-- Apply to the existing delivery_app database after the Week 11 cancellation columns exist.
-- Requires MySQL 8.0.16+ with InnoDB users/orders and signed INT primary keys.
-- Create the wallet first, then its ledger. Existing order and user rows are untouched.

CREATE TABLE IF NOT EXISTS wallets (
    id BIGINT NOT NULL AUTO_INCREMENT PRIMARY KEY,
    user_id INT NOT NULL,
    balance BIGINT NOT NULL DEFAULT 0,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    UNIQUE KEY uq_wallet_user (user_id),
    CONSTRAINT fk_wallet_user FOREIGN KEY (user_id) REFERENCES users(id),
    CONSTRAINT chk_wallet_balance CHECK (balance >= 0)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS wallet_transactions (
    id BIGINT NOT NULL AUTO_INCREMENT PRIMARY KEY,
    wallet_id BIGINT NOT NULL,
    order_id INT NULL,
    type VARCHAR(16) NOT NULL,
    amount BIGINT NOT NULL,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE KEY uq_wallet_order_type (order_id, type),
    KEY ix_wallet_history (wallet_id, created_at, id),
    CONSTRAINT fk_wallet_transaction_wallet FOREIGN KEY (wallet_id) REFERENCES wallets(id),
    CONSTRAINT fk_wallet_transaction_order FOREIGN KEY (order_id) REFERENCES orders(id),
    CONSTRAINT chk_wallet_transaction_amount CHECK (amount >= 0),
    CONSTRAINT chk_wallet_earn_order CHECK (type <> 'earn' OR order_id IS NOT NULL)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
