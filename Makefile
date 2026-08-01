.PHONY: install dev test lint format typecheck run serve docker-build docker-up docker-down clean

install:
	pip install -e ".[dev]"

dev: install

test:
	pytest --cov=ops_copilot --cov-report=term-missing

lint:
	ruff check .
	ruff format --check .

format:
	ruff format .
	ruff check --fix .

typecheck:
	mypy src/

run: serve

serve:
	ops-copilot serve --reload

docker-build:
	docker compose build

docker-up:
	docker compose up --build

docker-down:
	docker compose down

clean:
	rm -rf .pytest_cache .mypy_cache .ruff_cache htmlcov .coverage data .chroma
	find . -type d -name __pycache__ -exec rm -rf {} +
