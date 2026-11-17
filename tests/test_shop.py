"""Shop integration, replay, rollback and concurrency on disposable SQLite only."""
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import re
import sqlite3
from threading import Barrier
import unittest
from unittest.mock import patch
from uuid import uuid4
import app as application
import test_branch_flow as fixtures
from test_wallet import ClosingConnection


PRICE=1990000


class ShopTests(unittest.TestCase):
    def setUp(self):
        self.fixture=fixtures.BranchFlowTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.path=Path(__file__).with_name(f'.shop-test-{uuid4().hex}.sqlite')
        self.addCleanup(self.path.unlink,missing_ok=True)
        db=sqlite3.connect(self.path)
        self.fixture.db.backup(db)
        db.executescript('''
            INSERT INTO orders(id,user_id,total_price,total_calories) VALUES(1,1,1990500,10);
            INSERT INTO wallets(id,user_id,balance) VALUES(1,1,1990500),(2,2,7000000);
            INSERT INTO wallet_transactions(wallet_id,order_id,type,amount) VALUES(1,1,'earn',1990500);
        ''')
        db.commit();db.close()
        self.enterContext(patch('app.get_db_connection',side_effect=self.connect))
        self.client=self.login(1)

    def connect(self):
        db=sqlite3.connect(self.path,timeout=10)
        db.execute('PRAGMA foreign_keys=ON')
        return ClosingConnection(db)

    def login(self,user_id):
        client=application.app.test_client()
        with client.session_transaction() as session:session['user_id']=user_id
        return client

    def sql(self,query,args=()):
        db=self.connect().db
        try:
            cursor=db.execute(query,args)
            rows=cursor.fetchall();db.commit();return rows
        finally:db.close()

    def form(self,client=None):
        html=(client or self.client).get('/shop').get_data(as_text=True)
        return {name:re.search(f'name="{name}" value="([^"]+)"',html)[1]
                for name in ('shop_csrf_token','purchase_offer')}

    def buy(self,form=None,client=None):
        return (client or self.client).post('/shop/1/purchase',data=form or self.form(),follow_redirects=True)

    def state(self):
        return [self.sql(query) for query in ('SELECT * FROM wallets ORDER BY id','SELECT * FROM wallet_transactions ORDER BY id','SELECT * FROM point_purchases ORDER BY id')]

    def test_guest_restricted_and_member_catalog(self):
        guest=application.app.test_client()
        self.assertEqual(guest.get('/shop').location,'/login')
        self.assertEqual(guest.post('/shop/1/purchase').location,'/login')
        html=self.client.get('/shop').get_data(as_text=True)
        self.assertIn('1,990,500',html)
        self.assertIn('어른폰 18',html)
        self.assertIn('data-can-purchase="true"',html)
        self.assertIn('aria-current="page"',html)

    def test_insufficient_and_no_wallet_cannot_purchase(self):
        self.sql('UPDATE wallets SET balance=106420 WHERE user_id=1')
        html=self.client.get('/shop').get_data(as_text=True)
        self.assertIn('1,883,580',html)
        self.assertIn('data-can-purchase="false"',html)
        form=self.form();before=self.state()
        self.assertIn('부족합니다',self.buy(form).get_data(as_text=True))
        self.assertEqual(self.state(),before)
        self.sql('DELETE FROM wallet_transactions WHERE wallet_id=1')
        self.sql('DELETE FROM wallets WHERE user_id=1')
        self.assertIn('부족합니다',self.buy().get_data(as_text=True))
        self.assertEqual(self.sql('SELECT COUNT(*) FROM point_purchases'),[(0,)])

    def test_purchase_debit_snapshot_wallet_and_statistics(self):
        before_orders=self.sql('SELECT * FROM orders')
        before_earn=self.sql("SELECT * FROM wallet_transactions WHERE type='earn'")
        saving=self.client.get('/saving').get_data(as_text=True)
        form=self.form();form.update(price='1',user_id='2',balance='99999999')
        html=self.buy(form).get_data(as_text=True)
        self.assertIn('가상 구매가 완료되었습니다.',html)
        self.assertEqual(self.sql('SELECT balance FROM wallets WHERE user_id=1'),[(500,)])
        self.assertEqual(self.sql('SELECT user_id,product_name,price_points FROM point_purchases'),[(1,'어른폰 18',PRICE)])
        self.assertEqual(self.sql("SELECT amount,order_id FROM wallet_transactions WHERE type='spend'"),[(PRICE,None)])
        self.assertEqual(self.sql('SELECT * FROM orders'),before_orders)
        self.assertEqual(self.sql("SELECT * FROM wallet_transactions WHERE type='earn'"),before_earn)
        self.assertEqual(self.client.get('/saving').get_data(as_text=True),saving)
        wallet=self.client.get('/wallet').get_data(as_text=True)
        self.assertIn('500 포인트',wallet)
        self.assertIn('−1,990,000 포인트',wallet)
        self.assertIn('+1,990,500 포인트',wallet)
        self.sql("UPDATE point_products SET name='변경된 상품',price_points=100 WHERE id=1")
        self.assertEqual(self.sql('SELECT product_name,price_points FROM point_purchases'),[('어른폰 18',PRICE)])
        self.assertIn('이미 처리된 구매',self.buy(form).get_data(as_text=True))
        self.assertEqual(self.sql('SELECT balance FROM wallets WHERE user_id=1'),[(500,)])

    def test_csrf_offer_expiry_and_user_binding(self):
        form=self.form();before=self.state()
        for changed in ({**form,'shop_csrf_token':'bad'},{**form,'purchase_offer':form['purchase_offer']+'tampered'}):
            self.buy(changed)
            self.assertEqual(self.state(),before)
        other=self.login(2);other_form=self.form(other)
        self.buy({**form,'purchase_offer':other_form['purchase_offer']})
        self.assertEqual(self.state(),before)
        with patch('app.shop_signer') as signer:
            signer.return_value.loads.side_effect=application.SignatureExpired('expired')
            response=self.client.post('/shop/1/purchase',data=form)
        self.assertEqual(response.status_code,303)
        self.assertEqual(self.state(),before)

    def test_inactive_changed_price_and_unknown_product(self):
        form=self.form();before=self.state()
        self.sql('UPDATE point_products SET is_active=0 WHERE id=1')
        self.assertIn('구매할 수 없는 상품',self.buy(form).get_data(as_text=True))
        self.sql('UPDATE point_products SET is_active=1,price_points=2000000 WHERE id=1')
        self.assertIn('가격이 변경되었습니다',self.buy(form).get_data(as_text=True))
        self.client.post('/shop/999/purchase',data=form)
        self.assertEqual(self.state(),before)

    def test_purchase_and_ledger_failures_roll_back_everything(self):
        for table in ('wallet_transactions','point_purchases'):
            with self.subTest(table=table):
                form=self.form();before=self.state()
                self.sql(f"CREATE TRIGGER fail_insert BEFORE INSERT ON {table} BEGIN SELECT RAISE(ABORT,'private-error-detail'); END")
                html=self.buy(form).get_data(as_text=True)
                self.assertIn('구매를 처리하지 못했습니다',html)
                self.assertNotIn('private-error-detail',html)
                self.assertEqual(self.state(),before)
                self.sql('DROP TRIGGER fail_insert')

    def test_member_purchase_history_isolation(self):
        self.buy()
        other=self.login(2)
        html=other.get('/shop?user_id=1').get_data(as_text=True)
        self.assertIn('아직 구매한 상품이 없습니다.',html)
        self.assertIn('7,000,000',html)
        self.assertNotIn('500 포인트',html)
        self.assertIn('아직 사용한 포인트가 없습니다.',other.get('/wallet').get_data(as_text=True))

    def race(self,forms):
        cookie=self.client.get_cookie(application.app.config['SESSION_COOKIE_NAME']).value
        gate=Barrier(len(forms))
        def run(form):
            client=application.app.test_client()
            client.set_cookie(application.app.config['SESSION_COOKIE_NAME'],cookie)
            gate.wait(timeout=10)
            return self.buy(form,client).get_data(as_text=True)
        with ThreadPoolExecutor(max_workers=len(forms)) as pool:return list(pool.map(run,forms))

    def test_concurrent_same_request_charges_once(self):
        form=self.form()
        results=self.race([form,form])
        self.assertTrue(any('이미 처리된 구매' in result for result in results))
        self.assertEqual(self.sql('SELECT balance FROM wallets WHERE user_id=1'),[(500,)])
        self.assertEqual(self.sql('SELECT COUNT(*) FROM point_purchases'),[(1,)])
        self.assertEqual(self.sql("SELECT COUNT(*) FROM wallet_transactions WHERE type='spend'"),[(1,)])

    def test_concurrent_different_requests_cannot_overspend(self):
        forms=[self.form(),self.form()]
        results=self.race(forms)
        self.assertTrue(any('부족합니다' in result for result in results))
        self.assertEqual(self.sql('SELECT balance FROM wallets WHERE user_id=1'),[(500,)])
        self.assertEqual(self.sql('SELECT COUNT(*) FROM point_purchases'),[(1,)])

    def test_ten_percent_earnings_after_purchase(self):
        self.buy()
        snapshot=json.dumps(dict(preparation=480,duration=120,scale=10,path=[dict(lat=37,lng=127),dict(lat=37.01,lng=127.01)]))
        self.sql("INSERT INTO orders(id,user_id,order_date,total_price,total_calories,delivery_snapshot) VALUES(2,1,datetime('now','-100 seconds'),20009,500,?)",(snapshot,))
        self.client.get('/wallet');self.client.get('/wallet')
        self.assertEqual(self.sql('SELECT balance FROM wallets WHERE user_id=1'),[(2500,)])
        self.assertEqual(self.sql("SELECT amount FROM wallet_transactions WHERE type='earn' AND order_id=2"),[(2000,)])

    def test_logout_clears_shop_csrf(self):
        self.form()
        self.client.get('/logout')
        with self.client.session_transaction() as session:self.assertNotIn('shop_csrf_token',session)
        self.assertEqual(self.client.get('/shop').location,'/login')

    def test_incomplete_goal_never_rounds_up_to_one_hundred(self):
        self.sql('UPDATE wallets SET balance=? WHERE user_id=1',(PRICE-1,))
        html=self.client.get('/shop').get_data(as_text=True)
        self.assertIn('99.9%',html)
        self.assertIn('data-can-purchase="false"',html)

    def test_account_switch_clears_shop_csrf_and_old_offer(self):
        from werkzeug.security import generate_password_hash
        form=self.form()
        self.sql('UPDATE users SET username=?,password=?,nickname=? WHERE id=2',('other-member',generate_password_hash('test-password'),'다른 회원'))
        self.client.post('/login',data={'username':'other-member','password':'test-password'})
        with self.client.session_transaction() as session:
            self.assertEqual(session['user_id'],2)
            self.assertNotIn('shop_csrf_token',session)
        before=self.state()
        self.buy(form)
        self.assertEqual(self.state(),before)

    def test_exact_balance_can_be_spent_to_zero(self):
        self.sql('UPDATE wallets SET balance=? WHERE user_id=1',(PRICE,))
        self.assertIn('가상 구매가 완료되었습니다.',self.buy().get_data(as_text=True))
        self.assertEqual(self.sql('SELECT balance FROM wallets WHERE user_id=1'),[(0,)])

    def test_concurrent_earning_and_purchase_keep_balance_consistent(self):
        snapshot=json.dumps(dict(preparation=480,duration=120,scale=10,path=[dict(lat=37,lng=127),dict(lat=37.01,lng=127.01)]))
        self.sql("INSERT INTO orders(id,user_id,order_date,total_price,total_calories,delivery_snapshot) VALUES(2,1,datetime('now','-100 seconds'),20000,500,?)",(snapshot,))
        form=self.form()
        cookie=self.client.get_cookie(application.app.config['SESSION_COOKIE_NAME']).value
        gate=Barrier(2)
        def run(kind):
            client=application.app.test_client()
            client.set_cookie(application.app.config['SESSION_COOKIE_NAME'],cookie)
            gate.wait(timeout=10)
            return client.get('/wallet') if kind=='earn' else client.post('/shop/1/purchase',data=form)
        with ThreadPoolExecutor(max_workers=2) as pool:
            results=list(pool.map(run,['earn','purchase']))
        self.assertEqual([r.status_code for r in results],[200,303])
        self.assertEqual(self.sql('SELECT balance FROM wallets WHERE user_id=1'),[(2500,)])
        self.assertEqual(self.sql('SELECT COUNT(*) FROM point_purchases'),[(1,)])
        self.assertEqual(self.sql("SELECT amount FROM wallet_transactions WHERE order_id=2 AND type='earn'"),[(2000,)])


if __name__=='__main__':unittest.main()
