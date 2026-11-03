import math
import os
import requests
from settings import DELIVERY_LIMIT_METERS


class DeliveryError(Exception):
    pass


def positive(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value <= 0:
        raise DeliveryError('도로 거리 또는 소요시간이 올바르지 않습니다.')
    return value


def time_scale():
    try:
        return positive(float(os.getenv('DELIVERY_TIME_SCALE', '10')))
    except (ValueError, DeliveryError):
        raise DeliveryError('DELIVERY_TIME_SCALE은 양의 유한 숫자여야 합니다.') from None


def api_get(url, params):
    key = os.getenv('KAKAO_REST_API_KEY')
    if not key:
        raise DeliveryError('카카오 REST API 설정을 확인해 주세요.')
    try:
        response = requests.get(url, headers={'Authorization': f'KakaoAK {key}'}, params=params, timeout=(3, 10))
        response.raise_for_status()
        return response.json()
    except (requests.RequestException, ValueError):
        raise DeliveryError('카카오 API 요청 실패 또는 시간 초과로 확인할 수 없습니다.') from None


def address_to_coords(text):
    if not isinstance(text, str) or not text.strip():
        raise DeliveryError('주소가 등록되지 않았습니다.')
    try:
        doc = api_get('https://dapi.kakao.com/v2/local/search/address.json', {'query': text})['documents'][0]
        if isinstance(doc['x'], bool) or isinstance(doc['y'], bool):
            raise ValueError()
        x, y = float(doc['x']), float(doc['y'])
        if not math.isfinite(x) or not math.isfinite(y) or not (-180 <= x <= 180 and -90 <= y <= 90):
            raise ValueError()
        return (x, y)
    except (KeyError, IndexError, TypeError, ValueError, OverflowError):
        raise DeliveryError('주소 좌표 변환에 실패했습니다.') from None


def inspect_delivery(address, restaurants):
    coords = {}

    def locate(text):
        if text not in coords:
            coords[text] = address_to_coords(text)
        return coords[text]

    destination = locate(address)
    results = []
    routes_by_address = {}
    # Tuple inputs remain available for existing unit-level callers; checkout only passes verified branches.
    entries = restaurants if isinstance(restaurants, list) else sorted(set(restaurants))
    for entry in entries:
        branch = entry if isinstance(entry, dict) else None
        name = f'{branch["virtual_name"]} · {branch["place_name"]}' if branch else entry[0]
        route_key = branch['branch_id'] if branch else entry[1]
        try:
            if route_key not in routes_by_address:
                origin = (branch['lng'], branch['lat']) if branch else locate(entry[1])
                data = api_get('https://apis-navi.kakaomobility.com/v1/directions', {
                    'origin': f'{origin[0]},{origin[1]}',
                    'destination': f'{destination[0]},{destination[1]}',
                    'priority': 'DISTANCE', 'summary': 'false'})
                route = data['routes'][0]
                if type(route['result_code']) is not int or route['result_code'] != 0:
                    raise DeliveryError('자동차 도로 경로를 찾을 수 없습니다.')
                distance = positive(route['summary']['distance'])
                duration = positive(route['summary']['duration'])
                path = []
                for section in route['sections']:
                    for road in section['roads']:
                        vertices = road['vertexes']
                        if len(vertices) % 2:
                            raise ValueError()
                        for i in range(0, len(vertices), 2):
                            x, y = vertices[i:i+2]
                            if isinstance(x, bool) or isinstance(y, bool) or not (math.isfinite(x) and math.isfinite(y) and -180 <= x <= 180 and -90 <= y <= 90):
                                raise ValueError()
                            point = {'lng': x, 'lat': y}
                            if not path or point != path[-1]:
                                path.append(point)
                if len(path) < 2:
                    raise DeliveryError('유효한 도로 경로 좌표가 없습니다.')
                routes_by_address[route_key] = dict(distance=distance, duration=duration, path=path)
            result = dict(routes_by_address[route_key], name=name, status='available')
            if result['distance'] > DELIVERY_LIMIT_METERS:
                result['status'] = 'unavailable'
            if branch:
                result['branch'] = dict(branch)
            results.append(result)
        except (KeyError, IndexError, TypeError, ValueError, DeliveryError) as error:
            results.append(dict(name=name, status='unknown', message=str(error) if isinstance(error, DeliveryError) else '잘못된 API 응답입니다.'))
    if not results:
        raise DeliveryError('음식점 정보가 없습니다.')
    return results
