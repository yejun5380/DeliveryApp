import unittest
from datetime import datetime
from unittest.mock import Mock, patch
import app as application
from delivery import DeliveryError

BRANCH = dict(branch_id=1, restaurant_id=1, virtual_name='A', brand_name='롯데리아', place_id='123', place_name='롯데리아 테스트점', road_address='origin', lot_address='origin', address='origin', lng=127.0, lat=37.0)
DATA = ('address', [('1', 1, 100, 20, 1)], [BRANCH], 100, 20, 'fingerprint')
ROUTE = dict(name='A', status='available', distance=10000, duration=120,
             path=[dict(lat=37, lng=127), dict(lat=37.01, lng=127.01)], branch=BRANCH)


class CheckoutTests(unittest.TestCase):
    def setUp(self):
        application.app.config.update(TESTING=True, SECRET_KEY='test')
        self.client = application.app.test_client()
        self.connection = Mock()
        self.cursor = self.connection.cursor.return_value
        self.db = patch('app.get_db_connection', return_value=self.connection)
        member = patch('app.member_address', return_value='address')
        member.start()
        self.addCleanup(member.stop)
        catalog = patch('app.load_display_catalog', return_value=[dict(restaurant_id=1,virtual_name='A',aliases=['롯데리아'])])
        catalog.start()
        self.addCleanup(catalog.stop)
        self.db.start()
        self.addCleanup(self.db.stop)
        with self.client.session_transaction() as session:
            session.update(user_id=1, cart={'1': 1}, order_token='token')

    def order(self, **kwargs):
        return self.client.post('/order', data=dict(order_token='token', fingerprint='fingerprint', **kwargs))

    def test_final_order_rechecks_and_persists_snapshot(self):
        self.cursor.fetchone.return_value = None
        self.cursor.lastrowid = 7
        with patch('app.checkout_data', return_value=DATA), patch('app.inspect_delivery', return_value=[ROUTE]) as check:
            response = self.order()
        self.assertEqual(response.status_code, 302)
        check.assert_called_once()
        self.connection.commit.assert_called_once()
        inserts = [call.args for call in self.cursor.execute.call_args_list if 'INSERT INTO orders' in call.args[0]]
        self.assertIn('"duration": 120', inserts[0][1][4])
        with self.client.session_transaction() as session:
            self.assertEqual(session['cart'], {})

    def test_stale_address_or_cart_blocks_before_api(self):
        self.cursor.fetchone.return_value = None
        with patch('app.checkout_data', return_value=DATA[:-1]+('changed',)), patch('app.inspect_delivery') as check:
            self.assertEqual(self.order().status_code, 409)
            check.assert_not_called()
        self.connection.commit.assert_not_called()

    def test_final_distance_and_api_failure_block(self):
        self.cursor.fetchone.return_value = None
        for row in (dict(ROUTE, status='unavailable', distance=10001), dict(name='A', status='unknown', message='timeout')):
            with patch('app.checkout_data', return_value=DATA), patch('app.inspect_delivery', return_value=[row]):
                self.assertEqual(self.order().status_code, 422)
        self.connection.commit.assert_not_called()

    def test_duplicate_token_returns_existing_order_without_api(self):
        self.cursor.fetchone.return_value = (7,)
        with patch('app.checkout_data', return_value=DATA), patch('app.inspect_delivery') as check:
            response = self.order()
            self.assertTrue(response.location.endswith('/orders/7'))
            check.assert_not_called()
        self.connection.commit.assert_not_called()

    def test_bad_token_rejected(self):
        response = self.client.post('/order', data={'order_token': 'other'})
        self.assertEqual(response.status_code, 409)
        self.connection.cursor.assert_not_called()

    def test_precheck_reports_all_without_saving(self):
        with patch('app.checkout_data', return_value=DATA), patch('app.inspect_delivery', return_value=[ROUTE, dict(name='B',status='unknown',message='timeout')]):
            response = self.client.post('/cart/delivery-check')
        self.assertEqual(response.json['status'], 'unknown')
        self.assertEqual(len(response.json['restaurants']), 2)
        self.assertNotIn('path', response.json['restaurants'][0])
        self.connection.commit.assert_not_called()
        self.connection.rollback.assert_called_once()

    def test_legacy_order_preserved_without_fake_progress_or_api(self):
        self.cursor.fetchone.return_value = (7, datetime(2026,1,1), 'address', None, 100, 'active', None)
        with patch('app.inspect_delivery') as check:
            response = self.client.get('/delivery/7')
            check.assert_not_called()
        self.assertIn('복원할 수 없습니다', response.get_data(as_text=True))

    def test_delivery_ownership_and_not_found(self):
        self.cursor.fetchone.return_value = None
        response = self.client.get('/delivery/99')
        self.assertEqual(response.status_code, 302)
        sql, params = self.cursor.execute.call_args.args
        self.assertIn('user_id=%s', sql)
        self.assertEqual(params, (99, 1))

    def test_anonymous_cannot_check_or_view(self):
        with self.client.session_transaction() as session:
            session.clear()
        self.assertEqual(self.client.post('/cart/delivery-check').status_code, 401)
        self.assertEqual(self.client.get('/delivery/7').status_code, 302)
        self.connection.cursor.assert_not_called()

    def test_order_detail_and_statistics_still_render(self):
        self.cursor.fetchone.return_value = (7, datetime(2026,1,1), 100, 20, 'address', 'active', None, None, 100)
        self.cursor.fetchall.return_value = [('menu',1,100,20,'A')]
        self.assertEqual(self.client.get('/orders/7').status_code, 200)
        self.cursor.fetchone.side_effect = [(datetime(2026,1,1),), (1,100,20)]
        self.cursor.fetchall.return_value = []
        self.assertEqual(self.client.get('/saving').status_code, 200)


if __name__ == '__main__':
    unittest.main()
