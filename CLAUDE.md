# Parcelwise

Notes for coding agents working in this repo.

## Raven

We use Raven (the `raven` MCP server) so a coding agent asks the person who owns a judgment call instead of
guessing. Raven's host hooks register your first prompt as a task; if they are not installed, call
`bridge_start_task` with repo `parcelwise/parcelwise-app` before reading or editing anything. Then follow what
Raven returns for the rest of the task.

File the judgment calls the change rests on with `bridge_add_node`, one question per node, before you implement
the part that depends on it. A judgment call is a value or rule this change leans on that the code does not
settle: the ones nobody has made yet (a price, an allowance, a start date, which merchants are in or out) and
the ones a record already seems to answer (what counts as one use, which table usage is read from, where
charges post). Raven settles the second kind from the record and logs whose call it was. Keep it to the calls
that would change what you build: a feature this size has five or six, not fifteen. How a thing is paged,
retried or named is engineering, not a call.

Short questions, the way you would ask a colleague across a desk: one plain sentence, fifteen words or so, no
parentheses, no lists of options inside it ("Where do assistant charges post?"), never a reading of the record.
Your reading, with the ADR or PR it came from, the options and the detail go in `context` and `options`. File each question once. Put `paths` and a
`category` on every node: `pricing` (rates, allowances, which plans), `billing` (charges, invoices, Stripe),
`data` (what is counted, which table is read), `customer` (which merchants, exceptions), `ux` (the dashboard),
`compat` (Shopify and the App Store rules).

Never settle an open value yourself: no placeholder rate, allowance, start date or merchant list, and no default
that quietly decides one. Build the parts that do not depend on open calls (`bridge_wait` says what is still
open) and leave the open values as clearly marked inputs the owner's answer fills in.

Build what you can while calls are open, then keep calling `bridge_wait` and fill in each answer as it lands.
When the mechanism is built, its tests pass and no call is still open, commit on a branch named after the work and open a draft pull
request with `gh pr create --draft`, following the PR template. Keep the body short: two sentences under **What
and why**, the commands under **How it was tested**, and as the Decisions section exactly what
`bridge_pr_summary` returns, nothing more: it brings its own heading, so do not add one above it.

- When someone asks who knows something, or why something was decided, ask Raven (`bridge_ask_raven`) first.
- Write questions for people in plain English a busy teammate can answer in ten seconds.

## Conventions

- Money is `Decimal`. Every label purchase goes through `app/labels/purchase.py:purchase_label()`.
- Usage is counted in `usage_events` and read from `usage_daily` (`app/usage/`, ADR 0005). Charges post through
  `app/billing/nightly.py` as Stripe invoice items (ADR 0006) and every charge is idempotent (ADR 0007).
- Tests: `python3 -m pytest -q`. They need no network and no database. Lint: `ruff check .`.
