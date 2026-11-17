"""Additional feature regressions. All mutations use isolated fixtures only."""
import json
import unittest
from unittest.mock import Mock, patch
from flask import template_rendered
import app as application
import test_branch_flow as fixtures
from delivery import delivery_progress
from saving_stats import menu_calorie_chart


class Week12FeatureTests(unittest.TestCase):
    def setUp(self):
        self.flow = fixtures.BranchFlowTests()
        self.flow.setUp()
        self.addCleanup(self.flow.doCleanups)
        self.client, self.db = self.flow.client, self.flow.db

    def order(self, price=20000):
        self.db.execute('UPDATE menus SET price=? WHERE id=1', (price,))
        self.db.commit()
        self.flow.add(self.flow.search()[0])
        fingerprint = self.client.post('/cart/delivery-check').json['fingerprint']
        self.assertEqual(self.flow.submit(fingerprint).location, '/order/complete')
        return self.db.execute('SELECT MAX(id) FROM orders').fetchone()[0]

    def finish(self, identity):
        self.db.execute("UPDATE orders SET order_date=datetime('now','-100 seconds') WHERE id=?",(identity,))
        self.db.commit()

    def test_new_timing_boundary_and_legacy_snapshot_unchanged(self):
        identity = self.order()
        raw = self.db.execute('SELECT delivery_snapshot FROM orders WHERE id=?',(identity,)).fetchone()[0]
        snapshot = json.loads(raw)
        self.assertEqual(snapshot['preparation']+snapshot['duration'],600)
        self.assertEqual(snapshot['scale'],10)
        self.assertFalse(delivery_progress(raw,59.999)[2])
        self.assertTrue(delivery_progress(raw,60)[2])
        legacy = json.dumps(dict(snapshot,version=2,preparation=600,duration=120,scale=10))
        self.assertFalse(delivery_progress(legacy,60)[2])
        self.assertTrue(delivery_progress(legacy,72)[2])
        self.assertEqual(self.db.execute('SELECT delivery_snapshot FROM orders WHERE id=?',(identity,)).fetchone()[0],raw)

    def test_delivery_links_follow_server_state_and_direct_access_keeps_ownership(self):
        identity = self.order()
        for path in ('/orders',f'/orders/{identity}'):
            self.assertIn(f'href="/delivery/{identity}"',self.client.get(path).get_data(as_text=True))
        self.finish(identity)
        for path in ('/orders',f'/orders/{identity}'):
            html=self.client.get(path).get_data(as_text=True)
            self.assertNotIn(f'href="/delivery/{identity}"',html)
            self.assertIn('재주문',html)
        self.assertIn('가상 배달 완료',self.client.get(f'/delivery/{identity}').get_data(as_text=True))
        with self.client.session_transaction() as session: session['user_id']=2
        self.assertEqual(self.client.get(f'/delivery/{identity}').location,'/orders')
        with self.client.session_transaction() as session: session['user_id']=1
        cancelled=self.order()
        self.client.post(f'/orders/{cancelled}/cancel',data=self.flow.reorder_form())
        for path in ('/orders',f'/orders/{cancelled}'):
            self.assertNotIn(f'href="/delivery/{cancelled}"',self.client.get(path).get_data(as_text=True))
        self.assertIn('취소된 주문입니다',self.client.get(f'/delivery/{cancelled}').get_data(as_text=True))

    def test_ten_percent_floor_once_and_preserve_existing_ledger(self):
        old=self.order(20000)
        self.finish(old)
        self.db.execute('INSERT INTO wallets(user_id,balance) VALUES(1,20000)')
        wallet_id=self.db.execute('SELECT id FROM wallets WHERE user_id=1').fetchone()[0]
        self.db.execute("INSERT INTO wallet_transactions(wallet_id,order_id,type,amount) VALUES(?,?,'earn',20000)",(wallet_id,old))
        self.db.commit()
        history=self.db.execute('SELECT * FROM wallet_transactions').fetchall()
        for price in (20000,20009,9):
            identity=self.order(price)
            self.finish(identity)
            for _ in range(2):
                self.client.get('/wallet')
                self.client.get(f'/delivery/{identity}')
            amount=self.db.execute("SELECT amount FROM wallet_transactions WHERE order_id=?",(identity,)).fetchall()
            self.assertEqual(amount,[(price//10,)])
        self.assertEqual(self.db.execute('SELECT * FROM wallet_transactions WHERE order_id=?',(old,)).fetchall(),history)
        self.assertEqual(self.db.execute('SELECT balance FROM wallets WHERE user_id=1').fetchone()[0],24000)
        with self.client.session_transaction() as session: session['user_id']=2
        self.assertIn('0 포인트',self.client.get('/wallet').get_data(as_text=True))

    def test_menu_calories_use_historical_values_and_identity(self):
        self.db.execute("UPDATE menus SET name='같은 이름',calories=99999 WHERE id IN (1,2)")
        for owner,status,menu,calories,quantity in ((1,'active',1,30,2),(1,'active',1,40,3),(1,'active',2,90,1),(1,'cancelled',1,900,5),(2,'active',1,800,5)):
            order_id=self.db.execute('INSERT INTO orders(user_id,total_price,total_calories,status) VALUES(?,100,?,?)',(owner,calories*quantity,status)).lastrowid
            self.db.execute('INSERT INTO order_items(order_id,menu_id,quantity,price,calories) VALUES(?,?,?,100,?)',(order_id,menu,quantity,calories))
        self.db.commit()
        rendered=Mock()
        with template_rendered.connected_to(rendered,application.app):
            html=self.client.get('/saving').get_data(as_text=True)
        chart=rendered.call_args.kwargs['context']['calorie_periods']['daily']
        self.assertEqual(chart['total'],270)
        self.assertEqual([(i['menu_id'],i['calories'],i['percent']) for i in chart['items']],[(1,180,'66.7'),(2,90,'33.3')])
        self.assertIn('conic-gradient',html)
        self.assertEqual(html.count('<strong>같은 이름</strong>'),6)

    def test_empty_calories_and_many_menu_legend(self):
        html=self.client.get('/saving').get_data(as_text=True)
        self.assertIn('아직 표시할 메뉴별 칼로리 기록이 없습니다.',html)
        self.assertNotIn('class="calorie-donut"',html)
        chart=menu_calorie_chart([(i,'동일 이름','음식점',i) for i in range(1,51)])
        self.assertEqual(len(chart['items']),50)
        self.assertEqual(chart['items'][-1]['end'],'100.000000')

    def test_header_address_link_and_no_technical_delivery_copy(self):
        home=self.client.get('/').get_data(as_text=True)
        self.assertIn('<a href="/address">주소 설정</a>',home)
        self.assertEqual(home.count('href="/address"'),1)
        identity=self.order()
        html=self.client.get(f'/delivery/{identity}').get_data(as_text=True)
        for text in ('API 예상','가상 시간','GPS 추적','라이더 대표 경로'):
            self.assertNotIn(text,html)
        self.assertIn('실제 주문·결제가 없는 가상 서비스',html)


if __name__=='__main__':
    unittest.main()
