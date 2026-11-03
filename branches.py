"""Server-side place search and selection validation. Never accepts client coordinates."""

from collections import OrderedDict
from concurrent.futures import Future
from copy import deepcopy
import hashlib
import json
import math
import re
from threading import Lock
import time
import unicodedata

from delivery import DeliveryError, address_to_coords, api_get
from settings import DELIVERY_LIMIT_METERS


class SearchCache:
    """Bounded process-local TTL cache; identical concurrent requests share one lookup."""

    def __init__(self, ttl=300, capacity=128):
        self.ttl, self.capacity = ttl, capacity
        self.values, self.pending = OrderedDict(), {}
        self.lock = Lock()

    def get(self, key, fetch):
        with self.lock:
            now = time.monotonic()
            for old in list(self.values):
                if self.values[old][0] <= now:
                    del self.values[old]
            if key in self.values:
                self.values.move_to_end(key)
                return deepcopy(self.values[key][1])
            owner = key not in self.pending
            if owner:
                if len(self.pending) >= 16:
                    raise DeliveryError("검색 요청이 많습니다. 잠시 후 다시 시도해 주세요.")
                self.pending[key] = Future()
            future = self.pending[key]
        if not owner:
            return deepcopy(future.result())
        try:
            value = fetch()
            with self.lock:
                self.values[key] = (time.monotonic() + self.ttl, deepcopy(value))
                while len(self.values) > self.capacity:
                    self.values.popitem(last=False)
            future.set_result(value)
            return deepcopy(value)
        except Exception as error:
            future.set_exception(error)
            raise
        finally:
            with self.lock:
                self.pending.pop(key, None)


search_cache = SearchCache()
coordinate_cache = SearchCache(capacity=128)


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False, default=str).encode()).hexdigest()[:32]


def address_context(user_id, address):
    return digest([user_id, address.strip()])


def normalized(value):
    return re.sub(r"[\W_]", "", unicodedata.normalize("NFKC", value).casefold())


def brand_matches(name, aliases):
    name = normalized(name)
    # Category validation below also guards against keyword matches for unrelated places.
    return any(name.startswith(normalized(alias)) for alias in aliases if normalized(alias))


def category_matches(category, aliases):
    """Require a chain category as well as a matching name; fail closed on ambiguity."""
    if not isinstance(category, str):
        return False
    parts = {normalized(part) for part in category.split(">")}
    return any(normalized(alias) in parts for alias in aliases)


def meters_between(a, b):
    x1, y1, x2, y2 = map(math.radians, (*a, *b))
    value = math.sin((y2-y1)/2)**2 + math.cos(y1)*math.cos(y2)*math.sin((x2-x1)/2)**2
    return 6371000 * 2 * math.asin(math.sqrt(min(1, value)))


def mapping_for(cursor, restaurant_id):
    cursor.execute("SELECT brand_name, aliases FROM restaurant_brand_mappings WHERE restaurant_id=%s AND enabled=1", (restaurant_id,))
    row = cursor.fetchone()
    if not row:
        raise DeliveryError("브랜드 연결이 없거나 비활성화되어 있습니다.")
    try:
        aliases = json.loads(row[1])
        if not isinstance(aliases, list) or not all(isinstance(a, str) and a.strip() for a in aliases):
            raise ValueError()
    except (ValueError, TypeError):
        raise DeliveryError("브랜드 연결 설정이 올바르지 않습니다.") from None
    return row[0], list(dict.fromkeys([row[0], *aliases]))


def search_places(address, brand, aliases, page=1):
    center = coordinate_cache.get(address, lambda: address_to_coords(address))

    def fetch():
        data = api_get("https://dapi.kakao.com/v2/local/search/keyword.json", {
            "query": brand, "x": center[0], "y": center[1],
            "radius": DELIVERY_LIMIT_METERS, "sort": "distance",
            "category_group_code": "FD6", "page": page, "size": 15,
        })
        try:
            documents, is_end = data["documents"], data["meta"]["is_end"]
            if not isinstance(documents, list) or type(is_end) is not bool:
                raise ValueError()
            results, seen = [], set()
            for doc in documents:
                try:
                    place_id, name = doc["id"], doc["place_name"]
                    if not isinstance(place_id, str) or not re.fullmatch(r"[0-9]{1,64}", place_id):
                        continue
                    if (not isinstance(name, str) or not brand_matches(name, aliases)
                            or doc.get("category_group_code") != "FD6"
                            or not category_matches(doc.get("category_name"), aliases)):
                        continue
                    if isinstance(doc["x"], bool) or isinstance(doc["y"], bool):
                        continue
                    lng, lat = float(doc["x"]), float(doc["y"])
                    if not (math.isfinite(lng) and math.isfinite(lat) and -180 <= lng <= 180 and -90 <= lat <= 90):
                        continue
                    distance = meters_between(center, (lng, lat))
                    road_address = doc.get("road_address_name") or ""
                    lot_address = doc.get("address_name") or ""
                    if distance > DELIVERY_LIMIT_METERS or not (road_address or lot_address) or place_id in seen:
                        continue
                    if not all(isinstance(v, str) and len(v) <= 255 for v in (name, road_address, lot_address)):
                        continue
                    seen.add(place_id)
                    results.append(dict(place_id=place_id, place_name=name, road_address=road_address,
                                        lot_address=lot_address, lng=lng, lat=lat, nearby_distance=round(distance)))
                except (KeyError, TypeError, ValueError, OverflowError):
                    continue
            return dict(places=results, is_end=is_end or page >= 45)
        except (KeyError, TypeError, ValueError):
            raise DeliveryError("장소 검색 응답을 처리할 수 없습니다.") from None

    return search_cache.get((address, brand, tuple(aliases), page, DELIVERY_LIMIT_METERS), fetch)


def save_places(cursor, restaurant_id, places):
    saved = []
    for place in places:
        cursor.execute("""INSERT INTO restaurant_branches
            (restaurant_id,provider,place_id,place_name,road_address,lot_address,lng,lat)
            VALUES (%s,'kakao',%s,%s,%s,%s,%s,%s)
            ON DUPLICATE KEY UPDATE id=LAST_INSERT_ID(id), place_name=VALUES(place_name),
            road_address=VALUES(road_address),lot_address=VALUES(lot_address),
            lng=VALUES(lng),lat=VALUES(lat), updated_at=CURRENT_TIMESTAMP""",
            (restaurant_id, place["place_id"], place["place_name"], place["road_address"],
             place["lot_address"], place["lng"], place["lat"]))
        saved.append(dict(place, branch_id=cursor.lastrowid))
    return saved


def load_branch(cursor, branch_id, restaurant_id, lock=False):
    cursor.execute("""SELECT b.id,b.place_id,b.place_name,b.road_address,b.lot_address,b.lng,b.lat,
        r.name,b.restaurant_id FROM restaurant_branches b
        JOIN restaurants r ON r.id=b.restaurant_id WHERE b.id=%s AND b.restaurant_id=%s"""
        + (" FOR SHARE" if lock else ""), (branch_id, restaurant_id))
    row = cursor.fetchone()
    if not row:
        raise DeliveryError("선택한 지점이 올바르지 않습니다. 지점을 다시 선택해 주세요.")
    brand, aliases = mapping_for(cursor, restaurant_id)
    branch = dict(zip(("branch_id", "place_id", "place_name", "road_address", "lot_address", "lng", "lat", "virtual_name", "restaurant_id"), row))
    branch.update(lng=float(branch["lng"]), lat=float(branch["lat"]), brand_name=brand)
    if not brand_matches(branch["place_name"], aliases):
        raise DeliveryError("선택 지점의 브랜드가 일치하지 않습니다.")
    branch["address"] = branch["road_address"] or branch["lot_address"]
    return branch


def branch_digest(branch):
    return digest({key: branch[key] for key in ("branch_id", "place_id", "place_name", "road_address", "lot_address", "lng", "lat", "restaurant_id", "brand_name")})


def validate_grant(branch, grant, user_id, address):
    if not isinstance(grant, dict) or grant.get("a") != address_context(user_id, address) or grant.get("d") != branch_digest(branch):
        raise DeliveryError("배달 주소 또는 지점 정보가 변경되었습니다. 지점을 다시 선택해 주세요.")
    return branch


def split_cart_key(key):
    parts = str(key).split(":")
    if len(parts) not in (1, 2) or not all(p.isdigit() and int(p) > 0 for p in parts):
        raise DeliveryError("잘못된 장바구니 항목입니다.")
    return parts[0], int(parts[1]) if len(parts) == 2 else None
