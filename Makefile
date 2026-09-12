.PHONY: install test lint cov demo api

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
