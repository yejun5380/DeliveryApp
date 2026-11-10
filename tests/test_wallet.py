"""Isolated SQLite integration. BEGIN IMMEDIATE substitutes for MySQL row locks."""

from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import sqlite3
from threading import Barrier
import unittest
from unittest.mock import patch
from uuid import uuid4

import app as application
from test_branch_flow import Connection, WALLET_SCHEMA
from wallet import MAX_BALANCE, WalletError, reconcile_wallet


SNAPSHOT = dict(preparation=600, duration=120, scale=10,
                path=[dict(lat=37, lng=127), dict(lat=38, lng=128)])


class ClosingConnection(Connection):
    def close(self):
        self.db.close()


class WalletTests(unittest.TestCase):
    def setUp(self):
        self.path = Path(__file__).with_name(f'.wallet-test-{uuid4().hex}.sqlite')
        self.addCleanup(self.path.unlink, missing_ok=True)
        self.db = self.connect().db
        self.addCleanup(self.db.close)
        self.db.executescript("""
            CREATE TABLE users(id INTEGER PRIMARY KEY);
            INSERT INTO users VALUES (1), (2);
            CREATE TABLE orders(
                id INTEGER PRIMARY KEY, user_id INTEGER REFERENCES users(id),
                order_date TEXT DEFAULT CURRENT_TIMESTAMP, total_price INTEGER NOT NULL,
                total_calories INTEGER NOT NULL DEFAULT 10, delivery_snapshot TEXT,
                delivery_address TEXT, status TEXT NOT NULL DEFAULT 'active', cancelled_at TEXT
            );
        """)
        self.db.executescript(WALLET_SCHEMA)
        self.enterContext(patch('app.get_db_connection', side_effect=self.connect))
        self.enterContext(patch('app.load_display_catalog', return_value=[]))
        self.client = self.login()

    def connect(self):
        db = sqlite3.connect(self.path, timeout=10)
        db.execute('PRAGMA foreign_keys=ON')
        return ClosingConnection(db)

    def login(self, user_id=1):
        client = application.app.test_client()
        with client.session_transaction() as session:
            session['user_id'] = user_id
            session['cancel_token'] = 'wallet-test-csrf'
        return client

    def order(self, amount=100, user_id=1, age=100, status='active', raw=json.dumps(SNAPSHOT)):
        row = self.db.execute("""
            INSERT INTO orders(user_id, total_price, order_date, delivery_snapshot, status)
            VALUES (?, ?, datetime('now', ?), ?, ?)
        """, (user_id, amount, f'-{age} seconds', raw, status))
        self.db.commit()
        return row.lastrowid

    def ledger(self):
        return self.db.execute("SELECT order_id, amount FROM wallet_transactions ORDER BY order_id").fetchall()

    def balance(self):
        return self.db.execute("SELECT balance FROM wallets WHERE user_id=1").fetchone()

    def test_in_progress_visible_in_saving_but_not_credited(self):
        order_id = self.order(age=30)
        self.assertEqual(self.client.get(f'/delivery/{order_id}').status_code, 200)
        self.assertIn('아직 적립된 주문이 없습니다.', self.client.get('/wallet').get_data(as_text=True))
        self.assertIn('100원', self.client.get('/saving').get_data(as_text=True))
        self.assertEqual(self.ledger(), [])

    def test_completed_delivery_and_wallet_refresh_credit_only_once(self):
        order_id = self.order(age=72, amount=2400)
        self.assertEqual(self.client.get(f'/delivery/{order_id}').status_code, 200)
        self.assertEqual(self.balance(), (2400,))
        self.client.get(f'/delivery/{order_id}')
        html = self.client.get('/wallet').get_data(as_text=True)
        self.assertIn(f'주문 #{order_id}', html)
        self.assertIn('2,400 포인트', html)
        self.assertEqual(self.ledger(), [(order_id, 2400)])

    def test_only_valid_active_completed_orders_are_summed(self):
        first = self.order(amount=101)
        second = self.order(amount=202)
        self.order(status='cancelled')
        self.order(raw=None)
        self.order(raw='{')
        self.order(raw=json.dumps(dict(SNAPSHOT, path=[])))
        self.order(raw=json.dumps(dict(SNAPSHOT, routes=[None])))
        self.order(amount=-5)
        no_date = self.order()
        self.db.execute('UPDATE orders SET order_date=NULL WHERE id=?', (no_date,))
        self.db.commit()
        history = self.db.execute('SELECT * FROM orders ORDER BY id').fetchall()
        self.assertEqual(self.client.get('/wallet').status_code, 200)
        self.assertEqual(self.balance(), (303,))
        self.assertEqual(self.ledger(), [(first, 101), (second, 202)])
        self.assertEqual(self.db.execute('SELECT * FROM orders ORDER BY id').fetchall(), history)

    def test_wallet_and_delivery_are_scoped_to_member(self):
        foreign_order = self.order(user_id=2, amount=4321)
        self.login(2).get('/wallet')
        self.assertEqual(application.app.test_client().get('/wallet').location, '/login')
        self.assertEqual(self.client.get(f'/delivery/{foreign_order}').location, '/orders')
        html = self.client.get('/wallet?user_id=2').get_data(as_text=True)
        self.assertNotIn('4,321', html)
        self.assertNotIn(f'주문 #{foreign_order}', html)
        self.assertEqual(self.ledger(), [(foreign_order, 4321)])

    def concurrent_requests(self, callbacks):
        gate = Barrier(len(callbacks))

        def run(callback):
            client = self.login()
            gate.wait(timeout=10)
            return callback(client)

        with ThreadPoolExecutor(max_workers=len(callbacks)) as pool:
            return list(pool.map(run, callbacks))

    def test_two_devices_credit_all_orders_once(self):
        first = self.order(amount=123)
        second = self.order(amount=456)
        results = self.concurrent_requests([
            lambda c: c.get('/wallet'), lambda c: c.get('/wallet'),
            lambda c: c.get(f'/delivery/{first}'),
        ])
        self.assertTrue(all(response.status_code == 200 for response in results))
        self.assertEqual(self.balance(), (579,))
        self.assertEqual(self.ledger(), [(first, 123), (second, 456)])
        with self.assertRaises(sqlite3.IntegrityError):
            self.db.execute("""INSERT INTO wallet_transactions(wallet_id, order_id, type, amount)
                               SELECT id, ?, 'earn', 123 FROM wallets WHERE user_id=1""", (first,))
        self.db.rollback()
        with self.assertRaises(sqlite3.IntegrityError):
            self.db.execute("UPDATE wallets SET balance=-1")
        self.db.rollback()

    def test_cancel_racing_with_wallet_keeps_status_and_ledger_consistent(self):
        completed = self.order()
        in_progress = self.order(age=1)
        for order_id, message in ((completed, '배달이 완료된 주문은 취소할 수 없습니다.'),
                                  (in_progress, '주문이 취소되었습니다.')):
            wallet, cancel = self.concurrent_requests([
                lambda c: c.get('/wallet'),
                lambda c: c.post(f'/orders/{order_id}/cancel', data={'cancel_token': 'wallet-test-csrf'},
                                 follow_redirects=True),
            ])
            self.assertEqual(wallet.status_code, 200)
            self.assertIn(message, cancel.get_data(as_text=True))
        self.assertEqual(self.ledger(), [(completed, 100)])
        self.assertEqual(self.db.execute('SELECT status FROM orders ORDER BY id').fetchall(),
                         [('active',), ('cancelled',)])
        # The ledger still blocks cancellation if the clock moves backwards.
        self.db.execute('UPDATE orders SET order_date=CURRENT_TIMESTAMP WHERE id=?', (completed,))
        self.db.commit()
        response = self.client.post(f'/orders/{completed}/cancel', data={'cancel_token': 'wallet-test-csrf'},
                                    follow_redirects=True)
        self.assertIn('저금통에 적립된 주문은 취소할 수 없습니다.', response.get_data(as_text=True))

    def test_ledger_write_failure_rolls_back_wallet_and_all_credits(self):
        self.order()
        self.order()
        self.db.executescript("""
            CREATE TRIGGER fail_second_credit BEFORE INSERT ON wallet_transactions
            WHEN NEW.order_id=2 BEGIN SELECT RAISE(ABORT, 'test failure'); END;
        """)
        connection = self.connect()
        self.addCleanup(connection.close)
        with self.assertRaises(sqlite3.IntegrityError):
            reconcile_wallet(connection, 1)
        self.assertEqual(self.ledger(), [])
        self.assertIsNone(self.balance())

    def test_overflow_rolls_back_credit(self):
        self.order()
        self.db.execute('INSERT INTO wallets(user_id, balance) VALUES (1, ?)', (MAX_BALANCE,))
        self.db.commit()
        connection = self.connect()
        self.addCleanup(connection.close)
        with self.assertRaises(WalletError):
            reconcile_wallet(connection, 1)
        self.assertEqual(self.ledger(), [])
        self.assertEqual(self.balance(), (MAX_BALANCE,))
