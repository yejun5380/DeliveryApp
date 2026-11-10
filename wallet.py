"""Reconcile completed orders into the virtual savings ledger."""

from delivery import DELIVERY_ELAPSED_SQL, DeliveryError, delivery_progress


MAX_BALANCE = 2**63 - 1


class WalletError(Exception):
    pass


def reconcile_wallet(connection, user_id, order_id=None):
    """Own the transaction on an idle connection. A scheduler can call this too."""
    cursor = connection.cursor()
    try:
        connection.start_transaction()
        # Serialize reconciliations for this member, even before a wallet exists.
        cursor.execute("SELECT id FROM users WHERE id=%s FOR UPDATE", (user_id,))
        if cursor.fetchone() is None:
            connection.rollback()
            return

        order_filter = " AND o.id=%s" if order_id is not None else ""
        params = (user_id, order_id) if order_id is not None else (user_id,)
        cursor.execute(f"""
            SELECT o.id FROM orders o
            WHERE o.user_id=%s AND o.status='active' AND o.delivery_snapshot IS NOT NULL
            {order_filter}
            AND NOT EXISTS (
                SELECT 1 FROM wallet_transactions t WHERE t.order_id=o.id AND t.type='earn'
            )
            ORDER BY o.id
        """, params)
        candidates = cursor.fetchall()
        earnings = []
        for (candidate,) in candidates:
            # Cancellation takes this same row lock. Recheck current status under it.
            cursor.execute("""
                SELECT status, total_price, delivery_snapshot FROM orders
                WHERE id=%s AND user_id=%s FOR UPDATE
            """, (candidate, user_id))
            row = cursor.fetchone()
            if not row:
                continue
            status, amount, snapshot = row
            if status != "active" or type(amount) is not int or not 0 <= amount <= MAX_BALANCE:
                continue
            # NOW() is evaluated after waiting for the order lock.
            cursor.execute(f"SELECT {DELIVERY_ELAPSED_SQL} FROM orders WHERE id=%s FOR UPDATE", (candidate,))
            try:
                _, _, complete = delivery_progress(snapshot, cursor.fetchone()[0])
            except DeliveryError:
                continue
            if complete:
                earnings.append((candidate, amount))

        if earnings:
            cursor.execute("SELECT id, balance FROM wallets WHERE user_id=%s FOR UPDATE", (user_id,))
            wallet = cursor.fetchone()
            if wallet is None:
                cursor.execute("INSERT INTO wallets (user_id) VALUES (%s)", (user_id,))
                wallet_id, balance = cursor.lastrowid, 0
            else:
                wallet_id, balance = wallet
            credit = sum(amount for _, amount in earnings)
            if not 0 <= balance <= MAX_BALANCE - credit:
                raise WalletError("저금통 잔액 한도를 초과하여 적립할 수 없습니다.")
            for candidate, amount in earnings:
                cursor.execute("""
                    INSERT INTO wallet_transactions (wallet_id, order_id, type, amount)
                    VALUES (%s, %s, 'earn', %s)
                """, (wallet_id, candidate, amount))
            cursor.execute("UPDATE wallets SET balance=%s WHERE id=%s", (balance + credit, wallet_id))
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        cursor.close()
