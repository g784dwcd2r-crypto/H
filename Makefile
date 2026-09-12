.PHONY: install test lint cov demo api schema

install:
	uv venv --python 3.12 && uv pip install -e ".[dev]"

test:
	.venv/bin/pytest

lint:
	.venv/bin/ruff check . && .venv/bin/ruff format --check .

cov:
	.venv/bin/pytest --cov=filings_hub --cov-report=term-missing

demo:
	.venv/bin/filings-hub demo

api:
	.venv/bin/filings-hub api --reload

schema:
	.venv/bin/python -c "from filings_hub.db.load import write_schema_sql; print(write_schema_sql())"
