import json
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Event
from unittest.mock import patch

from branches import (SearchCache, address_context, branch_digest, brand_matches,
                      category_matches, search_places, split_cart_key, validate_grant)
from delivery import DeliveryError
from settings import DELIVERY_LIMIT_METERS, distance_policy


MAPPINGS = [
    (1, '옷데리아', '롯데리아'), (2, '맥도널즈', '맥도날드'),
    (3, '맘스타치', '맘스터치'), (4, 'BHB치킨', 'bhc치킨'),
    (5, '교춘치킨', '교촌치킨'), (6, 'BQQ치킨', 'BBQ치킨'),
    (7, '도미누피자', '도미노피자'), (8, '피자헛뜨', '피자헛'),
    (9, '미스타피자', '미스터피자'),
]


def place(place_id='101', name='롯데리아 테스트점', x='126.701', y='37.45', **changes):
    result = dict(id=place_id, place_name=name, x=x, y=y,
                  road_address_name='테스트 도로명 주소', address_name='테스트 지번 주소',
                  category_group_code='FD6', category_name='음식점 > 패스트푸드 > 롯데리아')
    result.update(changes)
    return result


class BranchSearchTests(unittest.TestCase):
    def setUp(self):
        self.cache = patch('branches.search_cache', SearchCache())
        self.coords = patch('branches.coordinate_cache', SearchCache())
        self.cache.start()
        self.coords.start()
        self.addCleanup(self.cache.stop)
        self.addCleanup(self.coords.stop)

    def search(self, documents, page=1):
        with patch('branches.address_to_coords', return_value=(126.7, 37.45)), \
             patch('branches.api_get', return_value={'documents': documents, 'meta': {'is_end': True}}) as get:
            result = search_places('인천 주소', '롯데리아', ['롯데리아'], page)
            return result, get

    def test_sql_contains_all_nine_user_approved_mappings(self):
        sql = (Path(__file__).resolve().parents[1] / 'DB/week10_branches.sql').read_text(encoding='utf-8')
        for identity, virtual, brand in MAPPINGS:
            self.assertIn(f"id={identity} AND name='{virtual}'", sql)
            self.assertIn(f"({identity},'{brand}',JSON_ARRAY(", sql)
        self.assertIn('SIGNAL SQLSTATE', sql)
        self.assertIn('order_restaurant_id INT NULL', sql)
        self.assertNotIn('UPDATE restaurants', sql)
        self.assertNotIn('UPDATE menus', sql)

    def test_member_coordinates_and_shared_10km_policy(self):
        result, get = self.search([place()])
        params = get.call_args.args[1]
        self.assertEqual(params['x'], 126.7)
        self.assertEqual(params['y'], 37.45)
        self.assertEqual(params['radius'], DELIVERY_LIMIT_METERS)
        self.assertEqual(params['query'], '롯데리아')
        self.assertEqual(params['sort'], 'distance')
        self.assertEqual(len(result['places']), 1)
        self.assertEqual(distance_policy()['limit_meters_label'], '10,000m')

    def test_multiple_branches_deduplicated_by_place_id(self):
        result, _ = self.search([place(), place(), place('102', '롯데리아 다른점')])
        self.assertEqual([p['place_id'] for p in result['places']], ['101', '102'])

    def test_invalid_brand_id_coordinates_category_and_radius_are_filtered(self):
        bad = [place(name='다른 브랜드'), place(place_id='bad-id'), place(x='nan'),
               place(x='999'), place(x=True), place(x='127.5'), place(category_group_code='CE7'),
               place(category_name='음식점 > 일반음식점'), place(road_address_name='', address_name='')]
        result, _ = self.search(bad)
        self.assertEqual(result['places'], [])

    def test_exact_search_radius_boundary(self):
        with patch('branches.meters_between', return_value=10000):
            self.assertEqual(len(self.search([place()])[0]['places']), 1)
        # Independent key prevents a previous cache entry from hiding the boundary.
        with patch('branches.meters_between', return_value=10001):
            self.assertEqual(self.search([place()], page=2)[0]['places'], [])

    def test_empty_result_is_not_replaced_by_another_region(self):
        result, get = self.search([])
        self.assertEqual(result['places'], [])
        get.assert_called_once()
        self.assertEqual(get.call_args.args[1]['radius'], 10000)

    def test_api_failure_is_not_cached_or_replaced(self):
        with patch('branches.address_to_coords', return_value=(126.7, 37.45)), \
             patch('branches.api_get', side_effect=DeliveryError('검색 실패')) as get:
            for _ in range(2):
                with self.assertRaises(DeliveryError):
                    search_places('인천 주소', '롯데리아', ['롯데리아'])
            self.assertEqual(get.call_count, 2)

    def test_malformed_search_response_is_error(self):
        with patch('branches.address_to_coords', return_value=(126.7, 37.45)), \
             patch('branches.api_get', return_value={'documents': {}, 'meta': {'is_end': True}}):
            with self.assertRaises(DeliveryError):
                search_places('인천 주소', '롯데리아', ['롯데리아'])

    def test_brand_normalization_and_category_guard(self):
        self.assertTrue(brand_matches('BHC 치킨 테스트점', ['bhc치킨']))
        self.assertFalse(brand_matches('테스트 롯데리아 앞 식당', ['롯데리아']))
        self.assertFalse(category_matches('음식점 > 양식 > 바베큐', ['BBQ', 'BBQ치킨']))

    def test_cart_keys_keep_same_menu_at_different_branches_separate(self):
        self.assertEqual(split_cart_key('1'), ('1', None))
        self.assertEqual(split_cart_key('1:10'), ('1', 10))
        self.assertNotEqual(split_cart_key('1:10'), split_cart_key('1:11'))
        for value in ('-1:2', '1:0', '1:2:3', '1:x'):
            with self.assertRaises(DeliveryError):
                split_cart_key(value)

    def test_grant_binds_member_address_and_branch_snapshot(self):
        branch = dict(branch_id=1, place_id='101', place_name='롯데리아 점', road_address='주소',
                      lot_address='', lng=126.7, lat=37.45, restaurant_id=1, brand_name='롯데리아')
        grant = dict(a=address_context(1, '인천'), d=branch_digest(branch))
        self.assertEqual(validate_grant(branch, grant, 1, '인천'), branch)
        for candidate, user_id, address in ((branch, 2, '인천'), (branch, 1, '전주'),
                                             (dict(branch, lng=127.5), 1, '인천')):
            with self.assertRaises(DeliveryError):
                validate_grant(candidate, grant, user_id, address)

    def test_cache_ttl_capacity_and_copies(self):
        cache = SearchCache(ttl=10, capacity=1)
        with patch('branches.time.monotonic', return_value=0):
            self.assertEqual(cache.get('a', lambda: [1]), [1])
            cache.get('a', lambda: [99]).append(2)
            self.assertEqual(cache.get('a', lambda: [99]), [1])
            cache.get('b', lambda: [2])
            self.assertNotIn('a', cache.values)
        with patch('branches.time.monotonic', return_value=11):
            self.assertEqual(cache.get('b', lambda: [3]), [3])

    def test_concurrent_identical_search_shares_one_fetch(self):
        cache = SearchCache()
        entered, release = Event(), Event()
        calls = []
        def fetch():
            calls.append(1)
            entered.set()
            release.wait(2)
            return [1]
        with ThreadPoolExecutor(max_workers=2) as pool:
            first = pool.submit(cache.get, 'same', fetch)
            self.assertTrue(entered.wait(2))
            second = pool.submit(cache.get, 'same', fetch)
            release.set()
            self.assertEqual(first.result(), [1])
            self.assertEqual(second.result(), [1])
        self.assertEqual(len(calls), 1)


if __name__ == '__main__':
    unittest.main()
