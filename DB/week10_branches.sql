-- DeliveryApp 10주차 네 번째 기능. 기존 10주차 마이그레이션 적용 후 실행.
-- 자동 실행하지 않습니다. 먼저 백업하고 별도 점검 시간에 실행하세요.
-- MySQL 8 / InnoDB 기준. CREATE ROUTINE 권한 필요.
-- 재실행/부분 적용 흔적이 있으면 SIGNAL로 중단합니다. DDL은 자동 커밋되므로
-- 실패 시 원인을 확인하고 수동으로 복구해야 합니다. 무조건 다시 실행하지 마세요.
USE delivery_app;
DELIMITER $$
DROP PROCEDURE IF EXISTS migrate_week10_branches$$
CREATE PROCEDURE migrate_week10_branches()
BEGIN
    IF EXISTS (SELECT 1 FROM information_schema.tables WHERE table_schema=DATABASE()
        AND table_name IN ('restaurant_brand_mappings','restaurant_branches','order_restaurants'))
       OR EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema=DATABASE()
        AND table_name='order_items' AND column_name='order_restaurant_id') THEN
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT='Branch migration already applied or partially applied. Inspect before retry.';
    END IF;
    IF (SELECT COUNT(*) FROM information_schema.columns WHERE table_schema=DATABASE()
        AND table_name='orders' AND column_name IN ('delivery_snapshot','request_token')) <> 2 THEN
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT='Apply original week10 migration first.';
    END IF;
    IF (SELECT COUNT(*) FROM restaurants WHERE
        (id=1 AND name='옷데리아') OR (id=2 AND name='맥도널즈') OR
        (id=3 AND name='맘스타치') OR (id=4 AND name='BHB치킨') OR
        (id=5 AND name='교춘치킨') OR (id=6 AND name='BQQ치킨') OR
        (id=7 AND name='도미누피자') OR (id=8 AND name='피자헛뜨') OR
        (id=9 AND name='미스타피자')) <> 9 THEN
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT='Expected virtual restaurant IDs and names do not match.';
    END IF;

    CREATE TABLE restaurant_brand_mappings (
        restaurant_id INT PRIMARY KEY,
        brand_name VARCHAR(100) NOT NULL,
        aliases JSON NOT NULL,
        enabled BOOLEAN NOT NULL DEFAULT TRUE,
        FOREIGN KEY (restaurant_id) REFERENCES restaurants(id)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

    CREATE TABLE restaurant_branches (
        id INT AUTO_INCREMENT PRIMARY KEY,
        restaurant_id INT NOT NULL,
        provider VARCHAR(20) NOT NULL DEFAULT 'kakao',
        place_id VARCHAR(64) NOT NULL,
        place_name VARCHAR(255) NOT NULL,
        road_address VARCHAR(255) NOT NULL,
        lot_address VARCHAR(255) NOT NULL,
        lng DECIMAL(18,14) NOT NULL,
        lat DECIMAL(18,14) NOT NULL,
        updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
        UNIQUE KEY uq_branch_place (restaurant_id,provider,place_id),
        FOREIGN KEY (restaurant_id) REFERENCES restaurants(id)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

    CREATE TABLE order_restaurants (
        id INT AUTO_INCREMENT PRIMARY KEY,
        order_id INT NOT NULL,
        restaurant_id INT NOT NULL,
        branch_id INT NOT NULL,
        virtual_name VARCHAR(100) NOT NULL,
        brand_name VARCHAR(100) NOT NULL,
        provider VARCHAR(20) NOT NULL DEFAULT 'kakao',
        place_id VARCHAR(64) NOT NULL,
        place_name VARCHAR(255) NOT NULL,
        road_address VARCHAR(255) NOT NULL,
        lot_address VARCHAR(255) NOT NULL,
        lng DECIMAL(18,14) NOT NULL,
        lat DECIMAL(18,14) NOT NULL,
        road_distance DOUBLE NOT NULL,
        road_duration DOUBLE NOT NULL,
        route_snapshot LONGTEXT NOT NULL,
        UNIQUE KEY uq_order_branch (order_id,branch_id),
        UNIQUE KEY uq_order_restaurant_parent (order_id,id),
        FOREIGN KEY (order_id) REFERENCES orders(id),
        FOREIGN KEY (restaurant_id) REFERENCES restaurants(id),
        FOREIGN KEY (branch_id) REFERENCES restaurant_branches(id)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

    ALTER TABLE order_items
        ADD COLUMN order_restaurant_id INT NULL,
        ADD CONSTRAINT fk_order_item_branch FOREIGN KEY (order_id,order_restaurant_id)
            REFERENCES order_restaurants(order_id,id);

    INSERT INTO restaurant_brand_mappings (restaurant_id,brand_name,aliases) VALUES
        (1,'롯데리아',JSON_ARRAY('롯데리아')),
        (2,'맥도날드',JSON_ARRAY('맥도날드')),
        (3,'맘스터치',JSON_ARRAY('맘스터치')),
        (4,'bhc치킨',JSON_ARRAY('bhc치킨','bhc')),
        (5,'교촌치킨',JSON_ARRAY('교촌치킨')),
        (6,'BBQ치킨',JSON_ARRAY('BBQ치킨','BBQ','비비큐')),
        (7,'도미노피자',JSON_ARRAY('도미노피자')),
        (8,'피자헛',JSON_ARRAY('피자헛')),
        (9,'미스터피자',JSON_ARRAY('미스터피자'));
END$$
CALL migrate_week10_branches()$$
DROP PROCEDURE migrate_week10_branches$$
DELIMITER ;
-- 기존 restaurants/menus/orders의 값은 변경하지 않습니다.
-- 기존 order_items.order_restaurant_id는 NULL 유지. 과거 지점을 추정하지 않습니다.
