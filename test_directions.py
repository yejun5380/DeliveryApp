
import os
import requests
from dotenv import load_dotenv

load_dotenv()

api_key = os.getenv("KAKAO_REST_API_KEY")

if not api_key:
    print("오류: .env에서 KAKAO_REST_API_KEY를 찾을 수 없습니다.")
    raise SystemExit(1)

url = "https://apis-navi.kakaomobility.com/v1/directions"

# API는 주소 대신 경도(x), 위도(y)를 사용함
# 아래 좌표는 연결 확인용 예시이며 실제 음식점 좌표가 아님
params = {
    "origin": "126.6570,37.4506",
    "destination": "126.6630,37.4480",
    "priority": "DISTANCE"
}

headers = {
    "Authorization": f"KakaoAK {api_key}"
}

try:
    response = requests.get(
        url,
        headers=headers,
        params=params,
        timeout=10
    )

    print("HTTP 상태 코드:", response.status_code)

    data = response.json()

    if response.status_code == 200 and data.get("routes"):
        route = data["routes"][0]
        summary = route.get("summary", {})

        print("경로 조회 성공!")
        print("거리:", summary.get("distance"), "m")
        print("예상 소요시간:", summary.get("duration"), "초")
        print("도로 구간 수:", len(route.get("sections", [])))
    else:
        print("API 응답:", data)

except requests.RequestException as error:
    print("요청 오류:", error)
except ValueError:
    print("JSON이 아닌 응답을 받았습니다.")
