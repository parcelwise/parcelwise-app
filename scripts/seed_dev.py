"""Seed a local database with one fake shop and a morning's worth of orders."""

import random

SKUS = ["CANDLE-8OZ", "CANDLE-12OZ", "SOAP-BAR", "GIFT-BOX"]


def fake_orders(n: int = 40):
    rng = random.Random(7)
    for i in range(n):
        yield {
            "shopify_id": 5_100_000 + i,
            "sku": rng.choice(SKUS),
            "quantity": rng.randint(1, 3),
            "weight_oz": rng.choice([6, 10, 14, 22]),
        }
