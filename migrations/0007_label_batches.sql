-- Bulk label purchases run by the label-worker service (Postgres job table, no Redis; ADR 0001).
CREATE TABLE label_batches (
    id            BIGSERIAL PRIMARY KEY,
    merchant_id   TEXT NOT NULL REFERENCES merchants(id),
    status        TEXT NOT NULL DEFAULT 'queued',  -- queued, running, done
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    heartbeat_at  TIMESTAMPTZ,
    finished_at   TIMESTAMPTZ
);
CREATE INDEX label_batches_open ON label_batches (created_at) WHERE status <> 'done';

CREATE TABLE label_batch_items (
    batch_id         BIGINT NOT NULL REFERENCES label_batches(id),
    order_id         TEXT NOT NULL REFERENCES orders(id),
    position         INT NOT NULL,
    carrier          TEXT NOT NULL,
    service          TEXT NOT NULL,
    rate_id          TEXT NOT NULL,
    shown_price      NUMERIC(10, 2) NOT NULL,
    quoted_at        TIMESTAMPTZ NOT NULL,
    status           TEXT NOT NULL,
    tracking_number  TEXT,
    error            TEXT,
    PRIMARY KEY (batch_id, order_id)
);
