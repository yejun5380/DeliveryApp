"""Virtual point purchases. No payment, shipping or external API integration."""
import re
from wallet import MAX_BALANCE


class ShopError(Exception):
    pass


def purchase_product(connection, user_id, product_id, expected_price, request_token):
    """Own one transaction; lock the member first, as wallet reconciliation does."""
    if (type(user_id) is not int or type(product_id) is not int or product_id <= 0
            or type(expected_price) is not int or not 0 < expected_price <= MAX_BALANCE
            or not isinstance(request_token, str) or not re.fullmatch(r'[0-9a-f]{64}', request_token)):
        raise ShopError('구매 정보를 다시 확인해 주세요.')
    cursor = connection.cursor()
    try:
        connection.start_transaction()
        cursor.execute('SELECT id FROM users WHERE id=%s FOR UPDATE', (user_id,))
        if cursor.fetchone() is None:
            raise ShopError('로그인 정보를 확인해 주세요.')
        cursor.execute('''SELECT id,product_id,product_name,price_points FROM point_purchases
                          WHERE user_id=%s AND request_token=%s''', (user_id,request_token))
        existing = cursor.fetchone()
        if existing:
            if existing[1] != product_id:
                raise ShopError('구매 정보를 다시 확인해 주세요.')
            connection.commit()
            return dict(id=existing[0],name=existing[2],price=existing[3],replayed=True)
        cursor.execute('SELECT name,price_points,is_active FROM point_products WHERE id=%s FOR SHARE', (product_id,))
        product = cursor.fetchone()
        if not product or product[2] != 1:
            raise ShopError('현재 구매할 수 없는 상품입니다.')
        name, price, _ = product
        if type(price) is not int or not 0 < price <= MAX_BALANCE or price != expected_price:
            raise ShopError('상품 가격이 변경되었습니다. 다시 확인해 주세요.')
        cursor.execute('SELECT id,balance FROM wallets WHERE user_id=%s FOR UPDATE', (user_id,))
        wallet = cursor.fetchone()
        if wallet is None:
            raise ShopError('보유 포인트가 부족합니다.')
        wallet_id, balance = wallet
        if type(balance) is not int or not 0 <= balance <= MAX_BALANCE:
            raise ShopError('포인트 잔액을 확인할 수 없습니다.')
        if balance < price:
            raise ShopError(f'포인트가 {price-balance:,}포인트 부족합니다.')
        cursor.execute('''UPDATE wallets SET balance=balance-%s
                          WHERE id=%s AND user_id=%s AND balance>=%s''', (price,wallet_id,user_id,price))
        if cursor.rowcount != 1:
            raise ShopError('보유 포인트가 부족합니다. 잔액을 다시 확인해 주세요.')
        cursor.execute("""INSERT INTO wallet_transactions(wallet_id,order_id,type,amount)
                          VALUES(%s,NULL,'spend',%s)""", (wallet_id,price))
        transaction_id = cursor.lastrowid
        cursor.execute('''INSERT INTO point_purchases
                          (user_id,product_id,product_name,price_points,wallet_transaction_id,request_token)
                          VALUES(%s,%s,%s,%s,%s,%s)''', (user_id,product_id,name,price,transaction_id,request_token))
        purchase_id = cursor.lastrowid
        connection.commit()
        return dict(id=purchase_id,name=name,price=price,replayed=False)
    except Exception:
        connection.rollback()
        raise
    finally:
        cursor.close()
