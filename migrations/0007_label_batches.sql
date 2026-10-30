-- Bulk label purchases from the Orders page. A worker buys each item through purchase_label() (ADR 0005).
CREATE TABLE label_batches (
    id            BIGSERIAL PRIMARY KEY,
    merchant_id   TEXT NOT NULL REFERENCES merchants(id),
    status        TEXT NOT NULL DEFAULT 'queued',  -- queued, running, done
    heartbeat_at  TIMESTAMPTZ,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);
-- One running batch per merchant, so the per-account USPS rate cap holds however many workers run.
CREATE UNIQUE INDEX label_batches_one_running ON label_batches (merchant_id) WHERE status = 'running';
CREATE INDEX label_batches_queued ON label_batches (created_at) WHERE status = 'queued';

CREATE TABLE label_batch_items (
    batch_id         BIGINT NOT NULL REFERENCES label_batches(id),
    position         INT NOT NULL,  -- the order the merchant saw them in; bought top to bottom
    order_id         TEXT NOT NULL REFERENCES orders(id),
    carrier          TEXT NOT NULL,
    service          TEXT NOT NULL,
    rate_id          TEXT NOT NULL,
    price            NUMERIC(10, 2) NOT NULL,  -- our quote
    quoted_at        TIMESTAMPTZ NOT NULL,
    shown_price      NUMERIC(10, 2) NOT NULL,  -- what the merchant confirmed
    attempt          INT NOT NULL DEFAULT 1,
    status           TEXT NOT NULL DEFAULT 'queued',  -- queued, bought, stale, failed
    sent_to_carrier  BOOLEAN NOT NULL DEFAULT false,
    tracking_number  TEXT,
    pdf_url          TEXT,
    error            TEXT,
    PRIMARY KEY (batch_id, order_id)
);
