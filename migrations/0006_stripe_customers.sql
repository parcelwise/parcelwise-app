ALTER TABLE merchants ADD COLUMN stripe_customer_id TEXT;
ALTER TABLE merchants ADD COLUMN labels_this_month INT NOT NULL DEFAULT 0;
