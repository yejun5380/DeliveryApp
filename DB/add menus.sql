USE delivery_app

-- 외래키 검사 잠시 비활성화
SET FOREIGN_KEY_CHECKS = 0;

-- 기존 테스트 데이터 전체 삭제
-- TRUNCATE는 데이터 삭제 + AUTO_INCREMENT 초기화
TRUNCATE TABLE order_items;
TRUNCATE TABLE orders;
TRUNCATE TABLE menus;
TRUNCATE TABLE restaurants;

-- 외래키 검사 다시 활성화
SET FOREIGN_KEY_CHECKS = 1;

SELECT * FROM restaurants;
SELECT * FROM menus;
SELECT * FROM orders;
SELECT * FROM order_items;

-- 옷데리아 음식점 추가
-- 실제 브랜드의 공개 데이터를 참고한 프로젝트용 테스트 음식점
INSERT INTO restaurants
(name, category, description, image, address)
VALUES
('옷데리아', '햄버거', '다양한 버거와 사이드 메뉴를 판매하는 패스트푸드점', NULL, '인천광역시 미추홀구 석골로 100');

SET @restaurant_id = LAST_INSERT_ID();

INSERT INTO menus
(restaurant_id, name, price, calories, description, image)
VALUES
(@restaurant_id, '리아 불고기 레드', 6200, 550, '매콤한 맛을 더한 불고기 버거', NULL),
(@restaurant_id, '리아 두툼새우', 7900, 549, '두툼한 새우 패티를 사용한 버거', NULL),
(@restaurant_id, '하와이안 모짜렐라버거', 8800, 773, '모짜렐라 치즈를 활용한 버거', NULL),
(@restaurant_id, '번트비프버거', 8800, 602, '풍미 있는 비프 패티를 활용한 버거', NULL),
(@restaurant_id, '통다리 크리스피치킨버거(파이어핫)', 6900, 594, '매콤한 소스와 통다리 치킨 패티를 활용한 버거', NULL);

-- 두 번째 프로젝트용 음식점 추가
-- 실제 맥도날드를 참고하지만 프로젝트에서는 변형명 사용
INSERT INTO restaurants
(name, category, description, image, address)
VALUES
('맥도널즈', '햄버거', '다양한 햄버거와 사이드 메뉴를 판매하는 패스트푸드점', NULL, NULL);

SELECT id INTO @restaurant_id
FROM restaurants
WHERE name = '맥도널즈'
LIMIT 1;

UPDATE restaurants
SET address = '인천광역시 남동구 구월동 1120-16'
WHERE id = @restaurant_id;

INSERT INTO menus
(restaurant_id, name, price, calories, description, image)
VALUES
(@restaurant_id, '빅맥', 6000, 582, '두 장의 비프 패티와 특제 소스를 사용한 버거', NULL),
(@restaurant_id, '맥스파이시 상하이버거', 6000, 528, '매콤한 치킨 패티를 사용한 치킨버거', NULL),
(@restaurant_id, '1955 버거', 7000, 572, '비프 패티와 다양한 재료를 조합한 버거', NULL),
(@restaurant_id, '불고기버거', 4000, 408, '불고기 소스를 활용한 버거', NULL),
(@restaurant_id, '슈비버거', 7000, 573, '새우 패티와 비프 패티를 함께 사용한 버거', NULL);

INSERT INTO restaurants
(name, category, description, image, address)
VALUES
('맘스타치', '햄버거', '치킨 패티를 중심으로 다양한 버거를 판매하는 패스트푸드점', NULL, NULL);

SET @restaurant_id = LAST_INSERT_ID();

INSERT INTO menus
(restaurant_id, name, price, calories, description, image)
VALUES
(@restaurant_id, '싸이버거', 5000, 594, '매콤한 통다리살 치킨 패티와 신선한 채소가 들어간 버거', NULL),
(@restaurant_id, '불싸이버거', 5200, 620, '매콤한 소스를 더한 통다리살 치킨버거', NULL),
(@restaurant_id, '간장마늘싸이버거', 5400, 650, '간장마늘 소스와 통다리살 치킨 패티가 어우러진 버거', NULL),
(@restaurant_id, '딥치즈버거', 5500, 600, '치즈 소스와 치킨 패티를 사용한 버거', NULL),
(@restaurant_id, '싸이플렉스버거', 8000, 950, '통다리살 치킨 패티 두 장을 사용한 대형 버거', NULL);

INSERT INTO restaurants
(name, category, description, image, address)
VALUES
('BHB치킨', '치킨', '다양한 시즈닝과 소스를 활용한 치킨을 판매하는 치킨 전문점', NULL, NULL);

SET @restaurant_id = LAST_INSERT_ID();

INSERT INTO menus
(restaurant_id, name, price, calories, description, image)
VALUES
(@restaurant_id, '뿌링클', 23000, 2600, '치즈 시즈닝을 활용한 바삭한 치킨', NULL),
(@restaurant_id, '맛초킹', 23000, 2500, '짭조름하고 매콤달콤한 소스를 활용한 치킨', NULL),
(@restaurant_id, '골드킹', 23000, 2500, '달콤하고 짭조름한 소스를 활용한 치킨', NULL),
(@restaurant_id, 'HOT후라이드', 22000, 2400, '매콤한 시즈닝으로 맛을 낸 후라이드 치킨', NULL),
(@restaurant_id, '후라이드', 21000, 2300, '바삭하게 튀긴 기본 후라이드 치킨', NULL);

INSERT INTO restaurants
(name, category, description, image, address)
VALUES
('교춘치킨', '치킨', '간장과 허니 소스를 활용한 다양한 치킨을 판매하는 치킨 전문점', NULL, NULL);

SET @restaurant_id = LAST_INSERT_ID();

INSERT INTO menus
(restaurant_id, name, price, calories, description, image)
VALUES
(@restaurant_id, '허니한마리', 19000, 2500, '달콤한 허니 소스를 활용한 한 마리 치킨', NULL),
(@restaurant_id, '허니콤보', 23000, 2600, '허니 소스와 날개 및 다리 부위를 함께 즐기는 치킨', NULL),
(@restaurant_id, '후라이드한마리', 21000, 2300, '바삭한 튀김옷을 사용한 기본 후라이드 치킨', NULL),
(@restaurant_id, '양념치킨한마리', 22000, 2500, '새콤달콤한 양념소스를 더한 치킨', NULL),
(@restaurant_id, '간장한마리', 19000, 2400, '마늘과 간장 소스를 활용한 치킨', NULL);

INSERT INTO restaurants
(name, category, description, image, address)
VALUES
('BQQ치킨', '치킨', '후라이드와 양념 등 다양한 치킨 메뉴를 판매하는 치킨 전문점', NULL, NULL);

SET @restaurant_id = LAST_INSERT_ID();

INSERT INTO menus
(restaurant_id, name, price, calories, description, image)
VALUES
(@restaurant_id, '황금올리브치킨', 23000, 2500, '바삭한 식감의 기본 후라이드 치킨', NULL),
(@restaurant_id, '황금올리브치킨 양념', 24500, 2700, '달콤한 양념을 더한 치킨', NULL),
(@restaurant_id, '황금올리브치킨 핫크리스피', 24000, 2600, '매콤하고 바삭한 맛을 강조한 치킨', NULL),
(@restaurant_id, '자메이카 통다리구이', 24000, 2200, '매콤한 소스를 활용해 구워낸 닭다리 메뉴', NULL),
(@restaurant_id, '크런치 순살크래커', 23000, 2400, '바삭한 식감으로 즐기는 순살 치킨', NULL);

INSERT INTO restaurants
(name, category, description, image, address)
VALUES
('도미누피자', '피자', '다양한 토핑과 스타일의 피자를 판매하는 피자 전문점', NULL, NULL);

SET @restaurant_id = LAST_INSERT_ID();

INSERT INTO menus
(restaurant_id, name, price, calories, description, image)
VALUES
(@restaurant_id, '블랙타이거 슈림프', 36900, 2600, '새우와 다양한 토핑을 활용한 프리미엄 피자', NULL),
(@restaurant_id, '포테이토', 27900, 2400, '감자와 치즈를 활용한 피자', NULL),
(@restaurant_id, '슈퍼디럭스', 28900, 2500, '고기와 채소 토핑을 다양하게 올린 피자', NULL),
(@restaurant_id, '베이컨체더치즈', 28900, 2700, '베이컨과 체더치즈를 활용한 피자', NULL),
(@restaurant_id, '페퍼로니', 25900, 2500, '페퍼로니와 치즈를 올린 기본 피자', NULL);

INSERT INTO restaurants
(name, category, description, image, address)
VALUES
('피자헛뜨', '피자', '다양한 토핑과 치즈를 활용한 피자를 판매하는 피자 전문점', NULL, NULL);

SET @restaurant_id = LAST_INSERT_ID();

INSERT INTO menus
(restaurant_id, name, price, calories, description, image)
VALUES
(@restaurant_id, '수퍼슈프림', 32900, 2600, '고기와 채소 등 다양한 토핑을 올린 피자', NULL),
(@restaurant_id, '페퍼로니 러버', 31900, 2700, '페퍼로니를 풍성하게 올린 피자', NULL),
(@restaurant_id, '치즈 러버', 30900, 2500, '치즈의 풍미를 강조한 피자', NULL),
(@restaurant_id, '직화불고기', 33900, 2800, '불고기 토핑을 활용한 피자', NULL),
(@restaurant_id, '베이컨 포테이토', 32900, 2700, '베이컨과 감자 토핑을 활용한 피자', NULL);

INSERT INTO restaurants
(name, category, description, image, address)
VALUES
('미스타피자', '피자', '다양한 프리미엄 토핑을 활용한 피자를 판매하는 피자 전문점', NULL, NULL);

SET @restaurant_id = LAST_INSERT_ID();

INSERT INTO menus
(restaurant_id, name, price, calories, description, image)
VALUES
(@restaurant_id, '쉬림프골드', 35900, 2700, '새우와 치즈를 활용한 프리미엄 피자', NULL),
(@restaurant_id, '포테이토골드', 33900, 2600, '감자와 치즈 토핑을 활용한 피자', NULL),
(@restaurant_id, '하와이안스페셜', 32900, 2500, '파인애플과 다양한 토핑을 활용한 피자', NULL),
(@restaurant_id, '불고기피자', 32900, 2700, '불고기 토핑을 풍성하게 올린 피자', NULL),
(@restaurant_id, '페퍼로니피자', 29900, 2500, '페퍼로니와 치즈를 활용한 피자', NULL);

SELECT * FROM restaurants;
SELECT * FROM menus;
