
-- DeliveryApp 데이터베이스 초기 생성 스크립트
-- 주의: 신규 DB 생성용 파일입니다.
-- 기존 데이터가 저장된 MySQL에서 전체 실행하지 마세요.
-- 아래 INSERT 데이터는 초기 테스트용이며 현재 운영 DB 데이터와 다릅니다.

CREATE DATABASE delivery_app
CHARACTER SET utf8mb4
COLLATE utf8mb4_unicode_ci;

USE delivery_app;

-- 1. 회원 테이블

CREATE TABLE users (
    id INT AUTO_INCREMENT PRIMARY KEY,
    username VARCHAR(50) NOT NULL,
    password VARCHAR(255) NOT NULL,
    nickname VARCHAR(50) NOT NULL,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    address VARCHAR(255)
);

-- 비밀번호 해시 저장 방식과 맞지 않아 예제 회원 생성은 비활성화
-- INSERT INTO users (username, password, nickname) VALUES
-- ('test1', '1111', '테스트유저');

SELECT * FROM users;


-- 2. 음식점 테이블

CREATE TABLE restaurants (
    id INT AUTO_INCREMENT PRIMARY KEY,
    name VARCHAR(100) NOT NULL,
    category VARCHAR(50) NOT NULL,
    description VARCHAR(255),
    image VARCHAR(255),
    address VARCHAR(255)
);

-- 초기 테스트 음식점 3곳
-- 실제 운영 DB의 가상 음식점 9곳과는 별개

INSERT INTO restaurants (name, category, description) VALUES
('맛있는 치킨', '치킨', '바삭한 치킨 전문점'),
('행복한 피자', '피자', '다양한 피자를 판매하는 피자집'),
('우리동네 분식', '분식', '떡볶이와 김밥을 판매하는 분식집');

SELECT * FROM restaurants;


-- 3. 메뉴 테이블

CREATE TABLE menus (
    id INT AUTO_INCREMENT PRIMARY KEY,
    restaurant_id INT NOT NULL,
    name VARCHAR(100) NOT NULL,
    price INT NOT NULL,
    calories INT NOT NULL,
    description VARCHAR(255),
    image VARCHAR(255),
    FOREIGN KEY (restaurant_id) REFERENCES restaurants(id)
);

-- 초기 테스트 메뉴 6개

INSERT INTO menus (restaurant_id, name, price, calories, description) VALUES
(1, '후라이드 치킨', 18000, 900, '바삭한 기본 후라이드 치킨'),
(1, '양념 치킨', 19000, 1000, '달콤매콤한 양념 치킨'),
(2, '치즈 피자', 16000, 800, '치즈가 듬뿍 올라간 피자'),
(2, '페퍼로니 피자', 18000, 900, '페퍼로니가 올라간 피자'),
(3, '떡볶이', 5000, 500, '매콤달콤한 떡볶이'),
(3, '김밥', 3500, 400, '기본 김밥');

SELECT * FROM menus;


-- 4. 주문 테이블

CREATE TABLE orders (
    id INT AUTO_INCREMENT PRIMARY KEY,
    user_id INT NOT NULL,
    order_date DATETIME DEFAULT CURRENT_TIMESTAMP,
    total_price INT NOT NULL,
    total_calories INT NOT NULL,
    delivery_address VARCHAR(255),
    FOREIGN KEY (user_id) REFERENCES users(id)
);

-- 회원 생성이 비활성화되어 있어 예제 주문도 비활성화
-- INSERT INTO orders (user_id, total_price, total_calories) VALUES
-- (1, 18000, 900);

SELECT * FROM orders;


-- 5. 주문 상세 테이블

CREATE TABLE order_items (
    id INT AUTO_INCREMENT PRIMARY KEY,
    order_id INT NOT NULL,
    menu_id INT NOT NULL,
    quantity INT NOT NULL,
    price INT NOT NULL,
    calories INT NOT NULL,
    FOREIGN KEY (order_id) REFERENCES orders(id),
    FOREIGN KEY (menu_id) REFERENCES menus(id)
);

-- 예제 주문이 없으므로 주문 상세 INSERT도 비활성화
-- INSERT INTO order_items (order_id, menu_id, quantity, price, calories) VALUES
-- (1, 1, 1, 18000, 900);

SELECT * FROM order_items;


-- 6. 회원별 주문 내역 JOIN 조회

SELECT
    u.nickname,
    o.id AS order_id,
    r.name AS restaurant,
    m.name AS menu,
    oi.quantity,
    oi.price,
    oi.calories
FROM users u
JOIN orders o ON u.id = o.user_id
JOIN order_items oi ON o.id = oi.order_id
JOIN menus m ON oi.menu_id = m.id
JOIN restaurants r ON m.restaurant_id = r.id;
