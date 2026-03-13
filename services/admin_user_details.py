from datetime import datetime, timezone


def _normalize_status(value):
    return str(value or "").strip().lower()


def _parse_timestamp(value):
    if value is None:
        return None
    if isinstance(value, datetime):
        return value

    raw = str(value).strip()
    if not raw:
        return None

    normalized = raw.replace(" ", "T")
    if normalized.endswith("Z"):
        normalized = normalized[:-1] + "+00:00"

    try:
        return datetime.fromisoformat(normalized)
    except ValueError:
        for fmt in (
            "%Y-%m-%d %H:%M:%S",
            "%Y-%m-%d %H:%M:%S.%f",
            "%Y-%m-%dT%H:%M:%S",
            "%Y-%m-%dT%H:%M:%S.%f",
            "%Y-%m-%d",
        ):
            try:
                return datetime.strptime(raw, fmt)
            except ValueError:
                continue
    return None


def _format_joined_date(value):
    dt_value = _parse_timestamp(value)
    if dt_value is None:
        return None
    return f"{dt_value.month}/{dt_value.day}/{dt_value.year}"


def _format_relative_time(value):
    dt_value = _parse_timestamp(value)
    if dt_value is None:
        return None

    if dt_value.tzinfo is None:
        dt_value = dt_value.replace(tzinfo=timezone.utc)
    else:
        dt_value = dt_value.astimezone(timezone.utc)

    now = datetime.now(timezone.utc)
    delta = now - dt_value
    seconds = max(int(delta.total_seconds()), 0)

    if seconds < 60:
        return "just now"

    minutes = seconds // 60
    if minutes < 60:
        return f"{minutes} minute{'s' if minutes != 1 else ''} ago"

    hours = minutes // 60
    if hours < 24:
        return f"{hours} hour{'s' if hours != 1 else ''} ago"

    days = hours // 24
    if days < 30:
        return f"{days} day{'s' if days != 1 else ''} ago"

    months = days // 30
    if months < 12:
        return f"{months} month{'s' if months != 1 else ''} ago"

    years = days // 365
    return f"{years} year{'s' if years != 1 else ''} ago"


def _build_initials(full_name):
    parts = [part[0].upper() for part in str(full_name or "").split() if part.strip()]
    if not parts:
        return "U"
    return "".join(parts[:2])


def _format_price(value):
    return round(float(value or 0), 2)


def _serialize_order_item(row):
    item = dict(row)
    item["quantity"] = int(item.get("quantity") or 0)
    item["unit_price"] = _format_price(item.get("unit_price"))
    item["line_total"] = _format_price(item["quantity"] * item["unit_price"])
    return item


def _fetch_order_items_map(cursor, order_ids):
    normalized_ids = []
    seen = set()
    for order_id in order_ids or []:
        try:
            normalized = int(order_id)
        except (TypeError, ValueError):
            continue
        if normalized in seen:
            continue
        seen.add(normalized)
        normalized_ids.append(normalized)

    if not normalized_ids:
        return {}

    placeholders = ", ".join(["?"] * len(normalized_ids))
    cursor.execute(
        f"""
        SELECT
            oi.id,
            oi.order_id,
            oi.product_id,
            oi.name,
            oi.quantity,
            oi.unit_price,
            oi.created_at,
            p.image_url
        FROM OrderItems oi
        LEFT JOIN Products p ON p.id = oi.product_id
        WHERE oi.order_id IN ({placeholders})
        ORDER BY oi.order_id DESC, oi.id ASC
        """,
        tuple(normalized_ids),
    )

    items_map = {order_id: [] for order_id in normalized_ids}
    for row in cursor.fetchall():
        row_dict = _serialize_order_item(row)
        items_map.setdefault(int(row_dict["order_id"]), []).append(row_dict)
    return items_map


def _serialize_order(order_row, items_map):
    order = dict(order_row)
    order_id = int(order["id"])
    items = items_map.get(order_id, [])
    order["id"] = order_id
    order["user_id"] = int(order.get("user_id") or 0)
    order["status"] = _normalize_status(order.get("status"))
    order["total_price"] = _format_price(order.get("total_price"))
    order["item_count"] = int(sum(item.get("quantity", 0) for item in items))
    order["line_items"] = int(len(items))
    order["items"] = items
    return order


def _empty_largest_order():
    return {
        "order_id": None,
        "amount": 0.0,
        "status": None,
        "created_at": None,
        "label": "N/A",
    }


def _empty_largest_basket():
    return {
        "order_id": None,
        "items_count": 0,
        "distinct_items": 0,
        "total_price": 0.0,
        "label": "N/A",
    }


def build_admin_user_details(cursor, user_id, recent_orders_limit=5):
    cursor.execute(
        """
        SELECT
            id,
            username,
            email,
            full_name,
            phone,
            user_type,
            role,
            status,
            is_admin,
            is_active,
            is_verified,
            address,
            profile_image_url,
            avatar,
            date_of_birth,
            created_at,
            updated_at
        FROM Users
        WHERE id = ?
        """,
        (user_id,),
    )
    user_row = cursor.fetchone()
    if not user_row:
        return None

    cursor.execute(
        """
        SELECT
            COALESCE(
                SUM(
                    CASE
                        WHEN LOWER(COALESCE(status, '')) != 'cancelled' THEN 1
                        ELSE 0
                    END
                ),
                0
            ) AS total_orders,
            COALESCE(
                SUM(
                    CASE
                        WHEN LOWER(COALESCE(status, '')) IN ('pending', 'completed') THEN total_price
                        ELSE 0
                    END
                ),
                0
            ) AS lifetime_spend,
            COALESCE(
                SUM(
                    CASE
                        WHEN LOWER(COALESCE(status, '')) IN ('pending', 'completed') THEN 1
                        ELSE 0
                    END
                ),
                0
            ) AS spend_orders,
            COALESCE(
                SUM(
                    CASE
                        WHEN LOWER(COALESCE(status, '')) = 'completed' THEN 1
                        ELSE 0
                    END
                ),
                0
            ) AS delivered_orders,
            COALESCE(
                SUM(
                    CASE
                        WHEN LOWER(COALESCE(status, '')) IN ('pending', 'processing') THEN 1
                        ELSE 0
                    END
                ),
                0
            ) AS open_orders
        FROM Orders
        WHERE user_id = ?
        """,
        (user_id,),
    )
    summary_row = cursor.fetchone()

    cursor.execute(
        """
        SELECT COALESCE(SUM(oi.quantity), 0) AS items_purchased
        FROM OrderItems oi
        JOIN Orders o ON o.id = oi.order_id
        WHERE o.user_id = ?
          AND LOWER(COALESCE(o.status, '')) != 'cancelled'
        """,
        (user_id,),
    )
    items_purchased_row = cursor.fetchone()
    items_purchased = int(items_purchased_row["items_purchased"] or 0) if items_purchased_row else 0

    cursor.execute(
        """
        SELECT
            id,
            user_id,
            status,
            total_price,
            payment_method,
            shipping_address,
            notes,
            created_at,
            updated_at
        FROM Orders
        WHERE user_id = ?
          AND LOWER(COALESCE(status, '')) != 'cancelled'
        ORDER BY created_at DESC, id DESC
        LIMIT 1
        """,
        (user_id,),
    )
    latest_non_cancelled_order = cursor.fetchone()

    cursor.execute(
        """
        SELECT
            id,
            user_id,
            status,
            total_price,
            payment_method,
            shipping_address,
            notes,
            created_at,
            updated_at
        FROM Orders
        WHERE user_id = ?
          AND LOWER(COALESCE(status, '')) = 'completed'
        ORDER BY created_at DESC, id DESC
        LIMIT 1
        """,
        (user_id,),
    )
    latest_completed_order = cursor.fetchone()

    cursor.execute(
        """
        SELECT
            id,
            user_id,
            status,
            total_price,
            payment_method,
            shipping_address,
            notes,
            created_at,
            updated_at
        FROM Orders
        WHERE user_id = ?
          AND LOWER(COALESCE(status, '')) != 'cancelled'
        ORDER BY total_price DESC, created_at DESC, id DESC
        LIMIT 1
        """,
        (user_id,),
    )
    largest_order_row = cursor.fetchone()

    cursor.execute(
        """
        SELECT
            o.id AS order_id,
            o.total_price,
            COALESCE(SUM(oi.quantity), 0) AS items_count,
            COUNT(oi.id) AS distinct_items
        FROM Orders o
        LEFT JOIN OrderItems oi ON oi.order_id = o.id
        WHERE o.user_id = ?
          AND LOWER(COALESCE(o.status, '')) != 'cancelled'
        GROUP BY o.id, o.total_price, o.created_at
        ORDER BY items_count DESC, distinct_items DESC, o.created_at DESC, o.id DESC
        LIMIT 1
        """,
        (user_id,),
    )
    largest_basket_row = cursor.fetchone()

    cursor.execute(
        """
        SELECT
            id,
            user_id,
            status,
            total_price,
            payment_method,
            shipping_address,
            notes,
            created_at,
            updated_at
        FROM Orders
        WHERE user_id = ?
          AND LOWER(COALESCE(status, '')) != 'cancelled'
        ORDER BY created_at DESC, id DESC
        LIMIT ?
        """,
        (user_id, int(max(recent_orders_limit, 1))),
    )
    recent_order_rows = cursor.fetchall()

    order_ids = [row["id"] for row in recent_order_rows]
    if latest_completed_order:
        order_ids.append(latest_completed_order["id"])
    items_map = _fetch_order_items_map(cursor, order_ids)

    recent_orders = [_serialize_order(row, items_map) for row in recent_order_rows]
    latest_purchase = (
        _serialize_order(latest_completed_order, items_map)
        if latest_completed_order
        else None
    )

    cursor.execute(
        """
        SELECT
            Cart.id AS cart_id,
            Cart.product_id,
            Cart.quantity,
            Cart.created_at,
            Cart.updated_at,
            Products.title AS name,
            Products.price,
            Products.image_url
        FROM Cart
        JOIN Products ON Products.id = Cart.product_id
        WHERE Cart.user_id = ?
        ORDER BY Cart.updated_at DESC, Cart.id DESC
        """,
        (user_id,),
    )
    cart_rows = cursor.fetchall()

    latest_basket = None
    if cart_rows:
        basket_items = []
        latest_basket_updated_at = None
        for row in cart_rows:
            item = dict(row)
            item["quantity"] = int(item.get("quantity") or 0)
            item["price"] = _format_price(item.get("price"))
            item["total_price"] = _format_price(item["quantity"] * item["price"])
            basket_items.append(item)

            updated_at = _parse_timestamp(item.get("updated_at"))
            if updated_at is not None and (
                latest_basket_updated_at is None or updated_at > latest_basket_updated_at
            ):
                latest_basket_updated_at = updated_at

        latest_basket = {
            "items": basket_items,
            "item_count": int(sum(item["quantity"] for item in basket_items)),
            "distinct_items": int(len(basket_items)),
            "total_price": _format_price(
                sum(item["total_price"] for item in basket_items)
            ),
            "updated_at": (
                latest_basket_updated_at.isoformat().replace("+00:00", "Z")
                if latest_basket_updated_at is not None
                else str(cart_rows[0]["updated_at"])
            ),
        }

    user = dict(user_row)
    user["id"] = int(user["id"])
    user["status"] = _normalize_status(
        user.get("status") or ("active" if bool(user.get("is_active")) else "inactive")
    )
    user["is_active"] = bool(user.get("is_active"))
    user["is_admin"] = int(bool(user.get("is_admin")))
    user["is_verified"] = bool(user.get("is_verified"))
    user["customer_number"] = user["id"]
    user["initials"] = _build_initials(user.get("full_name"))
    user["joined_date_label"] = _format_joined_date(user.get("created_at"))
    user["member_since_label"] = _format_relative_time(user.get("created_at"))
    user["purchase_status_label"] = (
        "No purchases yet"
        if int(summary_row["delivered_orders"] or 0) == 0
        else "Has completed purchases"
    )

    lifetime_spend = _format_price(summary_row["lifetime_spend"])
    spend_orders = int(summary_row["spend_orders"] or 0)
    average_order = _format_price(lifetime_spend / spend_orders) if spend_orders > 0 else 0.0

    largest_order = _empty_largest_order()
    if largest_order_row:
        largest_order_amount = _format_price(largest_order_row["total_price"])
        largest_order = {
            "order_id": int(largest_order_row["id"]),
            "amount": largest_order_amount,
            "status": _normalize_status(largest_order_row["status"]),
            "created_at": largest_order_row["created_at"],
            "label": f"{largest_order_amount:.2f}",
        }

    preferred_delivery = None
    latest_payment = None
    if latest_non_cancelled_order:
        preferred_delivery = (
            latest_non_cancelled_order["shipping_address"] or user.get("address")
        )
        latest_payment = latest_non_cancelled_order["payment_method"]
    else:
        preferred_delivery = user.get("address")

    largest_basket = _empty_largest_basket()
    if largest_basket_row and int(largest_basket_row["items_count"] or 0) > 0:
        items_count = int(largest_basket_row["items_count"] or 0)
        largest_basket = {
            "order_id": int(largest_basket_row["order_id"]),
            "items_count": items_count,
            "distinct_items": int(largest_basket_row["distinct_items"] or 0),
            "total_price": _format_price(largest_basket_row["total_price"]),
            "label": f"{items_count} item{'s' if items_count != 1 else ''}",
        }

    return {
        "user": user,
        "snapshot": {
            "preferred_delivery": preferred_delivery,
            "preferred_delivery_label": preferred_delivery or "N/A",
            "latest_payment": latest_payment,
            "latest_payment_label": latest_payment or "N/A",
            "largest_order": largest_order,
        },
        "metrics": {
            "total_orders": int(summary_row["total_orders"] or 0),
            "lifetime_spend": lifetime_spend,
            "average_order": average_order,
            "items_purchased": items_purchased,
        },
        "commerce_signals": {
            "delivered_orders": int(summary_row["delivered_orders"] or 0),
            "open_orders": int(summary_row["open_orders"] or 0),
            "largest_basket": largest_basket,
            "member_since": user["member_since_label"],
        },
        "latest_purchase": latest_purchase,
        "recent_orders": recent_orders,
        "latest_basket": latest_basket,
    }
