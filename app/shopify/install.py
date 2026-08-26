"""Where a merchant came from. Shopify's App Store brings its own billing expectations; our own signups pay
through Stripe. Recorded on the merchant at install so the two can be told apart (merchants.install_source)."""

APP_STORE = "app_store"
DIRECT = "direct"


def install_source(install: dict) -> str:
    """`install` is the payload of Shopify's app/installed hook, or our own signup form."""
    if install.get("source") == "shopify_app_store" or install.get("app_store_listing_id"):
        return APP_STORE
    return DIRECT
