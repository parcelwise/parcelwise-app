CREATE TABLE usage_events (
    id BIGSERIAL PRIMARY KEY,
    merchant_id TEXT NOT NULL REFERENCES merchants(id),
    feature TEXT NOT NULL,
    request_id TEXT NOT NULL,
    at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX usage_events_merchant_feature_at ON usage_events (merchant_id, feature, at);
