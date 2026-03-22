import logging
from datetime import datetime

from flask import Blueprint, g

from decorators.roles import ROLE_ADMIN, ROLE_USER, ROLE_WORKER
from routes.middleware import protect_blueprint


connect_api = Blueprint("connect_api", __name__)
protect_blueprint(
    connect_api,
    ROLE_USER,
    ROLE_WORKER,
    ROLE_ADMIN,
    exempt_endpoints={"list_connect_partners"},
)

logger = logging.getLogger(__name__)

CONNECT_ACCOUNT_TYPES = {"farmer", "importer"}
MONTH_SERIES_COUNT = 6


def _current_user_id():
    return int(g.current_user["id"])


def _normalize_account_type(value):
    normalized = str(value or "").strip().lower()
    return normalized if normalized in CONNECT_ACCOUNT_TYPES else None


def _safe_text(value):
    return str(value or "").strip()


def _parse_datetime(value):
    raw = _safe_text(value)
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
        ):
            try:
                return datetime.strptime(raw, fmt)
            except ValueError:
                continue
    return None


def _format_date(value):
    parsed = _parse_datetime(value)
    if not parsed:
        return _safe_text(value)
    return parsed.strftime("%b %d, %Y")


def _month_key(value):
    parsed = _parse_datetime(value)
    if not parsed:
        return None
    return f"{parsed.year:04d}-{parsed.month:02d}"


def _month_series(count=MONTH_SERIES_COUNT):
    now = datetime.utcnow()
    current_index = now.year * 12 + (now.month - 1)
    months = []
    for offset in range(count - 1, -1, -1):
        index = current_index - offset
        year = index // 12
        month = (index % 12) + 1
        dt_obj = datetime(year, month, 1)
        months.append(
            {
                "key": f"{year:04d}-{month:02d}",
                "label": dt_obj.strftime("%b"),
                "start": dt_obj.strftime("%Y-%m-%d 00:00:00"),
            }
        )
    return months


def _current_previous_month_bounds():
    months = _month_series(2)
    return months[1]["start"], months[0]["start"]


def _direction_for_change(value):
    numeric = float(value or 0)
    if numeric > 0:
        return "up"
    if numeric < 0:
        return "down"
    return "flat"


def _format_signed_count(value):
    numeric = int(value or 0)
    if numeric > 0:
        return f"+{numeric}"
    if numeric < 0:
        return str(numeric)
    return "0"


def _format_signed_percent(value):
    numeric = round(float(value or 0), 1)
    if numeric > 0:
        return f"+{numeric:g}%"
    if numeric < 0:
        return f"{numeric:g}%"
    return "0%"


def _percent_change(current_value, previous_value):
    current = float(current_value or 0)
    previous = float(previous_value or 0)
    if previous == 0:
        return 100.0 if current > 0 else 0.0
    return round(((current - previous) / previous) * 100, 1)


def _format_currency(value):
    return f"${float(value or 0):,.2f}"
