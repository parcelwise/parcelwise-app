# Parcelwise

Notes for coding agents working in this repo.

## Raven

We use Raven (the `raven` MCP server) so a coding agent asks the person who owns a judgment call instead of
guessing. At the start of every task, before reading or editing anything, call `bridge_start_task` with repo
`parcelwise/parcelwise-app`, then follow what Raven returns for the rest of the task.

- When someone asks who knows something, or why something was decided, ask Raven (`bridge_ask_raven`) first.
- Write questions for people in plain English a busy teammate can answer in ten seconds.

## Conventions

- Money is `Decimal`. Every label purchase goes through `app/labels/purchase.py:purchase_label()`.
- Tests: `python3 -m pytest -q`. They need no network and no database.
