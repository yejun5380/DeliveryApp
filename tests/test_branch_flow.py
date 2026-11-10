"""Flask integration with an isolated SQLite SQL adapter and mocked Kakao HTTP.

Never connects to or migrates the user's MySQL database. MySQL locks/DDL need
separate deployment verification; real checkout/search/cart code is exercised.
"""
from datetime import date, datetime
import json
import os
import re
import sqlite3
import unittest
from unittest.mock import Mock, patch

from flask import template_rendered

import app as application
from branches import SearchCache
from test_branches import MAPPINGS, place


WALLET_SCHEMA = """
    CREATE TABLE wallets(
        id INTEGER PRIMARY KEY, user_id INTEGER NOT NULL UNIQUE REFERENCES users(id),
        balance INTEGER NOT NULL DEFAULT 0 CHECK(typeof(balance)='integer' AND balance >= 0)
    );
    CREATE TABLE wallet_transactions(
        id INTEGER PRIMARY KEY, wallet_id INTEGER NOT NULL REFERENCES wallets(id),
        order_id INTEGER REFERENCES orders(id), type TEXT NOT NULL,
        amount INTEGER NOT NULL CHECK(typeof(amount)='integer' AND amount >= 0),
        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        UNIQUE(order_id, type), CHECK(type <> 'earn' OR order_id IS NOT NULL)
    );
"""


class Cursor:
    def __init__(self, db):
        self.db = db
        self.cursor = db.cursor()
        self.lastrowid = None

    def execute(self, sql, args=()):
        sql = sql.replace(' FOR UPDATE', '').replace(' FOR SHARE', '')
        sql = sql.replace('TIMESTAMPDIFF(MICROSECOND,order_date,NOW(6))/1000000',
                          "unixepoch('now') - unixepoch(order_date)")
        sql = sql.replace('NOW()', 'CURRENT_TIMESTAMP')
        sql = sql.replace('%s', '?')
        branch_insert = 'ON DUPLICATE KEY UPDATE' in sql
        if branch_insert:
            sql = sql.split('ON DUPLICATE KEY UPDATE')[0] + '''ON CONFLICT(restaurant_id,provider,place_id)
                DO UPDATE SET place_name=excluded.place_name,road_address=excluded.road_address,
                lot_address=excluded.lot_address,lng=excluded.lng,lat=excluded.lat'''
        args = tuple(value.isoformat(' ') if isinstance(value, datetime)
                     else value.isoformat() if isinstance(value, date) else value for value in args)
        self.cursor.execute(sql, args)
        self.lastrowid = self.cursor.lastrowid
        if branch_insert:
            self.lastrowid = self.db.execute("SELECT id FROM restaurant_branches WHERE restaurant_id=? AND place_id=?", args[:2]).fetchone()[0]

    def convert(self, row):
        if row is None:
            return None
        return tuple(datetime.fromisoformat(value) if column[0] in ('order_date', 'as_of') and isinstance(value, str)
                     else date.fromisoformat(value) if column[0] == 'saving_day' and isinstance(value, str)
                     else value for column, value in zip(self.cursor.description, row))

    def fetchone(self):
        return self.convert(self.cursor.fetchone())

    def fetchall(self):
        return [self.convert(row) for row in self.cursor.fetchall()]

    def close(self):
        self.cursor.close()


class Connection:
    def __init__(self, db):
        self.db = db

    def cursor(self, **kwargs):
        return Cursor(self.db)

    def commit(self):
        self.db.commit()

    def start_transaction(self):
        self.db.execute('BEGIN IMMEDIATE')

    def rollback(self):
        self.db.rollback()

    def close(self):
        pass


class BranchFlowTests(unittest.TestCase):
    def setUp(self):
        self.db = sqlite3.connect(':memory:')
        self.addCleanup(self.db.close)
        self.db.executescript('''
            PRAGMA foreign_keys=ON;
            CREATE TABLE users(id INTEGER PRIMARY KEY, address TEXT,username TEXT UNIQUE,password TEXT,nickname TEXT);
            CREATE TABLE restaurants(id INTEGER PRIMARY KEY,name TEXT,category TEXT,description TEXT,image TEXT,address TEXT);
            CREATE TABLE menus(id INTEGER PRIMARY KEY,restaurant_id INTEGER,name TEXT,price INTEGER,calories INTEGER,description TEXT,image TEXT);
            CREATE TABLE restaurant_brand_mappings(restaurant_id INTEGER PRIMARY KEY,brand_name TEXT,aliases TEXT,enabled INTEGER DEFAULT 1);
            CREATE TABLE restaurant_branches(id INTEGER PRIMARY KEY AUTOINCREMENT,restaurant_id INTEGER,provider TEXT,place_id TEXT,place_name TEXT,road_address TEXT,lot_address TEXT,lng REAL,lat REAL,updated_at TEXT DEFAULT CURRENT_TIMESTAMP,UNIQUE(restaurant_id,provider,place_id));
            CREATE TABLE orders(id INTEGER PRIMARY KEY AUTOINCREMENT,user_id INTEGER,order_date TEXT DEFAULT CURRENT_TIMESTAMP,total_price INTEGER,total_calories INTEGER,delivery_address TEXT,delivery_snapshot TEXT,request_token TEXT UNIQUE,status TEXT NOT NULL DEFAULT 'active',cancelled_at TEXT);
            CREATE TABLE order_restaurants(id INTEGER PRIMARY KEY AUTOINCREMENT,order_id INTEGER,restaurant_id INTEGER,branch_id INTEGER,virtual_name TEXT,brand_name TEXT,place_id TEXT,place_name TEXT,road_address TEXT,lot_address TEXT,lng REAL,lat REAL,road_distance REAL,road_duration REAL,route_snapshot TEXT,UNIQUE(order_id,id));
            CREATE TABLE order_items(id INTEGER PRIMARY KEY AUTOINCREMENT,order_id INTEGER,menu_id INTEGER,quantity INTEGER,price INTEGER,calories INTEGER,order_restaurant_id INTEGER,FOREIGN KEY(order_id,order_restaurant_id) REFERENCES order_restaurants(order_id,id));
            INSERT INTO users(id,address) VALUES(1,'인천 주소'),(2,'전주 주소');
        ''')
        self.db.executescript(WALLET_SCHEMA)
        for identity, name, brand in MAPPINGS:
            self.db.execute('INSERT INTO restaurants VALUES(?,?,\'음식점\',\'가상 설명\',NULL,\'기존 고정 주소\')', (identity, name))
            self.db.execute('INSERT INTO menus VALUES(?,?,?,100,20,\'가상 메뉴\',NULL)', (identity, identity, name+' 메뉴'))
            self.db.execute('INSERT INTO restaurant_brand_mappings VALUES(?,?,?,1)', (identity, brand, json.dumps([brand])))
        self.db.commit()
        application.app.config.update(TESTING=True, SECRET_KEY='branch-flow-test')
        self.client = application.app.test_client()
        self.road_distance = 10000
        self.http_calls = []
        self.fail_directions = False
        self.empty_search = False
        for patcher in (patch('app.get_db_connection', side_effect=lambda: Connection(self.db)),
                        patch('branches.search_cache', SearchCache()),
                        patch('branches.coordinate_cache', SearchCache()),
                        patch.dict(os.environ, KAKAO_REST_API_KEY='test'),
                        patch('delivery.requests.get', side_effect=self.http)):
            patcher.start()
            self.addCleanup(patcher.stop)
        with self.client.session_transaction() as session:
            session['user_id'] = 1

    def http(self, url, **kwargs):
        self.http_calls.append((url, kwargs['params']))
        params = kwargs['params']
        if '/address.json' in url:
            x, y = (126.7,37.45) if params['query'] == '인천 주소' else (127.15,35.82)
            data = {'documents': [{'x': str(x), 'y': str(y)}]}
        elif '/keyword.json' in url:
            brand, x, y = params['query'], float(params['x']), float(params['y'])
            docs = [place(str(101+i), brand+suffix, x=str(x+0.001*(i+1)), y=str(y),
                          category_name='음식점 > '+brand) for i,suffix in enumerate((' 가까운점',' 두번째점'))]
            data = {'documents': [] if self.empty_search else docs, 'meta': {'is_end': True}}
        else:
            if self.fail_directions:
                import requests
                raise requests.Timeout('do-not-log-this')
            x,y = map(float, params['origin'].split(','))
            data = {'routes': [{'result_code': 0, 'summary': {'distance': self.road_distance,'duration':120},
                               'sections': [{'roads':[{'vertexes':[x,y,x+0.01,y+0.01]}]}]}]}
        response = Mock()
        response.json.return_value = data
        return response

    def search(self, restaurant_id=1):
        response = self.client.get(f'/restaurant/{restaurant_id}/branches')
        self.assertEqual(response.status_code, 200, response.get_data(as_text=True))
        return response.json['places']

    def add(self, selection, menu_id='1', **extras):
        return self.client.post('/cart/add', data=dict(menu_id=menu_id,selection_token=selection['selection_token'],**extras))

    def submit(self, fingerprint):
        with self.client.session_transaction() as session:
            token = session['order_token']
        return self.client.post('/order', data={'order_token':token,'fingerprint':fingerprint})

    def test_all_nine_brand_queries_use_mapping_and_original_menu(self):
        for identity, name, brand in MAPPINGS:
            selections = self.search(identity)
            self.assertTrue(selections[0]['display_name'].startswith(name))
            self.assertNotIn('place_name', selections[0])
            self.assertTrue(self.db.execute('SELECT place_name FROM restaurant_branches WHERE id=?', (selections[0]['branch_id'],)).fetchone()[0].startswith(brand))
            self.assertEqual(self.add(selections[0], str(identity)).status_code, 302)
        self.assertEqual(self.db.execute('SELECT COUNT(*) FROM restaurants').fetchone()[0], 9)
        self.assertEqual(self.db.execute('SELECT SUM(price),SUM(calories) FROM menus').fetchone(), (900,180))
        self.assertEqual({p['query'] for url,p in self.http_calls if 'keyword.json' in url}, {b for _,_,b in MAPPINGS})

    def test_home_search_links_and_navigation_selection(self):
        guest = application.app.test_client()
        home = guest.get('/').get_data(as_text=True)
        self.assertIn('href="/" aria-current="page"', home)
        self.assertIn('class="app-card shortcut-card wallet-shortcut" href="/wallet"', home)
        self.assertIn('href="/login"', home)
        self.assertIn('href="/signup"', home)
        self.assertEqual(guest.get('/wallet').location, '/login')

        identity, name, _ = MAPPINGS[0]
        response = self.client.get('/', query_string={'search': f'{name} 메뉴'})
        html = response.get_data(as_text=True)
        self.assertIn(f'href="/restaurant/{identity}"', html)
        self.assertNotIn(f'href="/restaurant/{MAPPINGS[1][0]}"', html)
        self.assertIn('href="/cart"', html)
        self.assertIn('href="/logout"', html)
        for path in ('/orders', '/saving', '/wallet'):
            page = self.client.get(path)
            self.assertEqual(page.status_code, 200)
            self.assertIn(f'href="{path}" aria-current="page"', page.get_data(as_text=True))

    def test_saving_periods_use_database_clock_and_fill_empty_buckets(self):
        orders = [
            (1, '2025-01-31 23:59:59', 2, 'active'),
            (1, '2025-02-01 00:00:00', 4, 'active'),
            (1, '2025-11-10 00:00:00', 8, 'active'),  # Before the first weekly bucket.
            (1, '2025-11-17 00:00:00', 16, 'active'),
            (1, '2025-12-29 23:59:59', 32, 'active'),
            (1, '2025-12-31 23:59:59', 64, 'active'),
            (1, '2026-01-01 00:00:00', 128, 'active'),
            (1, '2026-01-04 23:59:59', 256, 'active'),
            (1, '2026-01-05 00:00:00', 512, 'active'),
            (1, '2026-01-05 12:00:00', 1024, 'active'),
            (1, '2026-01-05 12:00:01', 2048, 'active'),
            (1, '2026-01-04 00:00:00', 4096, 'cancelled'),
            (2, '2026-01-04 00:00:00', 8192, 'active'),
        ]
        self.db.executemany('''INSERT INTO orders(user_id,order_date,total_price,status,total_calories)
                               VALUES(?,?,?,?,10)''', orders)
        self.db.commit()
        execute = Cursor.execute

        def fixed_clock(cursor, sql, args=()):
            if sql == 'SELECT CURRENT_TIMESTAMP AS as_of':
                return execute(cursor, 'SELECT %s AS as_of', ('2026-01-05 12:00:00',))
            return execute(cursor, sql, args)

        rendered = Mock()
        with patch.object(Cursor, 'execute', fixed_clock), template_rendered.connected_to(rendered, application.app):
            response = self.client.get('/saving')
        self.assertEqual(response.status_code, 200)
        context = rendered.call_args.kwargs['context']
        series = context['saving_periods']
        self.assertEqual(context['saving_data'], (10, 2046, 100))
        self.assertEqual([row['amount'] for row in series['daily']['rows']], [0, 64, 128, 0, 0, 256, 1536])
        self.assertEqual([row['amount'] for row in series['weekly']['rows']], [16, 0, 0, 0, 0, 0, 480, 1536])
        self.assertEqual([row['amount'] for row in series['monthly']['rows']], [4] + [0] * 8 + [24, 96, 1920])
        self.assertEqual(series['monthly']['rows'][0]['label'], '2025-02')
        self.assertEqual(series['monthly']['rows'][-1]['label'], '2026-01')
        self.assertEqual(series['weekly']['rows'][-2]['label'], '2025-12-29 ~ 01-04')
        self.assertIn('1,984원', response.get_data(as_text=True))

    def test_saving_requires_login_and_renders_empty_periods(self):
        with patch('app.get_db_connection') as connect:
            self.assertEqual(application.app.test_client().get('/saving').location, '/login')
            connect.assert_not_called()
        response = self.client.get('/saving')
        self.assertEqual(response.get_data(as_text=True).count('이 기간에 표시할 절약 금액이 없습니다.'), 3)

    def test_same_menu_two_branches_and_quantity_buttons(self):
        first, second = self.search()
        self.add(first)
        self.add(second)
        with self.client.session_transaction() as session:
            cart = dict(session['cart'])
        self.assertEqual(cart, {f"1:{first['branch_id']}":1, f"1:{second['branch_id']}":1})
        key = f"1:{first['branch_id']}"
        self.assertEqual(self.client.post('/cart/add', data={'cart_key':key}).status_code,302)
        with self.client.session_transaction() as session:
            self.assertEqual(session['cart'][key], 2)
        self.client.post('/cart/minus', data={'cart_key':key})
        self.client.post('/cart/delete', data={'cart_key':key})
        with self.client.session_transaction() as session:
            self.assertEqual(session['cart'], {f"1:{second['branch_id']}":1})

    def test_legacy_cart_preserved_and_reselection_preserves_quantity(self):
        with self.client.session_transaction() as session:
            session['cart'] = {'1':3}
        response = self.client.get('/cart')
        self.assertIn('지점을 다시 선택', response.get_data(as_text=True))
        self.assertEqual(self.client.post('/cart/delivery-check').status_code,422)
        selection = self.search()[0]
        response = self.client.post('/cart/reselect',data={'cart_key':'1','selection_token':selection['selection_token']})
        self.assertEqual(response.status_code,302)
        with self.client.session_transaction() as session:
            self.assertEqual(session['cart'],{f"1:{selection['branch_id']}":3})

    def test_reselection_merges_same_branch_without_losing_quantity(self):
        first, second = self.search()
        self.add(first)
        self.add(second)
        response = self.client.post('/cart/reselect', data={'cart_key':f"1:{first['branch_id']}",'selection_token':second['selection_token']})
        self.assertEqual(response.status_code,302)
        with self.client.session_transaction() as session:
            self.assertEqual(session['cart'],{f"1:{second['branch_id']}":2})

    def test_member_address_changes_location_and_invalidates_old_cart(self):
        selection = self.search()[0]
        self.add(selection)
        self.db.execute("UPDATE users SET address='전주 주소' WHERE id=1")
        self.db.commit()
        self.assertEqual(self.client.post('/cart/delivery-check').status_code,422)
        self.assertEqual(self.add(selection).status_code,422)
        new_selection = self.search()[0]
        self.assertGreater(new_selection['lng'],127)
        self.assertLess(new_selection['lat'],36)
        self.assertEqual(self.add(new_selection).status_code,302)

    def test_forged_token_wrong_brand_and_cross_user_selection_blocked(self):
        selection = self.search()[0]
        self.assertEqual(self.add(dict(selection,selection_token='forged')).status_code,422)
        self.assertEqual(self.add(selection,menu_id='2').status_code,422)
        with self.client.session_transaction() as session:
            session['user_id'] = 2
        self.assertEqual(self.add(selection).status_code,422)

    def test_expired_selection_and_unknown_branch_blocked(self):
        import time
        selection = self.search()[0]
        with patch('itsdangerous.timed.time.time', return_value=time.time()+901):
            self.assertEqual(self.add(selection).status_code,422)
        with self.client.session_transaction() as session:
            session['cart'] = {'1:999999':1}
        self.assertEqual(self.client.post('/cart/delivery-check').status_code,422)

    def test_search_pagination_and_authentication(self):
        for page in ('0','46','bad'):
            self.assertEqual(self.client.get('/restaurant/1/branches?page='+page).status_code,400)
        response = self.client.get('/restaurant/1/branches?page=2')
        self.assertEqual(response.json['page'],2)
        self.assertEqual([p for url,p in self.http_calls if 'keyword.json' in url][0]['page'],2)
        with self.client.session_transaction() as session:
            session.clear()
        self.assertEqual(self.client.get('/restaurant/1/branches').status_code,401)

    def test_two_selected_branches_one_over_limit_blocks_whole_order(self):
        first, second = self.search()
        self.add(first)
        self.add(second)
        original_http = self.http
        def mixed(url, **kwargs):
            if 'directions' in url:
                self.road_distance = 10001 if kwargs['params']['origin'].startswith(str(second['lng'])) else 10000
            return original_http(url, **kwargs)
        with patch('delivery.requests.get', side_effect=mixed):
            result = self.client.post('/cart/delivery-check').json
            self.assertEqual([r['status'] for r in result['restaurants']],['available','unavailable'])
            self.assertEqual(self.submit(result['fingerprint']).status_code,422)
        self.assertEqual(self.db.execute('SELECT COUNT(*) FROM orders').fetchone()[0],0)

    def test_full_cookie_rejects_addition_without_losing_existing_cart(self):
        self.add(self.search()[0])
        with self.client.session_transaction() as session:
            original_cart = dict(session['cart'])
        with patch('app.app.session_interface.get_signing_serializer') as factory:
            # Exercise save_cart directly, independently of Flask's cookie transport.
            serializer = factory.return_value
            serializer.dumps.side_effect = ['x'*3600,'x'*3000]
            with application.app.test_request_context('/'):
                application.session['cart'] = original_cart
                with self.assertRaisesRegex(Exception,'저장 공간'):
                    application.save_cart(dict(original_cart, **{'2:2':1}))
                self.assertEqual(application.session['cart'],original_cart)

    def test_client_coordinate_address_and_branch_id_manipulation_ignored(self):
        selection = self.search()[0]
        self.assertEqual(self.add(selection,lng='0',lat='0',address='조작 주소',branch_id='9999').status_code,302)
        result = self.client.post('/cart/delivery-check').json
        self.assertEqual(result['restaurants'][0]['branch']['lng'], selection['lng'])
        self.assertNotEqual(result['restaurants'][0]['branch']['address'], '조작 주소')

    def test_nearby_but_road_exceeds_10km_blocks_precheck_and_final(self):
        selection = self.search()[0]
        self.assertLess(selection['nearby_distance'],10000)
        self.add(selection)
        allowed = self.client.post('/cart/delivery-check').json
        self.assertEqual(allowed['status'],'available')
        self.road_distance = 10001
        self.assertEqual(self.submit(allowed['fingerprint']).status_code,422)
        blocked = self.client.post('/cart/delivery-check').json
        self.assertEqual(blocked['status'],'unavailable')
        self.assertEqual(self.db.execute('SELECT COUNT(*) FROM orders').fetchone()[0],0)

    def test_api_failure_after_successful_precheck_blocks_order(self):
        self.add(self.search()[0])
        result = self.client.post('/cart/delivery-check').json
        self.fail_directions = True
        response = self.submit(result['fingerprint'])
        self.assertEqual(response.status_code,422)
        self.assertNotIn('do-not-log-this',response.get_data(as_text=True))
        self.assertEqual(self.db.execute('SELECT COUNT(*) FROM orders').fetchone()[0],0)

    def test_complete_two_branch_order_snapshot_and_duplicate_retry(self):
        first, second = self.search()
        self.add(first)
        self.add(second)
        result = self.client.post('/cart/delivery-check').json
        self.assertEqual(len(result['restaurants']),2)
        before = sum('directions' in url for url,_ in self.http_calls)
        response = self.submit(result['fingerprint'])
        self.assertEqual(response.status_code,302)
        self.assertEqual(sum('directions' in url for url,_ in self.http_calls)-before,2)
        self.assertEqual(self.db.execute('SELECT COUNT(*) FROM order_restaurants').fetchone()[0],2)
        self.assertEqual(self.db.execute('SELECT COUNT(*) FROM order_items WHERE order_restaurant_id IS NOT NULL').fetchone()[0],2)
        self.assertEqual(self.submit(result['fingerprint']).status_code,302)
        self.assertEqual(self.db.execute('SELECT COUNT(*) FROM orders').fetchone()[0],1)
        self.assertEqual(self.db.execute('SELECT status FROM orders').fetchone()[0], 'active')
        self.assertEqual(self.db.execute('SELECT COUNT(*) FROM wallet_transactions').fetchone()[0], 0)
        self.assertIn('아직 적립된 주문이 없습니다.', self.client.get('/wallet').get_data(as_text=True))
        delivery = self.client.get('/delivery/1').get_data(as_text=True)
        self.assertIn('delivery-data', delivery)
        self.assertIn('라이더 대표 경로', delivery)
        self.assertEqual(self.client.get('/saving').status_code,200)
        self.assertEqual(self.client.get('/orders').status_code,200)

    def cancel_fixture(self, user_id=1, age=0, **snapshot_overrides):
        snapshot = dict(preparation=600, duration=120, scale=10,
                        path=[dict(lat=37, lng=127), dict(lat=38, lng=128)])
        snapshot.update(snapshot_overrides)
        cursor = self.db.execute("""INSERT INTO orders
            (user_id, order_date, total_price, total_calories, delivery_snapshot)
            VALUES (?, datetime('now', ?), 1234, 567, ?)""",
                                 (user_id, f'-{age} seconds', json.dumps(snapshot)))
        self.db.commit()
        return cursor.lastrowid

    def post_cancel(self, order_id):
        self.client.get('/orders')
        with self.client.session_transaction() as session:
            token = session['cancel_token']
        return self.client.post(f'/orders/{order_id}/cancel',
                                data={'cancel_token': token}, follow_redirects=True).get_data(as_text=True)

    def test_cancel_checkout_preserves_order_and_stops_delivery(self):
        self.add(self.search()[0])
        fingerprint = self.client.post('/cart/delivery-check').json['fingerprint']
        self.assertEqual(self.submit(fingerprint).status_code, 302)
        detail = self.client.get('/orders/1').get_data(as_text=True)
        self.assertIn('/orders/1/cancel', detail)
        self.assertIn('confirm(', detail)
        self.assertIn('주문이 취소되었습니다.', self.post_cancel(1))
        status, cancelled_at = self.db.execute('SELECT status, cancelled_at FROM orders').fetchone()
        self.assertEqual(status, 'cancelled')
        self.assertIsNotNone(cancelled_at)
        self.assertEqual(self.db.execute('SELECT COUNT(*) FROM order_items').fetchone()[0], 1)
        self.assertEqual(self.db.execute('SELECT COUNT(*) FROM order_restaurants').fetchone()[0], 1)
        detail = self.client.get('/orders/1').get_data(as_text=True)
        self.assertIn('취소 일시', detail)
        self.assertNotIn('/orders/1/cancel', detail)
        delivery = self.client.get('/delivery/1').get_data(as_text=True)
        self.assertIn('취소된 주문입니다.', delivery)
        self.assertNotIn('delivery.js', delivery)

    def test_cancel_rejects_other_users_order(self):
        order_id = self.cancel_fixture(user_id=2)
        self.assertIn('취소할 주문을 찾을 수 없습니다.', self.post_cancel(order_id))
        self.assertEqual(self.db.execute('SELECT status FROM orders').fetchone()[0], 'active')

    def test_cancel_requires_login_post_and_csrf(self):
        order_id = self.cancel_fixture()
        url = f'/orders/{order_id}/cancel'
        self.assertEqual(self.client.get(url).status_code, 405)
        self.client.get('/orders')
        for form in ({}, {'cancel_token': '잘못된 토큰'}):
            response = self.client.post(url, data=form, follow_redirects=True)
            self.assertIn('요청을 확인할 수 없습니다.', response.get_data(as_text=True))
        response = application.app.test_client().post(url)
        self.assertEqual(response.location, '/login')
        self.assertEqual(self.db.execute('SELECT status FROM orders').fetchone()[0], 'active')

    def test_duplicate_cancel_leaves_timestamp_unchanged(self):
        order_id = self.cancel_fixture()
        self.assertIn('주문이 취소되었습니다.', self.post_cancel(order_id))
        self.db.execute("UPDATE orders SET cancelled_at='2026-01-01 00:00:00'")
        self.db.commit()
        self.assertIn('이미 취소된 주문입니다.', self.post_cancel(order_id))
        self.assertEqual(self.db.execute('SELECT cancelled_at FROM orders').fetchone()[0],
                         '2026-01-01 00:00:00')

    def test_completion_uses_saved_scale_and_duration(self):
        completed = self.cancel_fixture(age=5, preparation=20, duration=30, scale=10)
        ongoing = self.cancel_fixture(age=90, duration=1000, scale=2)
        html = self.client.get('/orders').get_data(as_text=True)
        self.assertNotIn(f'/orders/{completed}/cancel', html)
        self.assertIn(f'/orders/{ongoing}/cancel', html)
        self.assertIn('배달이 완료된 주문은 취소할 수 없습니다.', self.post_cancel(completed))
        self.assertIn('주문이 취소되었습니다.', self.post_cancel(ongoing))

    def test_missing_or_damaged_delivery_data_blocks_cancel(self):
        for raw, date in ((None, '2026-01-01'), ('{', '2026-01-01'), ('{}', '2026-01-01')):
            with self.subTest(snapshot=raw):
                order_id = self.cancel_fixture()
                self.db.execute('UPDATE orders SET delivery_snapshot=?, order_date=? WHERE id=?',
                                (raw, date, order_id))
                self.db.commit()
                self.assertNotIn(f'/orders/{order_id}/cancel',
                                 self.client.get(f'/orders/{order_id}').get_data(as_text=True))
                self.assertIn('저장된 배달 정보를 확인할 수 없습니다.', self.post_cancel(order_id))
        missing_date = self.cancel_fixture()
        self.db.execute('UPDATE orders SET order_date=NULL WHERE id=?', (missing_date,))
        self.db.commit()
        self.assertIn('저장된 배달 정보를 확인할 수 없습니다.', self.post_cancel(missing_date))
        self.assertEqual(self.db.execute("SELECT COUNT(*) FROM orders WHERE status='cancelled'").fetchone()[0], 0)

    def test_cancelled_orders_are_excluded_from_savings(self):
        order_id = self.cancel_fixture()
        self.cancel_fixture()
        self.assertIn('2회', self.client.get('/saving').get_data(as_text=True))
        self.post_cancel(order_id)
        html = self.client.get('/saving').get_data(as_text=True)
        self.assertIn('1회', html)
        self.assertIn('1,234원', html)
        self.assertIn('567 kcal', html)
        self.assertNotIn('2,468원', html)
        self.assertNotIn('1,134 kcal', html)

    def reorder_fixture(self, both_branches=False):
        first, second = self.search()
        self.add(first)
        if both_branches:
            self.add(second)
        fingerprint = self.client.post('/cart/delivery-check').json['fingerprint']
        self.assertEqual(self.submit(fingerprint).location, '/order/complete')
        return first, second

    def reorder_form(self, client=None):
        client = client or self.client
        html = client.get('/orders').get_data(as_text=True)
        return {name: re.search(f'name="{name}" value="([^"]+)"', html)[1]
                for name in ('cancel_token', 'cart_revision')}

    def cart_state(self):
        with self.client.session_transaction() as session:
            return {key: session.get(key) for key in ('cart', 'branch_grants', 'order_token')}

    def test_reorder_preserves_history_and_uses_current_menu(self):
        self.reorder_fixture()
        queries = [f'SELECT * FROM {table} ORDER BY id'
                   for table in ('orders', 'order_items', 'order_restaurants')]
        history = [self.db.execute(sql).fetchall() for sql in queries]
        self.db.execute('UPDATE menus SET price=350, calories=25 WHERE id=1')
        self.db.commit()
        self.assertIn('/orders/1/reorder', self.client.get('/orders/1').get_data(as_text=True))
        before = len(self.http_calls)
        response = self.client.post('/orders/1/reorder', data=self.reorder_form())
        self.assertEqual((response.status_code, response.location), (303, '/cart'))
        self.assertTrue(any('keyword.json' in url for url, _ in self.http_calls[before:]))
        self.assertFalse(any('directions' in url for url, _ in self.http_calls[before:]))
        self.assertEqual([self.db.execute(sql).fetchall() for sql in queries], history)
        self.assertNotEqual(self.cart_state()['order_token'],
                            self.db.execute('SELECT request_token FROM orders').fetchone()[0])
        self.assertIn('350', self.client.get('/cart').get_data(as_text=True))
        self.road_distance = 10001
        check = self.client.post('/cart/delivery-check').json
        self.assertEqual(check['status'], 'unavailable')
        self.assertEqual(self.submit(check['fingerprint']).status_code, 422)
        self.road_distance = 10000
        fingerprint = self.client.post('/cart/delivery-check').json['fingerprint']
        self.assertEqual(self.submit(fingerprint).location, '/order/complete')
        self.assertEqual(self.db.execute('SELECT total_price,total_calories FROM orders ORDER BY id').fetchall(),
                         [(100, 20), (350, 25)])

    def test_reorder_cancelled_order_keeps_cancelled_status(self):
        self.reorder_fixture()
        self.assertIn('주문이 취소되었습니다.', self.post_cancel(1))
        self.assertIn('/orders/1/reorder', self.client.get('/orders').get_data(as_text=True))
        self.assertEqual(self.client.post('/orders/1/reorder', data=self.reorder_form()).location, '/cart')
        self.assertEqual(self.db.execute('SELECT status FROM orders').fetchall(), [('cancelled',)])
        self.assertIn('취소된 주문입니다.', self.client.get('/delivery/1').get_data(as_text=True))
        self.assertIn('아직 절약 기록이 없습니다.', self.client.get('/saving').get_data(as_text=True))

    def test_reorder_rejects_anonymous_bad_csrf_and_other_users(self):
        self.reorder_fixture()
        url = '/orders/1/reorder'
        self.assertEqual(application.app.test_client().post(url).location, '/login')
        self.assertEqual(self.client.get(url).status_code, 405)
        form = self.reorder_form()
        response = self.client.post(url, data={**form, 'cancel_token': '잘못됨'}, follow_redirects=True)
        self.assertIn('요청을 확인할 수 없습니다.', response.get_data(as_text=True))
        with self.client.session_transaction() as session:
            session['user_id'] = 2
        for order_id in (1, 99):
            response = self.client.post(f'/orders/{order_id}/reorder', data=form, follow_redirects=True)
            self.assertIn('재주문할 주문을 찾을 수 없습니다.', response.get_data(as_text=True))
        self.assertEqual(self.cart_state()['cart'], {})

    def test_reorder_merges_exact_branch_and_rejects_replay(self):
        first, second = self.reorder_fixture(both_branches=True)
        self.add(first)
        form = self.reorder_form()
        # A request already in flight can carry the original signed cart cookie.
        cookie_name = application.app.config['SESSION_COOKIE_NAME']
        parallel_client = application.app.test_client()
        parallel_client.set_cookie(cookie_name, self.client.get_cookie(cookie_name).value)
        self.assertEqual(self.client.post('/orders/1/reorder', data=form).location, '/cart')
        state = self.cart_state()
        self.assertEqual(state['cart'], {f"1:{first['branch_id']}": 2, f"1:{second['branch_id']}": 1})
        self.assertEqual(parallel_client.post('/orders/1/reorder', data=form).location, '/cart')
        with parallel_client.session_transaction() as session:
            self.assertEqual(session['cart'], state['cart'])
        response = self.client.post('/orders/1/reorder', data=form, follow_redirects=True)
        self.assertIn('이미 처리된 요청', response.get_data(as_text=True))
        self.assertEqual(self.cart_state(), state)

    def test_reorder_revalidates_current_address_and_uses_fresh_coordinates(self):
        self.reorder_fixture()
        self.db.execute("UPDATE users SET address='전주 주소' WHERE id=1")
        self.db.commit()
        self.assertEqual(self.client.post('/orders/1/reorder', data=self.reorder_form()).location, '/cart')
        _, params = next((url, p) for url, p in reversed(self.http_calls) if 'keyword.json' in url)
        self.assertEqual((params['x'], params['y']), (127.15, 35.82))
        self.assertAlmostEqual(self.db.execute("SELECT lng FROM restaurant_branches WHERE place_id='101'").fetchone()[0],
                               127.151)
        self.assertAlmostEqual(self.db.execute('SELECT lng FROM order_restaurants').fetchone()[0], 126.701)

    def test_reorder_failure_leaves_all_cart_items_and_grants_intact(self):
        first, _ = self.reorder_fixture(both_branches=True)
        self.add(first)
        form = self.reorder_form()
        state = self.cart_state()
        self.db.execute("UPDATE order_restaurants SET place_id='999' WHERE place_id='102'")
        self.db.commit()
        response = self.client.post('/orders/1/reorder', data=form, follow_redirects=True)
        self.assertIn('이전 주문의 지점을 찾을 수 없습니다.', response.get_data(as_text=True))
        self.assertEqual(self.cart_state(), state)
        self.db.execute('DELETE FROM menus WHERE id=1')
        self.db.commit()
        response = self.client.post('/orders/1/reorder', data=form, follow_redirects=True)
        self.assertIn('현재 판매하지 않는 메뉴', response.get_data(as_text=True))
        self.assertEqual(self.cart_state(), state)

    def test_reorder_quantity_cap_applies_to_merged_cart(self):
        first, _ = self.reorder_fixture()
        self.add(first)
        with self.client.session_transaction() as session:
            session['cart'] = {f"1:{first['branch_id']}": 99}
        form = self.reorder_form()
        state = self.cart_state()
        response = self.client.post('/orders/1/reorder', data=form, follow_redirects=True)
        self.assertIn('합산 수량은 메뉴·지점별 최대 99개', response.get_data(as_text=True))
        self.assertEqual(self.cart_state(), state)

    def test_branch_updates_do_not_change_historical_order(self):
        selection = self.search()[0]
        self.add(selection)
        fingerprint = self.client.post('/cart/delivery-check').json['fingerprint']
        self.submit(fingerprint)
        original = self.db.execute('SELECT delivery_snapshot FROM orders').fetchone()[0]
        self.db.execute("UPDATE restaurant_branches SET place_name='롯데리아 변경점',road_address='변경 주소',lng=128 WHERE id=?",(selection['branch_id'],))
        self.db.commit()
        detail = self.client.get('/orders/1').get_data(as_text=True)
        self.assertIn(selection['display_name'],detail)
        self.assertNotIn('롯데리아',detail)
        self.assertNotIn('변경 주소',detail)
        self.assertEqual(self.db.execute('SELECT delivery_snapshot FROM orders').fetchone()[0], original)
        snapshot = json.loads(original)
        self.assertEqual(snapshot['version'],2)
        self.assertEqual(snapshot['routes'][0]['branch']['lng'],selection['lng'])
        self.assertEqual(self.client.get('/delivery/1').status_code,200)

    def test_branch_updates_before_order_require_reselection(self):
        selection = self.search()[0]
        self.add(selection)
        fingerprint = self.client.post('/cart/delivery-check').json['fingerprint']
        self.db.execute("UPDATE restaurant_branches SET road_address='변경 주소' WHERE id=?", (selection['branch_id'],))
        self.db.commit()
        self.assertEqual(self.submit(fingerprint).status_code,422)

    def test_old_orders_without_branches_and_v1_snapshots_still_render(self):
        old = dict(version=1, duration=120,preparation=600,scale=10,representative='기존 음식점',
                   path=[dict(lat=37,lng=127),dict(lat=37.01,lng=127.01)],routes=[dict(name='기존 음식점',distance=4500,duration=120)])
        self.db.execute("INSERT INTO orders(user_id,total_price,total_calories,delivery_snapshot) VALUES(1,100,20,?)", (json.dumps(old),))
        self.db.execute('INSERT INTO order_items(order_id,menu_id,quantity,price,calories) VALUES(1,1,1,100,20)')
        self.db.commit()
        self.assertIn('저장된 실제 지점 정보 없음',self.client.get('/orders/1').get_data(as_text=True))
        self.assertEqual(self.client.get('/delivery/1').status_code,200)
        self.assertEqual(json.loads(self.db.execute('SELECT delivery_snapshot FROM orders').fetchone()[0]),old)

    def test_search_is_lazy_cached_and_no_results_have_no_fallback(self):
        self.assertEqual(self.client.get('/restaurant/1').status_code,200)
        self.assertEqual(self.http_calls,[])
        self.empty_search = True
        self.assertEqual(self.search(),[])
        self.assertEqual(self.search(),[])
        self.assertEqual(len(self.http_calls),2)  # one geocode + one search

    def test_signup_hashed_login_and_logout_regression(self):
        self.client.get('/logout')
        response = self.client.post('/signup',data={'username':'new-user','password':'test-password','nickname':'테스트 회원'})
        self.assertEqual(response.status_code,302)
        stored = self.db.execute("SELECT password FROM users WHERE username='new-user'").fetchone()[0]
        self.assertNotEqual(stored,'test-password')
        self.assertEqual(self.client.post('/login',data={'username':'new-user','password':'wrong'}).status_code,200)
        response = self.client.post('/login',data={'username':'new-user','password':'test-password'})
        self.assertEqual(response.status_code,302)
        self.assertEqual(self.client.get('/saving').status_code,200)
        self.client.get('/logout')
        self.assertEqual(self.client.get('/cart').status_code,302)

    def test_existing_plaintext_login_upgrade_keeps_same_member_cart(self):
        self.add(self.search()[0])
        with self.client.session_transaction() as session:
            original_cart = dict(session['cart'])
        self.db.execute("UPDATE users SET username='legacy',password='old-password',nickname='기존 회원' WHERE id=1")
        self.db.commit()
        response = self.client.post('/login',data={'username':'legacy','password':'old-password'})
        self.assertEqual(response.status_code,302)
        self.assertNotEqual(self.db.execute('SELECT password FROM users WHERE id=1').fetchone()[0],'old-password')
        with self.client.session_transaction() as session:
            self.assertEqual(session['cart'],original_cart)

    def test_existing_order_other_member_access_still_blocked(self):
        self.db.execute('INSERT INTO orders(user_id,total_price,total_calories) VALUES(2,100,20)')
        self.db.commit()
        self.assertEqual(self.client.get('/orders/1').status_code,302)
        self.assertEqual(self.client.get('/delivery/1').status_code,302)

    def test_public_names_across_search_cart_check_order_and_delivery(self):
        selection = self.search()[0]
        self.assertEqual(selection['display_name'],'옷데리아 가까운점')
        self.assertNotIn('롯데리아',json.dumps(selection,ensure_ascii=False))
        self.add(selection)
        for url in ('/','/restaurant/1','/cart'):
            response = self.client.get(url)
            self.assertEqual(response.status_code,200)
            self.assertNotIn('롯데리아',response.get_data(as_text=True))
        check = self.client.post('/cart/delivery-check').json
        self.assertNotIn('롯데리아',json.dumps(check,ensure_ascii=False))
        self.assertEqual(self.submit(check['fingerprint']).status_code,302)
        raw_snapshot = self.db.execute('SELECT delivery_snapshot FROM orders').fetchone()[0]
        self.assertIn('롯데리아',raw_snapshot)
        raw_place = self.db.execute('SELECT place_name,brand_name FROM order_restaurants').fetchone()
        self.assertEqual(raw_place,('롯데리아 가까운점','롯데리아'))
        for url in ('/order/complete','/orders','/orders/1','/delivery/1'):
            response = self.client.get(url)
            self.assertEqual(response.status_code,200)
            self.assertNotIn('롯데리아',response.get_data(as_text=True))
        self.assertEqual(self.db.execute('SELECT delivery_snapshot FROM orders').fetchone()[0],raw_snapshot)

    def test_distance_and_api_error_messages_use_virtual_names(self):
        self.add(self.search()[0])
        check = self.client.post('/cart/delivery-check').json
        self.road_distance = 10001
        response = self.submit(check['fingerprint'])
        self.assertEqual(response.status_code,422)
        self.assertIn('옷데리아 가까운점',response.get_data(as_text=True))
        self.assertNotIn('롯데리아',response.get_data(as_text=True))
        self.fail_directions = True
        result = self.client.post('/cart/delivery-check').json
        self.assertEqual(result['status'],'unknown')
        self.assertIn('옷데리아 가까운점',result['restaurants'][0]['name'])
        self.assertNotIn('롯데리아',json.dumps(result,ensure_ascii=False))


if __name__ == '__main__':
    unittest.main()
