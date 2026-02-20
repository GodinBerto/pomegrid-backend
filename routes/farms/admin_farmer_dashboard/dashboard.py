def percent_change(current_value, previous_value):
    current = float(current_value or 0)
    previous = float(previous_value or 0)
    if previous == 0:
        return 100.0 if current > 0 else 0.0
    return round(((current - previous) / previous) * 100, 1)


def trend_state(change_percent, period_label="from last month"):
    change = round(float(change_percent or 0), 1)
    if change > 0:
        direction = "up"
    elif change < 0:
        direction = "down"
    else:
        direction = "flat"
    return {
        "changePercent": change,
        "direction": direction,
        "periodLabel": period_label,
    }


def build_dashboard_states(
    total_revenue,
    revenue_change_percent,
    total_orders,
    orders_change_percent,
    total_products,
    total_customers,
    customers_change_percent,
):
    revenue_value = round(float(total_revenue or 0), 2)
    return {
        "totalRevenue": {
            "title": "Total Revenue",
            "value": revenue_value,
            "formatted": f"${revenue_value:,.2f}",
            **trend_state(revenue_change_percent),
        },
        "orders": {
            "title": "Orders",
            "value": int(total_orders or 0),
            **trend_state(orders_change_percent),
        },
        "products": {
            "title": "Products",
            "value": int(total_products or 0),
        },
        "customers": {
            "title": "Customers",
            "value": int(total_customers or 0),
            **trend_state(customers_change_percent),
        },
    }


FARMER_ADMIN_DASHBOARD_IMAGE_STATE = {
    "totalRevenue": {
        "title": "Total Revenue",
        "value": 24356.00,
        "formatted": "$24,356.00",
        "changePercent": 12.3,
        "direction": "up",
        "periodLabel": "from last month",
    },
    "orders": {
        "title": "Orders",
        "value": 142,
        "changePercent": -2.5,
        "direction": "down",
        "periodLabel": "from last month",
    },
    "products": {
        "title": "Products",
        "value": 35,
    },
    "customers": {
        "title": "Customers",
        "value": 89,
        "changePercent": 8.1,
        "direction": "up",
        "periodLabel": "from last month",
    },
}
