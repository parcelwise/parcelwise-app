import base64
import hashlib
import hmac

from app.shopify.webhooks import verify


def test_verify_accepts_valid_hmac():
    body, secret = b'{"id": 1}', "shh"
    good = base64.b64encode(hmac.new(secret.encode(), body, hashlib.sha256).digest()).decode()
    assert verify(body, good, secret)
    assert not verify(body, "bogus", secret)
