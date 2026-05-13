"""Stripe is the source of truth for which plan a merchant is on."""

HANDLED = {"customer.subscription.created", "customer.subscription.updated", "customer.subscription.deleted"}


def handle_event(event, merchants):
    if event["type"] not in HANDLED:
        return None
    subscription = event["data"]["object"]
    merchant = merchants.by_stripe_customer(subscription["customer"])
    plan = subscription["items"]["data"][0]["price"]["lookup_key"]
    if event["type"] == "customer.subscription.deleted":
        plan = "free"
    merchants.set_plan(merchant.id, plan)
    return plan
