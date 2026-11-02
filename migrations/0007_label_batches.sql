-- Buying labels for many orders at once. A batch is a job; the label-worker service works through its items.
-- Postgres, not a queue service (ADR 0001; Marcus Lee, Raven decision a6f8e89cd82c).
CREATE TABLE label_batches (
    id           TEXT PRIMARY KEY,
    merchant_id  TEXT NOT NULL REFERENCES merchants(id),
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE label_batch_items (
    batch_id         TEXT NOT NULL REFERENCES label_batches(id),
    order_id         TEXT NOT NULL REFERENCES orders(id),
    merchant_id      TEXT NOT NULL REFERENCES merchants(id),
    -- queued | bought | already_labeled | needs_requote | failed | no_longer_unfulfilled
    status           TEXT NOT NULL DEFAULT 'queued',
    carrier          TEXT NOT NULL,
    service          TEXT NOT NULL,
    rate_id          TEXT NOT NULL,
    rate_price       NUMERIC(10, 2) NOT NULL,
    quoted_at        TIMESTAMPTZ NOT NULL,
    -- The price the merchant saw and approved for this order.
    shown_price      NUMERIC(10, 2) NOT NULL,
    tracking_number  TEXT,
    error            TEXT,
    -- Finished purchase attempts; the idempotency key uses attempts + 1. A carrier timeout doesn't count.
    attempts         INT NOT NULL DEFAULT 0,
    -- The last attempt timed out at the carrier: a retry keeps this rate and price, and the same key.
    timed_out        BOOLEAN NOT NULL DEFAULT false,
    updated_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (batch_id, order_id)
);
CREATE INDEX label_batch_items_queued ON label_batch_items (updated_at) WHERE status = 'queued';
CREATE INDEX label_batch_items_merchant_queued ON label_batch_items (merchant_id) WHERE status = 'queued';
