CREATE DATABASE delivery_app
CHARACTER SET utf8mb4
COLLATE utf8mb4_unicode_ci;

USE delivery_app

-- 유저 테이블 

CREATE TABLE users (

    id INT AUTO_INCREMENT PRIMARY KEY,
    username VARCHAR(50) NOT NULL,
    password VARCHAR(255) NOT NULL,
    nickname VARCHAR(50) NOT NULL,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

INSERT INTO users (username, password, nickname) VALUES 
('test1', '1111', '테스트유저');

SELECT * FROM users;

-- 음식점

CREATE TABLE restaurants (
    id INT AUTO_INCREMENT PRIMARY KEY,
    name VARCHAR(100) NOT NULL,
    category VARCHAR(50) NOT NULL,
    description VARCHAR(255),
    image VARCHAR(255)
);

INSERT INTO restaurants (name, category, description) VALUES
('맛있는 치킨', '치킨', '바삭한 치킨 전문점'),
('행복한 피자', '피자', '다양한 피자를 판매하는 피자집'),
('우리동네 분식', '분식', '떡볶이와 김밥을 판매하는 분식집');

SELECT * FROM restaurants;

-- 메뉴

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

-- 1: 치킨, 2: 피자, 3: 분식

INSERT INTO menus (restaurant_id, name, price, calories, description) VALUES
(1, '후라이드 치킨', 18000, 900, '바삭한 기본 후라이드 치킨'),
(1, '양념 치킨', 19000, 1000, '달콤매콤한 양념 치킨');

INSERT INTO menus (restaurant_id, name, price, calories, description) VALUES
(2, '치즈 피자', 16000, 800, '치즈가 듬뿍 올라간 피자'),
(2, '페퍼로니 피자', 18000, 900, '페퍼로니가 올라간 피자');

INSERT INTO menus (restaurant_id, name, price, calories, description) VALUES
(3, '떡볶이', 5000, 500, '매콤달콤한 떡볶이'),
(3, '김밥', 3500, 400, '기본 김밥');

SELECT * FROM menus;

-- 주문

CREATE TABLE orders (
    id INT AUTO_INCREMENT PRIMARY KEY,
    user_id INT NOT NULL,
    order_date DATETIME DEFAULT CURRENT_TIMESTAMP,
    total_price INT NOT NULL,
    total_calories INT NOT NULL,
    FOREIGN KEY (user_id) REFERENCES users(id)
);

INSERT INTO orders (user_id, total_price, total_calories) VALUES 
(1, 18000, 900);

SELECT * FROM orders;

-- 주문 정보

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

INSERT INTO order_items (order_id, menu_id, quantity, price, calories) VALUES 
(1, 1, 1, 18000, 900);

SELECT * FROM order_items;

SELECT u.nickname, o.id AS order_id, r.name AS restaurant, m.name AS menu, oi.quantity, oi.price, oi.calories
FROM users u
JOIN orders o ON u.id = o.user_id
JOIN order_items oi ON o.id = oi.order_id
JOIN menus m ON oi.menu_id = m.id
JOIN restaurants r ON m.restaurant_id = r.id;