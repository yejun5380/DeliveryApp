"""Home category and menu search regression checks using an isolated database."""
import sqlite3
import unittest
from unittest.mock import patch

import app as application
from test_branch_flow import Connection


class HomeTests(unittest.TestCase):
    def setUp(self):
        self.db = sqlite3.connect(':memory:')
        self.addCleanup(self.db.close)
        self.db.executescript('''
            CREATE TABLE restaurants(id INTEGER PRIMARY KEY, name TEXT, category TEXT, description TEXT);
            CREATE TABLE menus(id INTEGER PRIMARY KEY, restaurant_id INTEGER, name TEXT);
            INSERT INTO restaurants VALUES
                (1,'Chicken House','치킨','crispy'),
                (2,'Pizza House','피자','cheesy'),
                (3,'Burger House','햄버거','burger');
            INSERT INTO menus VALUES (1,1,'special'),(2,1,'special combo'),(3,2,'special'),(4,3,'special burger');
        ''')
        self.connector = patch.object(application, 'get_db_connection', return_value=Connection(self.db)).start()
        self.addCleanup(patch.stopall)
        self.client = application.app.test_client()

    def page(self, **query):
        response = self.client.get('/', query_string=query)
        self.assertEqual(response.status_code, 200)
        return response.get_data(as_text=True)

    def test_landing_categories_without_restaurant_listing_or_db_call(self):
        html = self.page()
        self.connector.assert_not_called()
        for category in ('치킨', '피자', '햄버거'):
            self.assertIn(f'<strong>{category}</strong>', html)
        self.assertNotIn('Chicken House', html)
        self.assertNotIn('restaurants-title', html)

    def test_category_and_menu_search_are_intersected_without_duplicates(self):
        html = self.page(category='치킨', search='special')
        self.assertEqual(html.count('<h3>Chicken House</h3>'), 1)
        self.assertNotIn('Pizza House', html)
        self.assertIn('name="category" value="치킨"', html)
        self.assertIn('/restaurant/1', html)
        self.assertIn('aria-current="true"', html)

    def test_search_preserves_other_existing_categories(self):
        self.assertIn('Burger House', self.page(search='Burger'))
        self.assertIn('Pizza House', self.page(search='special'))

    def test_all_categories_and_burger_menu_search(self):
        for category, name in (('치킨', 'Chicken House'), ('피자', 'Pizza House'), ('햄버거', 'Burger House')):
            with self.subTest(category=category):
                html = self.page(category=category)
                self.assertIn(f'<h3>{name}</h3>', html)
                self.assertEqual(html.count('app-card restaurant-card'), 1)
        html = self.page(category='햄버거', search='special')
        self.assertIn('<h3>Burger House</h3>', html)
        self.assertNotIn('Pizza House', html)
        self.assertIn('🍔', html)
        self.assertIn('name="category" value="햄버거"', html)

    def test_empty_category_and_no_search_results(self):
        self.db.execute("DELETE FROM restaurants WHERE category='햄버거'")
        self.assertIn('아직 등록된 음식점이 없습니다', self.page(category='햄버거'))
        self.assertIn('검색 조건에 맞는 음식점이 없습니다', self.page(category='치킨', search='missing'))

    def test_invalid_category_rejected_before_query(self):
        self.assertEqual(self.client.get('/', query_string={'category': "치킨' OR 1=1"}).status_code, 400)
        self.connector.assert_not_called()

    def test_search_text_is_escaped_and_parameterized(self):
        html = self.page(search='<script>alert(1)</script>')
        self.assertNotIn('<script>alert(1)</script>', html)
        self.assertIn('&lt;script&gt;', html)
        self.assertNotIn('Chicken House', html)


if __name__ == '__main__':
    unittest.main()
