USE delivery_app;
-- 기존 주문은 NULL 유지: 과거 API 소요시간을 추측하여 채우지 않습니다.
ALTER TABLE orders
    ADD COLUMN delivery_snapshot LONGTEXT NULL,
    ADD COLUMN request_token CHAR(64) NULL,
    ADD UNIQUE KEY uq_orders_request_token (request_token);
