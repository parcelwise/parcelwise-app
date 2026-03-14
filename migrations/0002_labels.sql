CREATE TABLE labels (
    id               BIGSERIAL PRIMARY KEY,
    order_id         TEXT NOT NULL REFERENCES orders(id),
    carrier          TEXT NOT NULL,
    tracking_number  TEXT NOT NULL,
    price            NUMERIC(10, 2) NOT NULL,
    pdf_url          TEXT NOT NULL,
    idempotency_key  TEXT NOT NULL UNIQUE,
    created_at       TIMESTAMPTZ NOT NULL DEFAULT now()
);
