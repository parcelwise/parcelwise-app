# Parcelwise

Notes for coding agents working in this repo.

## Raven

We use Raven (the `raven` MCP server) so a coding agent asks the person who owns a judgment call instead of
guessing. Raven's host hooks register your first prompt as a task; if they are not installed, call
`bridge_start_task` with repo `parcelwise/parcelwise-app` before reading or editing anything. Then follow what
Raven returns for the rest of the task.

Every judgment call the change rests on is its own Raven node (`bridge_add_node`), filed before you implement
the part that depends on it:

- the calls nobody has made yet: a price, an allowance, a start date, a cutoff, a customer exception, which
  merchants are in or out, where something shows in the dashboard;
- and the ones an ADR, a pull request or a teammate's earlier call already seems to answer: what counts as one
  use, which table usage is read from, how reads are paged, where charges post, a Stripe metered price or an
  invoice item, what makes a charge safe to retry, how a metered feature shows on the invoice, how retries and
  failed attempts are counted, which plans a feature is on. Raven settles those from the record and logs whose
  call it was, so the pull request shows what was decided and by whom.

One question per node: short, and the question itself ("Where do assistant charges post?"), not a reading of
the record ("does ADR 0006 hold given that..."). Your reading of the record, with the ADR or PR it came from,
goes in `context`. File each question once and do not re-word a question that is already open. Put `paths` and
a `category` on every node: `pricing` (rates, allowances, which plans), `billing` (charges, invoices, Stripe),
`data` (what is counted, which table is read), `customer` (which merchants, exceptions), `ux` (the dashboard),
`integrations` (Shopify).

Never settle an open value yourself: no placeholder rate, allowance, start date or merchant list, and no default
that quietly decides one. Build the parts that do not depend on open calls (`bridge_wait` says what is still
open) and leave the open values as clearly marked inputs the owner's answer fills in.

When the mechanism is built and its tests pass, commit on a branch named after the work and open a draft pull
request with `gh pr create --draft`, following the PR template; list the open calls under **Decisions** with
who owns each.

- When someone asks who knows something, or why something was decided, ask Raven (`bridge_ask_raven`) first.
- Write questions for people in plain English a busy teammate can answer in ten seconds.

## Conventions

- Money is `Decimal`. Every label purchase goes through `app/labels/purchase.py:purchase_label()`.
- Usage is counted in `usage_events` and read from `usage_daily` (`app/usage/`, ADR 0005). Charges post through
  `app/billing/nightly.py` as Stripe invoice items (ADR 0006) and every charge is idempotent (ADR 0007).
- Tests: `python3 -m pytest -q`. They need no network and no database. Lint: `ruff check .`.
