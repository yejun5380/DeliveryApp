"""SQLite equivalents of the approved point shop tables, for isolated tests only."""
SHOP_SCHEMA = '''
CREATE TABLE point_products(
 id INTEGER PRIMARY KEY AUTOINCREMENT, code TEXT NOT NULL UNIQUE, name TEXT NOT NULL,
 description TEXT NOT NULL,price_points INTEGER NOT NULL CHECK(price_points>0),
 image_path TEXT NOT NULL,is_active INTEGER NOT NULL DEFAULT 1 CHECK(is_active IN(0,1))
);
CREATE TABLE point_purchases(
 id INTEGER PRIMARY KEY AUTOINCREMENT,user_id INTEGER NOT NULL REFERENCES users(id),
 product_id INTEGER NOT NULL REFERENCES point_products(id),product_name TEXT NOT NULL,
 price_points INTEGER NOT NULL CHECK(price_points>0),
 wallet_transaction_id INTEGER NOT NULL UNIQUE REFERENCES wallet_transactions(id),
 request_token TEXT NOT NULL,purchased_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
 UNIQUE(user_id,request_token)
);
INSERT INTO point_products(code,name,description,price_points,image_path)
 VALUES('adult-phone-18','어른폰 18','가상 스마트폰입니다.',1990000,'/static/images/adult_phone_18.svg');
'''
