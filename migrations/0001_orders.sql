CREATE TABLE merchants (
    id           TEXT PRIMARY KEY,
    shop_domain  TEXT NOT NULL UNIQUE,
    plan         TEXT NOT NULL DEFAULT 'free',
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE orders (
    id           TEXT PRIMARY KEY,
    merchant_id  TEXT NOT NULL REFERENCES merchants(id),
    shopify_id   BIGINT NOT NULL,
    sku          TEXT NOT NULL,
    quantity     INT NOT NULL,
    weight_oz    NUMERIC(8, 2) NOT NULL,
    status       TEXT NOT NULL DEFAULT 'unfulfilled',
    created_at   TIMESTAMPTZ NOT NULL,
    UNIQUE (merchant_id, shopify_id)
);
CREATE INDEX orders_unfulfilled ON orders (merchant_id, created_at) WHERE status = 'unfulfilled';
