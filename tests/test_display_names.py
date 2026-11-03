from copy import deepcopy
import json
import unittest
from unittest.mock import Mock

from display_names import (DISPLAY_ALIASES, load_display_catalog, public_branch,
                           public_snapshot, virtual_place_name)
from test_branches import MAPPINGS


def catalog():
    return [dict(restaurant_id=identity, virtual_name=virtual,
                 aliases=[brand, *DISPLAY_ALIASES.get(brand, ())])
            for identity, virtual, brand in MAPPINGS]


class DisplayNameTests(unittest.TestCase):
    def test_all_nine_brands_preserve_branch_suffix(self):
        for identity, virtual, brand in MAPPINGS:
            with self.subTest(brand=brand):
                self.assertEqual(virtual_place_name(brand+' 인천시티오씨엘점', virtual,
                                                   [brand], catalog()), virtual+' 인천시티오씨엘점')

    def test_examples_and_spacing_case_punctuation_variants(self):
        cases = [
            ('롯데리아 인천시티오씨엘점','옷데리아','옷데리아 인천시티오씨엘점'),
            ('맥도날드 인천점','맥도널즈','맥도널즈 인천점'),
            ('교촌치킨 용현점','교춘치킨','교춘치킨 용현점'),
            ('bhc치킨 주안점','BHB치킨','BHB치킨 주안점'),
            ('BHC 치킨 주안점','BHB치킨','BHB치킨 주안점'),
            ('ｂｈｃ치킨 주안점','BHB치킨','BHB치킨 주안점'),
            ('롯\u200b데 리-아 인천점','옷데리아','옷데리아 인천점'),
            ("McDonald’s 인천점",'맥도널즈','맥도널즈 인천점'),
            ('교촌 용현점','교춘치킨','교춘치킨 용현점'),
            ('비비큐 주안점','BQQ치킨','BQQ치킨 주안점'),
        ]
        for raw, virtual, expected in cases:
            with self.subTest(raw=raw):
                self.assertEqual(virtual_place_name(raw,virtual,catalog=catalog()),expected)

    def test_missing_unknown_and_unrecognized_names_never_forwarded(self):
        for raw in (None, '', '알 수 없는 실제 상호 인천점', 'UnknownChain 인천점'):
            self.assertEqual(virtual_place_name(raw,'옷데리아',catalog=catalog(),place_id='123'),
                             '옷데리아 지점 (지점 123)')
        self.assertEqual(virtual_place_name('인천점','옷데리아',place_id='<unsafe>'),'옷데리아 지점')

    def test_already_virtual_names_are_idempotent(self):
        for _, virtual, _ in MAPPINGS:
            value = virtual+' 인천점'
            self.assertEqual(virtual_place_name(value,virtual,catalog=catalog()),value)

    def test_compound_place_names_do_not_leak_other_chain(self):
        result = virtual_place_name('롯데리아 / KYOCHON 인천점','옷데리아',catalog=catalog())
        self.assertEqual(result,'옷데리아 / 교춘치킨 인천점')

    def test_public_branch_preserves_location_and_does_not_mutate_source(self):
        original = dict(restaurant_id=1,virtual_name='옷데리아',brand_name='롯데리아',
                        place_name='롯데리아 인천점',place_id='123',branch_id=1,
                        address='롯데리아 건물 1층',road_address='롯데리아 건물 1층',
                        lot_address='인천 지번',lng=126.7,lat=37.45)
        before = deepcopy(original)
        public = public_branch(original,catalog())
        self.assertEqual(original,before)
        self.assertEqual(public['display_name'],'옷데리아 인천점')
        self.assertNotIn('brand_name',public)
        self.assertNotIn('place_name',public)
        for key in ('place_id','branch_id','address','road_address','lot_address','lng','lat'):
            self.assertEqual(public[key],original[key])

    def test_v2_snapshot_routes_representative_and_json_are_presentation_only(self):
        branch = dict(restaurant_id=1,virtual_name='옷데리아',brand_name='롯데리아',
                      place_name='롯데리아 인천점',place_id='123',lng=126.7,lat=37.45)
        snapshot = dict(version=2,representative='옷데리아 · 롯데리아 인천점',
                        duration=120,scale=10,preparation=600,
                        path=[{'lng':126.7,'lat':37.45},{'lng':126.71,'lat':37.46}],
                        routes=[dict(name='옷데리아 · 롯데리아 인천점',branch=branch,distance=10000,duration=120)])
        before = json.dumps(snapshot,ensure_ascii=False)
        public = public_snapshot(snapshot,catalog())
        self.assertNotIn('롯데리아',json.dumps(public,ensure_ascii=False))
        self.assertEqual(public['representative'],'옷데리아 인천점')
        self.assertEqual(json.dumps(snapshot,ensure_ascii=False),before)
        for key in ('path','duration','scale','preparation'):
            self.assertEqual(public[key],snapshot[key])

    def test_v1_legacy_snapshots_are_rendered_safely(self):
        for raw, expected in (('옷데리아','옷데리아'),('롯데리아 인천점','옷데리아 인천점'),
                              ('옷데리아 · 롯데리아 인천점','옷데리아 인천점'),
                              ('UnrecognizedChain 점','가상 음식점')):
            snapshot = dict(representative=raw,routes=[dict(name=raw,distance=4500,duration=120)])
            self.assertEqual(public_snapshot(snapshot,catalog())['representative'],expected)
            self.assertEqual(snapshot['representative'],raw)

    def test_disabled_mapping_catalog_keeps_aliases_for_old_orders(self):
        cursor = Mock()
        cursor.fetchall.return_value = [(1,'옷데리아','롯데리아','["롯데리아"]')]
        result = load_display_catalog(cursor)
        self.assertNotIn('enabled=1',cursor.execute.call_args.args[0])
        self.assertIn('LOTTERIA',result[0]['aliases'])


if __name__ == '__main__':
    unittest.main()
