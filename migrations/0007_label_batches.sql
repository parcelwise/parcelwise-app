CREATE TABLE label_batches (
    id           TEXT PRIMARY KEY,
    merchant_id  TEXT NOT NULL REFERENCES merchants(id),
    status       TEXT NOT NULL DEFAULT 'queued',
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    started_at   TIMESTAMPTZ,
    finished_at  TIMESTAMPTZ
);
-- One running batch per merchant keeps a merchant's carrier account under its rate cap (ADR 0005).
CREATE UNIQUE INDEX label_batches_one_running ON label_batches (merchant_id) WHERE status = 'running';
CREATE INDEX label_batches_queued ON label_batches (created_at) WHERE status = 'queued';

CREATE TABLE label_batch_items (
    batch_id         TEXT NOT NULL REFERENCES label_batches(id),
    position         INT NOT NULL,
    order_id         TEXT NOT NULL REFERENCES orders(id),
    carrier          TEXT NOT NULL,
    service          TEXT NOT NULL,
    rate_id          TEXT NOT NULL,
    price            NUMERIC(10, 2) NOT NULL,
    quoted_at        TIMESTAMPTZ NOT NULL,
    shown_price      NUMERIC(10, 2) NOT NULL,
    status           TEXT NOT NULL DEFAULT 'pending',
    tracking_number  TEXT,
    error            TEXT,
    PRIMARY KEY (batch_id, order_id)
);
