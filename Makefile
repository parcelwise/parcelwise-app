.PHONY: setup test lint dev

setup:
	python3 -m venv .venv && .venv/bin/pip install -e ".[dev]"

test:
	.venv/bin/pytest -q

lint:
	.venv/bin/ruff check .

dev:
	.venv/bin/python -m app.api.dev & (cd web && npm run dev)
