"""Only purchase_label() may call a carrier's buy(). Retries without its idempotency key double-bought labels."""

from pathlib import Path

APP = Path(__file__).resolve().parents[1] / "app"
ALLOWED = {APP / "labels" / "purchase.py", APP / "labels" / "carriers.py"}


def test_only_purchase_label_buys():
    offenders = [str(p.relative_to(APP)) for p in APP.rglob("*.py") if p not in ALLOWED and ".buy(" in p.read_text()]
    assert offenders == []
