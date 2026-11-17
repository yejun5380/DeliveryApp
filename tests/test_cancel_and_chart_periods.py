"""Cancellation boundaries and chart windows, using isolated DB and virtual time."""
from datetime import datetime, timedelta
import json
import unittest
from unittest.mock import Mock, patch
from flask import template_rendered
import app as application
import test_branch_flow as fixtures
from delivery import DELIVERY_ELAPSED_SQL, cancellation_remaining
from saving_stats import period_starts


class CancelAndChartTests(unittest.TestCase):
    def setUp(self):
        self.flow=fixtures.BranchFlowTests()
        self.flow.setUp()
        self.addCleanup(self.flow.doCleanups)
        self.client,self.db=self.flow.client,self.flow.db

    def order(self,preparation=480,scale=10):
        snapshot=json.dumps(dict(preparation=preparation,duration=120,scale=scale,
                                 path=[dict(lat=37,lng=127),dict(lat=37.01,lng=127.01)]))
        identity=self.db.execute('INSERT INTO orders(user_id,total_price,total_calories,delivery_snapshot) VALUES(1,20000,500,?)',(snapshot,)).lastrowid
        self.db.commit()
        return identity,snapshot

    def clock(self,elapsed,write_elapsed=None):
        execute=fixtures.Cursor.execute
        def fixed(cursor,sql,args=()):
            value=write_elapsed if write_elapsed is not None and sql.startswith('UPDATE orders SET status=') else elapsed
            return execute(cursor,sql.replace(DELIVERY_ELAPSED_SQL,str(value)),args)
        return patch.object(fixtures.Cursor,'execute',fixed)

    def token(self):
        self.client.get('/orders')
        with self.client.session_transaction() as session:return session['cancel_token']

    def test_exact_reception_boundaries_on_server_and_forms(self):
        for preparation,scale,deadline in ((480,10,16),(600,10,20),(900,5,60)):
            for offset in (-.000001,0,.000001):
                with self.subTest(preparation=preparation,scale=scale,offset=offset):
                    identity,snapshot=self.order(preparation,scale)
                    elapsed=deadline+offset
                    self.assertEqual(cancellation_remaining(snapshot,elapsed)>0,offset<0)
                    with self.clock(elapsed):
                        for path in ('/orders',f'/orders/{identity}'):
                            html=self.client.get(path).get_data(as_text=True)
                            self.assertEqual(f'action="/orders/{identity}/cancel"' in html,offset<0)
                        response=self.client.post(f'/orders/{identity}/cancel',data={'cancel_token':self.token()},follow_redirects=True)
                    status=self.db.execute('SELECT status FROM orders WHERE id=?',(identity,)).fetchone()[0]
                    self.assertEqual(status,'cancelled' if offset<0 else 'active')
                    self.assertIn('주문이 취소되었습니다.' if offset<0 else '주문 접수 단계가 끝나 취소할 수 없습니다.',response.get_data(as_text=True))
        self.assertEqual(self.db.execute('SELECT COUNT(*) FROM wallet_transactions').fetchone()[0],0)

    def test_expiry_during_ledger_lock_is_rechecked_at_update(self):
        identity,_=self.order()
        token=self.token()
        with self.clock(15.999,write_elapsed=16):
            response=self.client.post(f'/orders/{identity}/cancel',data={'cancel_token':token},follow_redirects=True)
        self.assertIn('주문 접수 단계가 끝나 취소할 수 없습니다.',response.get_data(as_text=True))
        self.assertEqual(self.db.execute('SELECT status FROM orders WHERE id=?',(identity,)).fetchone()[0],'active')

    def chart_context(self,as_of):
        execute=fixtures.Cursor.execute
        def fixed(cursor,sql,args=()):
            if sql=='SELECT CURRENT_TIMESTAMP AS as_of':return execute(cursor,'SELECT %s AS as_of',(as_of.isoformat(' '),))
            return execute(cursor,sql,args)
        rendered=Mock()
        with patch.object(fixtures.Cursor,'execute',fixed),template_rendered.connected_to(rendered,application.app):
            response=self.client.get('/saving')
        self.assertEqual(response.status_code,200)
        return rendered.call_args.kwargs['context'],response.get_data(as_text=True)

    def item(self,day,menu,calories,quantity=1,owner=1,status='active'):
        value=day.isoformat(' ') if isinstance(day,datetime) else day.isoformat()+' 00:00:00'
        identity=self.db.execute('INSERT INTO orders(user_id,order_date,total_price,total_calories,status) VALUES(?,?,100,?,?)',(owner,value,calories*quantity,status)).lastrowid
        self.db.execute('INSERT INTO order_items(order_id,menu_id,quantity,price,calories) VALUES(?,?,?,100,?)',(identity,menu,quantity,calories))

    def test_calorie_windows_boundaries_identity_and_exclusions(self):
        now=datetime(2026,1,5,12)
        starts=period_starts(now.date())
        self.db.execute("UPDATE menus SET name='동일 메뉴',calories=99999 WHERE id IN(1,2)")
        self.item(starts['daily'][0],1,10,2)
        self.item(now,1,30,2)
        self.item(starts['daily'][0]-timedelta(days=1),1,5,2)
        self.item(starts['weekly'][0],2,40,2)
        self.item(starts['weekly'][0]-timedelta(days=1),2,50,2)
        self.item(starts['monthly'][0],1,60)
        self.item(starts['monthly'][0]-timedelta(days=1),1,999)
        self.item(now+timedelta(seconds=1),1,999)
        self.item(now,1,999,status='cancelled')
        self.item(now,1,999,owner=2)
        self.db.commit()
        context,html=self.chart_context(now)
        periods=context['calorie_periods']
        self.assertEqual([periods[key]['total'] for key in ('daily','weekly','monthly')],[80,170,330])
        self.assertEqual([(i['menu_id'],i['calories']) for i in periods['monthly']['items']],[(2,180),(1,150)])
        self.assertIn('data-chart-tooltip="2026-01-05',html)
        self.assertIn('aria-controls="calorie-monthly"',html)

    def test_empty_periods_do_not_draw_empty_donuts(self):
        now=datetime(2026,1,5,12)
        self.item(period_starts(now.date())['monthly'][0],1,100)
        self.db.commit()
        context,html=self.chart_context(now)
        self.assertEqual(context['calorie_periods']['daily']['total'],0)
        self.assertEqual(context['calorie_periods']['weekly']['total'],0)
        self.assertEqual(context['calorie_periods']['monthly']['total'],100)
        self.assertNotIn('data-calorie-source="calorie-data-daily"',html)
        self.assertIn('data-calorie-source="calorie-data-monthly"',html)


if __name__=='__main__':unittest.main()
