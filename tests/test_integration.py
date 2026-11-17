"""Full user journeys against isolated SQLite and mocked Kakao; no real DB writes."""
import unittest
import hashlib
import json
from werkzeug.security import check_password_hash
import test_branch_flow as fixtures
import app as application


class IntegrationTests(unittest.TestCase):
    def setUp(self):
        self.flow = fixtures.BranchFlowTests()
        self.flow.setUp()
        self.addCleanup(self.flow.doCleanups)
        self.db, self.client = self.flow.db, self.flow.client
        self.db.execute("UPDATE restaurants SET category=CASE WHEN id<=3 THEN '햄버거' WHEN id<=6 THEN '치킨' ELSE '피자' END")
        self.db.commit()

    def register_login(self, username='journey-member'):
        self.client.get('/logout')
        self.assertEqual(self.client.post('/signup', data=dict(username=username, password='test-password', nickname='통합 테스트')).location, '/login')
        row = self.db.execute('SELECT id,password FROM users WHERE username=?', (username,)).fetchone()
        self.assertTrue(check_password_hash(row[1], 'test-password'))
        self.assertEqual(self.client.post('/login', data=dict(username=username, password='test-password')).location, '/')
        self.assertEqual(self.client.post('/address', data={'address': '인천 주소'}).location, '/address')
        return row[0]

    def checkout(self):
        selection = self.flow.search()[0]
        self.assertEqual(self.flow.add(selection).location, '/cart')
        key = f"1:{selection['branch_id']}"
        self.client.post('/cart/add', data={'cart_key': key})
        html = self.client.get('/cart').get_data(as_text=True)
        self.assertIn('200원', html)
        self.assertIn('40 kcal', html)
        fingerprint = self.client.post('/cart/delivery-check').json['fingerprint']
        self.assertEqual(self.flow.submit(fingerprint).location, '/order/complete')
        return self.db.execute('SELECT MAX(id) FROM orders').fetchone()[0]

    def test_complete_journey_cancel_reorder_credit_and_logout(self):
        user_id = self.register_login()
        home = self.client.get('/').get_data(as_text=True)
        self.assertIn('햄버거', home)
        for category in ('치킨', '피자', '햄버거'):
            html = self.client.get('/', query_string={'category': category}).get_data(as_text=True)
            self.assertEqual(html.count('app-card restaurant-card'), 3)
        self.assertIn('/restaurant/1', self.client.get('/', query_string={'category': '햄버거', 'search': '옷데리아 메뉴'}).get_data(as_text=True))
        self.assertEqual(self.client.get('/restaurant/1').status_code, 200)
        first = self.checkout()
        for path in ('/order/complete', '/orders', f'/orders/{first}', f'/delivery/{first}', '/wallet', '/saving'):
            response = self.client.get(path)
            self.assertEqual(response.status_code, 200, path)
            self.assertIn('class="app-shell"', response.get_data(as_text=True))
            if path in ('/order/complete', f'/delivery/{first}'):
                self.assertIn('href="/orders" aria-current="true"', response.get_data(as_text=True))
        with self.client.session_transaction() as session:
            self.assertFalse(session['cart'])
            cancel_token = session['cancel_token']
        self.assertEqual(self.db.execute('SELECT total_price,total_calories,user_id FROM orders WHERE id=?', (first,)).fetchone(), (200,40,user_id))
        self.client.post(f'/orders/{first}/cancel', data={'cancel_token': cancel_token})
        self.assertIn('주문 취소', self.client.get('/orders').get_data(as_text=True))
        self.assertIn('아직 절약 기록이 없습니다.', self.client.get('/saving').get_data(as_text=True))
        self.assertEqual(self.db.execute('SELECT COUNT(*) FROM wallet_transactions').fetchone()[0], 0)
        # Current prices apply to a reorder, while the cancelled historical order stays intact.
        self.db.execute('UPDATE menus SET price=350,calories=25 WHERE id=1')
        self.db.commit()
        self.assertEqual(self.client.post(f'/orders/{first}/reorder', data=self.flow.reorder_form()).location, '/cart')
        self.assertIn('700원', self.client.get('/cart').get_data(as_text=True))
        fingerprint = self.client.post('/cart/delivery-check').json['fingerprint']
        self.flow.submit(fingerprint)
        second = self.db.execute('SELECT MAX(id) FROM orders').fetchone()[0]
        self.db.execute("UPDATE orders SET order_date=datetime('now','-100 seconds') WHERE id=?", (second,))
        self.db.commit()
        for _ in range(3):
            self.client.get(f'/delivery/{second}')
            self.client.get('/wallet')
        self.assertEqual(self.db.execute('SELECT balance FROM wallets WHERE user_id=?', (user_id,)).fetchone()[0], 70)
        self.assertEqual(self.db.execute('SELECT COUNT(*) FROM wallet_transactions').fetchone()[0], 1)
        self.assertEqual(self.db.execute('SELECT status,total_price FROM orders WHERE id=?', (first,)).fetchone(), ('cancelled',200))
        self.flow.add(self.flow.search()[0])
        self.client.get('/logout')
        with self.client.session_transaction() as session:
            for key in ('user_id','nickname','cart','branch_grants','order_token','cancel_token','last_order_price','last_order_calories'):
                self.assertNotIn(key, session)

    def test_guest_access_and_cross_member_isolation(self):
        first = self.checkout()
        other = application.app.test_client()
        for path in ('/address','/cart','/orders',f'/orders/{first}',f'/delivery/{first}','/wallet','/saving','/order/complete'):
            self.assertEqual(other.get(path).location, '/login', path)
        self.assertEqual(other.get('/restaurant/1/branches').status_code,401)
        self.assertEqual(other.post('/cart/delivery-check').status_code,401)
        with other.session_transaction() as session:
            session['user_id'] = 2
        self.assertEqual(other.get(f'/orders/{first}').location, '/orders')
        self.assertEqual(other.get(f'/delivery/{first}').location, '/orders')
        self.assertIn('아직 주문(절약)내역이 없습니다.', other.get('/orders').get_data(as_text=True))
        self.assertIn('0 포인트', other.get('/wallet').get_data(as_text=True))
        self.assertIn('전주 주소', other.get('/address').get_data(as_text=True))
        with other.session_transaction() as session:
            revision = hashlib.sha256(json.dumps([session.get('order_token'),session.get('cart',{})],sort_keys=True).encode()).hexdigest()
            form = dict(cancel_token=session['cancel_token'],cart_revision=revision)
        other.post(f'/orders/{first}/reorder', data=form)
        other.post(f'/orders/{first}/cancel', data={'cancel_token': form['cancel_token']})
        self.assertEqual(self.db.execute('SELECT status FROM orders WHERE id=?',(first,)).fetchone()[0],'active')
        with other.session_transaction() as session:
            self.assertFalse(session.get('cart'))

    def test_account_switch_does_not_expose_previous_order_completion(self):
        self.checkout()
        self.client.post('/signup', data=dict(username='second-member',password='test-password',nickname='두 번째 회원'))
        self.client.post('/login', data=dict(username='second-member',password='test-password'))
        self.assertEqual(self.client.get('/order/complete').location, '/orders')
        with self.client.session_transaction() as session:
            self.assertNotIn('last_order_price', session)
            self.assertNotIn('last_order_calories', session)

    def test_sql_like_login_text_does_not_bypass_authentication(self):
        self.client.get('/logout')
        response = self.client.post('/login', data=dict(username="' OR 1=1 --",password='not-a-password'))
        self.assertIn('아이디 또는 비밀번호가 틀렸습니다.',response.get_data(as_text=True))
        with self.client.session_transaction() as session:
            self.assertNotIn('user_id',session)


if __name__ == '__main__':
    unittest.main()
