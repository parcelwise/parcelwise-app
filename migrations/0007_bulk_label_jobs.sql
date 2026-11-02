-- Bulk label buys run as jobs in Postgres, picked up by the label-worker service (Raven decision ceed75dcbb69).
CREATE TABLE bulk_label_jobs (
    id           BIGSERIAL PRIMARY KEY,
    merchant_id  TEXT NOT NULL REFERENCES merchants(id),
    status       TEXT NOT NULL DEFAULT 'queued',  -- queued, running, done
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    started_at   TIMESTAMPTZ,
    finished_at  TIMESTAMPTZ
);
CREATE INDEX bulk_label_jobs_queued ON bulk_label_jobs (created_at) WHERE status = 'queued';

-- One row per order the merchant confirmed, in the order shown.
CREATE TABLE bulk_label_job_items (
    job_id       BIGINT NOT NULL REFERENCES bulk_label_jobs(id),
    position     INT NOT NULL,
    order_id     TEXT NOT NULL REFERENCES orders(id),
    carrier      TEXT NOT NULL,
    service      TEXT NOT NULL,
    rate_id      TEXT NOT NULL,
    quoted_at    TIMESTAMPTZ NOT NULL,
    shown_price  NUMERIC(10, 2) NOT NULL,
    status       TEXT NOT NULL DEFAULT 'pending',  -- pending, bought, failed, needs_approval, already_labelled
    error        TEXT,
    label_id     BIGINT REFERENCES labels(id),
    PRIMARY KEY (job_id, position)
);
