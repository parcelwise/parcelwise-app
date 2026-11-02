-- Bulk label buying (Raven task 051ffb8e9c2d). A background worker claims pending batches from this table.
ALTER TABLE merchants ADD COLUMN bulk_labels_enabled BOOLEAN NOT NULL DEFAULT false;

CREATE TABLE label_batches (
    id           BIGSERIAL PRIMARY KEY,
    merchant_id  TEXT NOT NULL REFERENCES merchants(id),
    status       TEXT NOT NULL DEFAULT 'pending',
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    started_at   TIMESTAMPTZ,
    finished_at  TIMESTAMPTZ
);
CREATE INDEX label_batches_open ON label_batches (created_at) WHERE status IN ('pending', 'running');

-- One row per selected order, holding the exact rate and price the merchant saw and approved.
CREATE TABLE label_batch_items (
    batch_id         BIGINT NOT NULL REFERENCES label_batches(id),
    order_id         TEXT NOT NULL REFERENCES orders(id),
    position         INT NOT NULL,
    carrier          TEXT NOT NULL,
    service          TEXT NOT NULL,
    rate_id          TEXT NOT NULL,
    price            NUMERIC(10, 2) NOT NULL,
    quoted_at        TIMESTAMPTZ NOT NULL,
    status           TEXT NOT NULL DEFAULT 'pending',
    reason           TEXT NOT NULL DEFAULT '',
    tracking_number  TEXT NOT NULL DEFAULT '',
    PRIMARY KEY (batch_id, order_id)
);
