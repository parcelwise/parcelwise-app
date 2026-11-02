# Changelog

## Unreleased

- Bulk label buying for merchants with `bulk_labels_enabled` (Bloom & Co first): select up to 200 orders on the Orders page and a background worker buys them serially, 40 a minute, skipping and reporting orders that already have a label or whose price changed

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
