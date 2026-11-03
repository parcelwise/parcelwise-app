-- Bulk label buys run in the background (Raven decision 5e5e0741c202, Ana Ruiz). The row id is the batch id that
-- goes into every label's idempotency key, so re-running a job never buys twice.
CREATE TABLE bulk_label_jobs (
    id           TEXT PRIMARY KEY,
    merchant_id  TEXT NOT NULL REFERENCES merchants(id),
    status       TEXT NOT NULL DEFAULT 'pending' CHECK (status IN ('pending', 'done', 'refused')),
    lines        JSONB NOT NULL,
    outcomes     JSONB,
    reason       TEXT NOT NULL DEFAULT '',
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    finished_at  TIMESTAMPTZ
);

-- One bulk buy per merchant at a time; a second one is refused (Raven decision af32723a4431, Ana Ruiz).
CREATE UNIQUE INDEX bulk_label_jobs_one_pending ON bulk_label_jobs (merchant_id) WHERE status = 'pending';
CREATE INDEX bulk_label_jobs_latest ON bulk_label_jobs (merchant_id, created_at DESC);
