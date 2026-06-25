"""Customer emails sent on the merchant's behalf through Postmark."""

TEMPLATES = {"shipped": "shipping-confirmation-v2", "delivered": "delivered-v1"}


def shipping_confirmation(order, label) -> dict:
    return {
        "TemplateAlias": TEMPLATES["shipped"],
        "To": order.customer_email,
        "TemplateModel": {"order": order.id, "tracking": label.tracking_number, "carrier": label.carrier.upper()},
    }
