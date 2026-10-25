-- delivery_app 데이터베이스 선택
USE delivery_app;

-- 주문에 포함된 음식점과 주소 조회
SELECT DISTINCT
    o.id AS order_id,
    r.id AS restaurant_id,
    r.name AS restaurant_name,
    r.address AS restaurant_address
FROM orders o
JOIN order_items oi ON o.id = oi.order_id
JOIN menus m ON oi.menu_id = m.id
JOIN restaurants r ON m.restaurant_id = r.id
ORDER BY o.id DESC, r.id;