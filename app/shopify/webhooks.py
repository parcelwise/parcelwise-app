"""Shopify webhooks. Verified by HMAC before anything else runs."""

import base64
import hashlib
import hmac


def verify(body: bytes, header_hmac: str, secret: str) -> bool:
    digest = hmac.new(secret.encode(), body, hashlib.sha256).digest()
    return hmac.compare_digest(base64.b64encode(digest).decode(), header_hmac)


TOPICS = {"orders/create", "orders/cancelled"}
