CREATE TABLE posted_charges (
    idempotency_key TEXT PRIMARY KEY,
    merchant_id TEXT NOT NULL REFERENCES merchants(id),
    feature TEXT NOT NULL,
    period TEXT NOT NULL,
    stripe_item_id TEXT NOT NULL,
    posted_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
