import unittest

from routes.food_trade.products import normalize_product_image_payload


class NormalizeProductImagePayloadTests(unittest.TestCase):
    def test_accepts_single_image_payload(self):
        payload = {"image_url": "https://cdn.example.com/a.jpg"}
        self.assertEqual(
            normalize_product_image_payload(payload),
            [{"image_url": "https://cdn.example.com/a.jpg", "sort_order": 0, "is_primary": False}],
        )

    def test_accepts_multiple_image_payload(self):
        payload = {
            "images": [
                {"image_url": "https://cdn.example.com/1.jpg", "sort_order": 2, "is_primary": True},
                {"image_url": "https://cdn.example.com/2.jpg"},
            ]
        }
        self.assertEqual(
            normalize_product_image_payload(payload),
            [
                {"image_url": "https://cdn.example.com/1.jpg", "sort_order": 2, "is_primary": True},
                {"image_url": "https://cdn.example.com/2.jpg", "sort_order": 0, "is_primary": False},
            ],
        )


if __name__ == "__main__":
    unittest.main()
