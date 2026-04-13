import importlib
import os
import shutil
import sqlite3
import sys
import tempfile
import unittest
import uuid
from pathlib import Path


class SQLiteEndpointSmokeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.project_root = Path(__file__).resolve().parents[1]
        cls.temp_dir = tempfile.TemporaryDirectory(prefix="pomegrid-smoke-")
        cls.temp_db = Path(cls.temp_dir.name) / "pomegrid.db"

        source_db = cls.project_root / "instance" / "pomegrid.db"
        if source_db.exists():
            shutil.copy2(source_db, cls.temp_db)
        else:
            cls.temp_db.touch()

        os.environ["REDIS_ENABLED"] = "0"
        os.environ["AUTH_EXPOSE_VERIFICATION_CODE"] = "1"

        sys.modules.pop("app", None)

        import database
        import database.connection as connection

        connection.DB_PATH = cls.temp_db
        database.DB_PATH = cls.temp_db

        cls.app_module = importlib.import_module("app")
        cls.app = cls.app_module.app
        cls.app.config.update(TESTING=True, REDIS_ENABLED=False)
        cls.client = cls.app.test_client()
        cls._cached_auth_headers = None

    @classmethod
    def tearDownClass(cls):
        cls.temp_dir.cleanup()

    @classmethod
    def _db_row(cls, query, params=()):
        conn = sqlite3.connect(cls.temp_db)
        conn.row_factory = sqlite3.Row
        try:
            cursor = conn.cursor()
            cursor.execute(query, params)
            return cursor.fetchone()
        finally:
            conn.close()

    @classmethod
    def _sample_id(cls, table_name, where_sql=None, params=()):
        query = f"SELECT id FROM {table_name}"
        if where_sql:
            query += f" WHERE {where_sql}"
        query += " ORDER BY id ASC LIMIT 1"
        row = cls._db_row(query, params)
        return int(row["id"]) if row else None

    def _auth_headers(self):
        cached_headers = self.__class__._cached_auth_headers
        if cached_headers is not None:
            return dict(cached_headers)

        suffix = uuid.uuid4().hex[:10]
        password = "SmokePass123!"
        email = f"smoke-{suffix}@example.com"
        registration_payload = {
            "username": f"smoke_{suffix}",
            "password": password,
            "email": email,
            "full_name": "SQLite Smoke User",
            "phone": f"233555{suffix[:4]}",
            "user_type": "user",
            "date_of_birth": "1998-01-15",
            "accept_policy": True,
        }

        register_response = self.client.post(
            "/api/v1/auth/register",
            json=registration_payload,
        )
        self.assertEqual(register_response.status_code, 201, register_response.get_data(as_text=True))

        login_response = self.client.post(
            "/api/v1/auth/login",
            json={"email": email, "password": password},
        )
        self.assertEqual(login_response.status_code, 200, login_response.get_data(as_text=True))

        login_payload = login_response.get_json() or {}
        token = (((login_payload.get("data") or {}).get("access_token")) or "").strip()
        self.assertTrue(token, "Login did not return an access token")

        headers = {"Authorization": f"Bearer {token}"}
        self.__class__._cached_auth_headers = dict(headers)
        return headers

    def test_public_collection_endpoints_do_not_500(self):
        paths = (
            "/",
            "/api/v1",
            "/api/v1/products",
            "/api/v1/products/featured",
            "/api/v1/categories",
            "/api/v1/services",
            "/api/v1/workers/",
            "/api/v1/connect/partners",
        )

        for path in paths:
            with self.subTest(path=path):
                response = self.client.get(path)
                self.assertLess(
                    response.status_code,
                    500,
                    f"{path} returned {response.status_code}: {response.get_data(as_text=True)}",
                )

    def test_public_detail_endpoints_succeed_when_sample_data_exists(self):
        samples = (
            ("Categories", "id IS NOT NULL", "/api/v1/categories/{id}"),
            ("Products", "COALESCE(is_active, 1) = 1", "/api/v1/products/{id}"),
            ("farm_services", "COALESCE(is_active, 1) = 1", "/api/v1/services/{id}"),
            ("Workers", "id IS NOT NULL", "/api/v1/workers/{id}"),
        )

        for table_name, where_sql, path_template in samples:
            sample_id = self._sample_id(table_name, where_sql)
            if sample_id is None:
                continue

            path = path_template.format(id=sample_id)
            with self.subTest(path=path):
                response = self.client.get(path)
                self.assertEqual(
                    response.status_code,
                    200,
                    f"{path} returned {response.status_code}: {response.get_data(as_text=True)}",
                )

        product_id = self._sample_id("Products", "COALESCE(is_active, 1) = 1")
        if product_id is not None:
            response = self.client.get(f"/api/v1/products/{product_id}/feedback")
            self.assertEqual(
                response.status_code,
                200,
                response.get_data(as_text=True),
            )

    def test_protected_endpoints_reject_anonymous_without_500(self):
        paths = (
            "/api/v1/auth/me",
            "/api/v1/users/me",
            "/api/v1/payments",
            "/api/v1/orders/get-user-orders",
            "/api/v1/connect/",
        )
        allowed_statuses = {401, 403, 422}
        anonymous_client = self.app.test_client()

        for path in paths:
            with self.subTest(path=path):
                response = anonymous_client.get(path)
                self.assertIn(
                    response.status_code,
                    allowed_statuses,
                    f"{path} returned {response.status_code}: {response.get_data(as_text=True)}",
                )

    def test_auth_register_login_and_current_user_endpoints(self):
        headers = self._auth_headers()

        auth_me_response = self.client.get("/api/v1/auth/me", headers=headers)
        self.assertEqual(auth_me_response.status_code, 200, auth_me_response.get_data(as_text=True))
        auth_me_payload = auth_me_response.get_json() or {}
        self.assertIn("data", auth_me_payload)
        self.assertIn("email", auth_me_payload["data"])

        user_me_response = self.client.get("/api/v1/users/me", headers=headers)
        self.assertEqual(user_me_response.status_code, 200, user_me_response.get_data(as_text=True))
        user_me_payload = user_me_response.get_json() or {}
        self.assertTrue((user_me_payload.get("data") or {}).get("email"))

    def test_authenticated_feedback_submission_when_product_exists(self):
        product_id = self._sample_id("Products", "COALESCE(is_active, 1) = 1")
        if product_id is None:
            self.skipTest("No active product exists in the SQLite baseline database")

        headers = self._auth_headers()
        response = self.client.post(
            f"/api/v1/products/{product_id}/feedback",
            headers=headers,
            json={"rating": 5, "feedback": "Smoke test feedback"},
        )
        self.assertIn(
            response.status_code,
            {200, 201},
            response.get_data(as_text=True),
        )

    def test_authenticated_settings_endpoints_support_full_settings_flow(self):
        headers = self._auth_headers()

        settings_response = self.client.get("/api/v1/settings", headers=headers)
        self.assertEqual(settings_response.status_code, 200, settings_response.get_data(as_text=True))
        settings_payload = settings_response.get_json() or {}
        self.assertIn("profile", settings_payload.get("data") or {})
        self.assertIn("notifications", settings_payload.get("data") or {})
        self.assertIn("paymentMethods", settings_payload.get("data") or {})
        self.assertIn("billing", settings_payload.get("data") or {})

        profile_response = self.client.patch(
            "/api/v1/settings/profile",
            headers=headers,
            json={
                "firstName": "Smoke",
                "lastName": "Tester",
                "email": "smoke-settings@example.com",
                "phone": "2335551212",
                "bio": "Updated from settings smoke test",
            },
        )
        self.assertEqual(profile_response.status_code, 200, profile_response.get_data(as_text=True))
        profile_payload = profile_response.get_json() or {}
        self.assertEqual((profile_payload.get("data") or {}).get("firstName"), "Smoke")
        self.assertEqual((profile_payload.get("data") or {}).get("lastName"), "Tester")

        avatar_response = self.client.post(
            "/api/v1/settings/profile/avatar",
            headers=headers,
            json={
                "avatarUrl": "https://res.cloudinary.com/demo/image/upload/v1/profile/images/avatar-test.png"
            },
        )
        self.assertEqual(avatar_response.status_code, 200, avatar_response.get_data(as_text=True))
        avatar_payload = avatar_response.get_json() or {}
        self.assertIn(
            "profile/images/avatar-test.png",
            ((avatar_payload.get("data") or {}).get("avatarUrl") or ""),
        )

        notifications_response = self.client.patch(
            "/api/v1/settings/notifications",
            headers=headers,
            json={"settings": {"marketing_emails": True, "security_alerts": False}},
        )
        self.assertEqual(notifications_response.status_code, 200, notifications_response.get_data(as_text=True))
        notifications_payload = notifications_response.get_json() or {}
        groups = ((notifications_payload.get("data") or {}).get("groups")) or []
        flattened_settings = {
            setting["id"]: setting["enabled"]
            for group in groups
            for setting in group.get("settings", [])
        }
        self.assertTrue(flattened_settings.get("marketing_emails"))
        self.assertFalse(flattened_settings.get("security_alerts"))

        reset_notifications_response = self.client.post(
            "/api/v1/settings/notifications/reset",
            headers=headers,
        )
        self.assertEqual(
            reset_notifications_response.status_code,
            200,
            reset_notifications_response.get_data(as_text=True),
        )

        add_payment_method_response = self.client.post(
            "/api/v1/settings/payments/methods",
            headers=headers,
            json={
                "name": "Smoke Tester",
                "number": "4242 4242 4242 4242",
                "expiry": "12/99",
                "cvc": "123",
            },
        )
        self.assertEqual(
            add_payment_method_response.status_code,
            201,
            add_payment_method_response.get_data(as_text=True),
        )
        added_method_payload = add_payment_method_response.get_json() or {}
        added_method = added_method_payload.get("data") or {}
        method_id = added_method.get("id")
        self.assertTrue(method_id)

        payment_methods_response = self.client.get(
            "/api/v1/settings/payments/methods",
            headers=headers,
        )
        self.assertEqual(
            payment_methods_response.status_code,
            200,
            payment_methods_response.get_data(as_text=True),
        )
        self.assertGreaterEqual(len((payment_methods_response.get_json() or {}).get("data") or []), 1)

        billing_response = self.client.put(
            "/api/v1/settings/payments/billing",
            headers=headers,
            json={
                "street": "12 Water Lane",
                "city": "Accra",
                "state": "Greater Accra",
                "zip": "00233",
                "country": "Ghana",
            },
        )
        self.assertEqual(billing_response.status_code, 200, billing_response.get_data(as_text=True))
        billing_payload = billing_response.get_json() or {}
        self.assertEqual((billing_payload.get("data") or {}).get("city"), "Accra")

        password_response = self.client.patch(
            "/api/v1/settings/profile/password",
            headers=headers,
            json={
                "currentPassword": "SmokePass123!",
                "newPassword": "SmokePass456!",
                "confirmPassword": "SmokePass456!",
            },
        )
        self.assertEqual(password_response.status_code, 200, password_response.get_data(as_text=True))

        delete_payment_method_response = self.client.delete(
            f"/api/v1/settings/payments/methods/{method_id}",
            headers=headers,
        )
        self.assertEqual(
            delete_payment_method_response.status_code,
            200,
            delete_payment_method_response.get_data(as_text=True),
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)
