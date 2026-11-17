-- Approved and applied on 2026-11-17. Do not rerun against the same database.
-- Apply to the already selected DeliveryApp database.
-- Requires MySQL 8.0.16+ and InnoDB; existing users.id is signed INT,
-- wallet_transactions.id is signed BIGINT.
-- Existing tables, balances, earnings and orders are never altered here.
-- MySQL CREATE TABLE implicitly commits: validate/backup before approved execution.
-- Intentionally fail if a shop table already exists; inspect instead of overwriting.

CREATE TABLE point_products (
    id BIGINT NOT NULL AUTO_INCREMENT PRIMARY KEY,
    code VARCHAR(64) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
    name VARCHAR(100) NOT NULL,
    description VARCHAR(500) NOT NULL,
    price_points BIGINT NOT NULL,
    image_path VARCHAR(255) NOT NULL,
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    updated_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6)
        ON UPDATE CURRENT_TIMESTAMP(6),
    UNIQUE KEY uq_point_product_code (code),
    CONSTRAINT chk_point_product_price CHECK (price_points > 0),
    CONSTRAINT chk_point_product_active CHECK (is_active IN (0, 1))
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE point_purchases (
    id BIGINT NOT NULL AUTO_INCREMENT PRIMARY KEY,
    user_id INT NOT NULL,
    product_id BIGINT NOT NULL,
    product_name VARCHAR(100) NOT NULL,
    price_points BIGINT NOT NULL,
    wallet_transaction_id BIGINT NOT NULL,
    request_token CHAR(64) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
    purchased_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    UNIQUE KEY uq_point_purchase_request (user_id, request_token),
    UNIQUE KEY uq_point_purchase_transaction (wallet_transaction_id),
    KEY ix_point_purchase_history (user_id, purchased_at, id),
    CONSTRAINT fk_point_purchase_user FOREIGN KEY (user_id) REFERENCES users(id),
    CONSTRAINT fk_point_purchase_product FOREIGN KEY (product_id) REFERENCES point_products(id),
    CONSTRAINT fk_point_purchase_transaction FOREIGN KEY (wallet_transaction_id)
        REFERENCES wallet_transactions(id),
    CONSTRAINT chk_point_purchase_price CHECK (price_points > 0)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- User-specified provisional point price; this does not assert a live retail price.
-- The SVG asset will be authored locally when implementation is approved.
INSERT INTO point_products
    (code, name, description, price_points, image_path)
VALUES
    ('adult-phone-18', '어른폰 18',
     '포인트로 모으는 가상 스마트폰입니다. 실제 결제·배송·현금 교환은 제공하지 않습니다.',
     1990000, '/static/images/adult_phone_18.svg');
