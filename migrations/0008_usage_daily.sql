CREATE TABLE usage_daily (
    day DATE NOT NULL,
    merchant_id TEXT NOT NULL REFERENCES merchants(id),
    feature TEXT NOT NULL,
    count INT NOT NULL DEFAULT 0,
    PRIMARY KEY (day, merchant_id, feature)
);
