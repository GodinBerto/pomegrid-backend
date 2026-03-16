import json
import logging

from flask import Blueprint, jsonify, request

from database import db_connection
from decorators.roles import admin_required
from extensions.redis_client import get_redis_client


farm_services = Blueprint("farm_services", __name__)
logger = logging.getLogger(__name__)

ALLOWED_ICONS = {"users", "settings", "graduationCap", "wrench"}
PRICE_TIERS = ("basic", "premium", "enterprise")
FARM_SERVICES_LIST_CACHE_KEY = "farms:services:list"


def _cache_get(key):
    try:
        redis_client = get_redis_client()
        payload = redis_client.get(key)
        return json.loads(payload) if payload else None
    except Exception as e:
        logger.warning("Redis unavailable, skipping farm services cache read: %s", e)
        return None


def _cache_set(key, value, ttl=120):
    try:
        redis_client = get_redis_client()
        redis_client.setex(key, ttl, json.dumps(value))
    except Exception as e:
        logger.warning("Redis unavailable, skipping farm services cache write: %s", e)


def _cache_delete(*keys):
    if not keys:
        return
    try:
        redis_client = get_redis_client()
        redis_client.delete(*keys)
    except Exception as e:
        logger.warning("Redis unavailable, skipping farm services cache delete: %s", e)


def _default_pricing():
    return {
        "basic": {"price": 0, "duration": ""},
        "premium": {"price": 0, "duration": ""},
        "enterprise": {"price": 0, "duration": ""},
    }


def _serialize_farm_service(row):
    features = []
    pricing = _default_pricing()

    if row["features_json"]:
        try:
            decoded_features = json.loads(row["features_json"])
            if isinstance(decoded_features, list):
                features = [str(item).strip() for item in decoded_features if str(item).strip()]
        except (TypeError, ValueError, json.JSONDecodeError):
            features = []

    if row["pricing_json"]:
        try:
            decoded_pricing = json.loads(row["pricing_json"])
            if isinstance(decoded_pricing, dict):
                normalized_pricing = _default_pricing()
                for tier in PRICE_TIERS:
                    tier_value = decoded_pricing.get(tier) or {}
                    normalized_pricing[tier] = {
                        "price": int(tier_value.get("price") or 0),
                        "duration": str(tier_value.get("duration") or "").strip(),
                    }
                pricing = normalized_pricing
        except (TypeError, ValueError, json.JSONDecodeError):
            pricing = _default_pricing()

    return {
        "title": str(row["title"] or "").strip(),
        "description": str(row["description"] or "").strip(),
        "icon": str(row["icon"] or "").strip(),
        "features": features,
        "pricing": pricing,
    }


def _validate_service_payload(data):
    title = str(data.get("title") or "").strip()
    description = str(data.get("description") or "").strip()
    icon = str(data.get("icon") or "").strip()
    raw_features = data.get("features")
    raw_pricing = data.get("pricing")

    if not title:
        return None, "title is required"
    if not description:
        return None, "description is required"
    if icon not in ALLOWED_ICONS:
        return None, "icon must be one of users|settings|graduationCap|wrench"

    if not isinstance(raw_features, list):
        return None, "features must be an array"
    features = [str(item).strip() for item in raw_features if str(item).strip()]
    if len(features) < 4 or len(features) > 6:
        return None, "features must contain 4 to 6 items"

    if not isinstance(raw_pricing, dict):
        return None, "pricing is required"

    pricing = {}
    for tier in PRICE_TIERS:
        tier_value = raw_pricing.get(tier)
        if not isinstance(tier_value, dict):
            return None, f"pricing.{tier} is required"
        duration = str(tier_value.get("duration") or "").strip()
        if not duration:
            return None, f"pricing.{tier}.duration is required"
        try:
            price = int(float(tier_value.get("price")))
        except (TypeError, ValueError):
            return None, f"pricing.{tier}.price must be a number"
        if price < 0:
            return None, f"pricing.{tier}.price must be non-negative"
        pricing[tier] = {"price": price, "duration": duration}

    return {
        "title": title,
        "description": description,
        "icon": icon,
        "features": features,
        "pricing": pricing,
    }, None


@farm_services.route("", methods=["GET"])
@farm_services.route("/", methods=["GET"])
def list_farm_services():
    cached = _cache_get(FARM_SERVICES_LIST_CACHE_KEY)
    if cached is not None:
        return jsonify(cached), 200

    try:
        conn, cursor = db_connection()
        cursor.execute(
            """
            SELECT title, description, icon, features_json, pricing_json
            FROM farm_services
            WHERE COALESCE(is_active, 1) = 1
            ORDER BY sort_order ASC, id ASC
            """
        )
        rows = cursor.fetchall()
        conn.close()
        payload = [_serialize_farm_service(row) for row in rows]
        _cache_set(FARM_SERVICES_LIST_CACHE_KEY, payload)
        return jsonify(payload), 200
    except Exception:
        logger.exception("Failed to list farm services")
        return jsonify([]), 500


@farm_services.route("", methods=["POST"])
@farm_services.route("/", methods=["POST"])
@admin_required
def create_farm_service():
    payload, error = _validate_service_payload(request.get_json() or {})
    if error:
        return jsonify({"message": error}), 400

    try:
        conn, cursor = db_connection()
        cursor.execute("SELECT COALESCE(MAX(sort_order), 0) + 1 AS next_sort_order FROM farm_services")
        sort_order = int(cursor.fetchone()["next_sort_order"] or 1)
        cursor.execute(
            """
            INSERT INTO farm_services (
                title,
                description,
                icon,
                features_json,
                pricing_json,
                sort_order,
                is_active
            )
            VALUES (?, ?, ?, ?, ?, ?, 1)
            """,
            (
                payload["title"],
                payload["description"],
                payload["icon"],
                json.dumps(payload["features"]),
                json.dumps(payload["pricing"]),
                sort_order,
            ),
        )
        conn.commit()
        conn.close()
        _cache_delete(FARM_SERVICES_LIST_CACHE_KEY)
        return jsonify(payload), 201
    except Exception as exc:
        logger.exception("Failed to create farm service")
        message = "title already exists" if "unique" in str(exc).lower() else "failed to create service"
        return jsonify({"message": message}), 400
