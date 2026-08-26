from app.shopify.install import APP_STORE, DIRECT, install_source


def test_app_store_installs_are_told_apart_from_our_signups():
    assert install_source({"source": "shopify_app_store", "shop": "bloom-and-co.myshopify.com"}) == APP_STORE
    assert install_source({"app_store_listing_id": "parcelwise-labels"}) == APP_STORE
    assert install_source({"shop": "bloom-and-co.myshopify.com", "email": "hello@bloom.example"}) == DIRECT
