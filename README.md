<!-- 메인 제목 -->
# DeliveryApp - 가상 배달 주문 & 절약 관리 웹 서비스

 배달 앱 서비스 구조를 참고하여 제작한 가상 주문 서비스로, 주문 금액과 칼로리를 기록하여 '절약한 금액'과 '절약한 칼로리'를 시각화해 주는 웹 애플리케이션

---

## 1. 프로젝트 개요
* **진행 기간**: 2026년 2학기 개인 프로젝트
* **핵심 아이디어**: 실제 배달 주문 대신 가상의 주문을 진행하며 사용자가 음식 주문으로 지출하는 비용과 칼로리를 얼마나 줄였는지 계산해 줍니다.

---

## 2. 사용 기술 (Tech Stack)

### Frontend
* HTML5 / CSS3
* JavaScript

### Backend
* Python 3
* Flask (웹 프레임워크)

### Database
* MySQL / MySQL Workbench

### Version Control & Tools
* Git / GitHub
* Visual Studio Code

---

## 3. 프로젝트 폴더 구조

```text
프젝/
├─ app.py               # Flask 백엔드 서버 메인 파일
├─ project.html         # 작업 메모 및 참고용 파일
├─ memo.txt             # 프로젝트 개발 노트
├─ DB/
│  └─ schema.sql        # 데이터베이스 생성 및 테이블 스키마 SQL
└─ templates/           # HTML 화면 템플릿 폴더
   ├─ index.html        # 메인 화면 (음식점 목록 및 검색)
   ├─ restaurant.html   # 음식점 상세 정보 및 메뉴 선택
   ├─ cart.html         # 장바구니 화면
   ├─ order_complete.html# 주문 완료 안내 화면
   ├─ orders.html       # 사용자 주문(절약) 내역 화면
   ├─ saving.html       # 절약 통계 화면
   ├─ signup.html       # 회원가입 화면
   └─ login.html        # 로그인 화면
