import math


DEFAULT_PAGE = 1
DEFAULT_PER_PAGE = 20
MAX_PER_PAGE = 100


def envelope(data=None, message="OK", status=200, success=None, meta=None):
    if success is None:
        success = 200 <= int(status) < 400
    payload = {
        "success": bool(success),
        "data": data,
        "message": message,
        "status": int(status),
    }
    if meta is not None:
        payload["meta"] = meta
    return payload


def parse_pagination(args):
    try:
        page = int(args.get("page", DEFAULT_PAGE))
    except (TypeError, ValueError):
        page = DEFAULT_PAGE
    try:
        per_page = int(args.get("per_page", DEFAULT_PER_PAGE))
    except (TypeError, ValueError):
        per_page = DEFAULT_PER_PAGE

    if page < 1:
        page = DEFAULT_PAGE
    if per_page < 1:
        per_page = DEFAULT_PER_PAGE
    if per_page > MAX_PER_PAGE:
        per_page = MAX_PER_PAGE

    offset = (page - 1) * per_page
    return page, per_page, offset


def build_meta(page, per_page, total):
    total_value = int(total or 0)
    pages = math.ceil(total_value / per_page) if per_page > 0 else 0
    return {
        "page": int(page),
        "per_page": int(per_page),
        "total": total_value,
        "pages": int(pages),
    }
