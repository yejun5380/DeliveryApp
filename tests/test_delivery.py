import os
import unittest
from unittest.mock import Mock, patch
import requests
from delivery import DeliveryError, inspect_delivery, time_scale


def response(distance=10000, duration=120, vertices=None):
    return {'routes': [{'result_code': 0, 'summary': {'distance': distance, 'duration': duration},
                        'sections': [{'roads': [{'vertexes': vertices if vertices is not None else [127, 37, 127.01, 37.01]}]}]}]}


class DeliveryTests(unittest.TestCase):
    def call(self, data, restaurants=None):
        def fake_get(url, **kwargs):
            obj = Mock()
            obj.json.return_value = {'documents': [{'x': '127', 'y': '37'}]} if 'local/search' in url else data
            return obj
        with patch.dict(os.environ, KAKAO_REST_API_KEY='test'), patch('delivery.requests.get', side_effect=fake_get) as get:
            result = inspect_delivery('destination', restaurants or [('A', 'origin')])
            return result, get.call_count

    def test_distance_boundary(self):
        self.assertEqual(self.call(response())[0][0]['status'], 'available')
        self.assertEqual(self.call(response(10001))[0][0]['status'], 'unavailable')

    def test_invalid_duration_is_unknown(self):
        for duration in (None, 0, -1, '120', True, float('nan')):
            with self.subTest(duration=duration):
                self.assertEqual(self.call(response(duration=duration))[0][0]['status'], 'unknown')

    def test_malformed_path(self):
        for vertices in ([], [127, 37], [127, 37, 128], [127, 37, 999, 37]):
            self.assertEqual(self.call(response(vertices=vertices))[0][0]['status'], 'unknown')

    def test_shared_address_deduplicates(self):
        results, calls = self.call(response(), [('A', 'origin'), ('B', 'origin')])
        self.assertEqual(len(results), 2)
        self.assertEqual(calls, 3)  # destination, origin, directions

    def test_timeout(self):
        with patch.dict(os.environ, KAKAO_REST_API_KEY='test'), patch('delivery.requests.get', side_effect=requests.Timeout('secret')):
            with self.assertRaises(DeliveryError) as error:
                inspect_delivery('destination', [('A', 'origin')])
            self.assertNotIn('secret', str(error.exception))

    def test_all_restaurants_checked(self):
        rows, calls = self.call(response(), [('A', 'one'), ('B', 'two')])
        self.assertEqual(len(rows), 2)
        self.assertEqual(calls, 5)

    def test_scale_configuration(self):
        for value in ('0', '-1', 'nan', 'inf', 'bad'):
            with patch.dict(os.environ, DELIVERY_TIME_SCALE=value):
                with self.assertRaises(DeliveryError):
                    time_scale()


if __name__ == '__main__':
    unittest.main()
