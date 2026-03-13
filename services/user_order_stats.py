def get_user_order_stats_map(cursor, user_ids):
    normalized_ids = []
    seen = set()
    for user_id in user_ids or []:
        try:
            normalized = int(user_id)
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
            user_id,
            COUNT(*) AS orders,
            COALESCE(
                SUM(
                    CASE
                        WHEN LOWER(COALESCE(status, '')) IN ('pending', 'completed') THEN total_price
                        ELSE 0
                    END
                ),
                0
            ) AS amount_spent
        FROM Orders
        WHERE user_id IN ({placeholders})
        GROUP BY user_id
        """,
        tuple(normalized_ids),
    )

    stats_map = {}
    for row in cursor.fetchall():
        stats_map[int(row["user_id"])] = {
            "orders": int(row["orders"] or 0),
            "amount_spent": round(float(row["amount_spent"] or 0), 2),
        }
    return stats_map
