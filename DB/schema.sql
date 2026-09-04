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

-- 음식점

CREATE TABLE restaurants (
    id INT AUTO_INCREMENT PRIMARY KEY,
    name VARCHAR(100) NOT NULL,
    category VARCHAR(50) NOT NULL,
    description VARCHAR(255),
    image VARCHAR(255)
);