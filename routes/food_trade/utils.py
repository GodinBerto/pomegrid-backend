from database.connection import db_connection

def update_product_stock(product_id, qty):
    try:
        conn, cursor = db_connection()
        # Decrement stock, ensuring it doesn't go below 0
        cursor.execute(
            "UPDATE food_trade_products SET stock_qty = MAX(0, stock_qty - ?) WHERE id = ?",
            (qty, product_id)
        )
        conn.commit()
    except Exception as e:
        print(f"Error updating stock for product {product_id}: {e}")
    finally:
        try:
            conn.close()
        except Exception:
            pass


def check_admin(user_id):
    conn, cursor = db_connection()
    cursor.execute("SELECT role FROM food_trade_user_roles WHERE user_id = ? AND role = 'admin'", (user_id,))
    row = cursor.fetchone()
    conn.close()
    return bool(row)
