# Changelog

## Unreleased

- Assistant usage metered on Starter and Growth: 200 and 1,000 answers a month included, then $0.04 an answer, on the
  next invoice from December 2026 usage. Billed on completed answers, not attempts. Posts nothing until every
  billing input is decided; App Store installs are not charged through Stripe.
- Plan page shows assistant answers against the allowance, with the per-answer price.

## 0.34.0 (2026-10-21)

- The Parcelwise Assistant answers questions about orders, labels and the plan; Starter and Growth (#49, #55, #62)
- Usage counted in `usage_events`, read from `usage_daily` (#71, #96)
- Extra labels past the Starter allowance charged per label on the next invoice (#113, #124)
- Every charge idempotent (#140); charges posted in batches (#148)
- Assistant retries a timeout once (#216); labels and answers this month on the Plan page (#220)

## 0.31.0 (2026-09-30)

- Order search by SKU or customer name (#198)
- Every label purchase goes through `purchase_label()` (#212)

## 0.24.0 (2026-07-21)

- Letter-size label sheets (#131)
- Package presets (#118)

## 0.18.0 (2026-06-06)

- Refuse purchases at stale or changed prices (#94)

## 0.1.0 (2026-03-02)

- First release: USPS labels for one shop
