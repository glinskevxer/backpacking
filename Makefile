# Every target runs against the project virtualenv, so nothing here depends on
# what happens to be on PATH.

VENV ?= .venv
PY := $(VENV)/bin/python
PIP := $(VENV)/bin/pip
SRC := src/backpacking
TESTS := tests

.DEFAULT_GOAL := help
.PHONY: help venv install lint format typecheck test test-fast coverage check \
        seed serve migrate revision clean docker-build docker-up docker-down

help: ## Show the targets
	@grep -E '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) \
		| awk 'BEGIN {FS = ":.*?## "}; {printf "  %-16s %s\n", $$1, $$2}'

venv: ## Create the virtualenv
	python3.12 -m venv $(VENV)
	$(PIP) install --upgrade pip setuptools wheel

install: venv ## Install the project with every extra
	$(PIP) install -e ".[api,db,cli,dev]"

lint: ## Run ruff
	$(VENV)/bin/ruff check $(SRC) $(TESTS)

format: ## Fix what ruff can fix
	$(VENV)/bin/ruff check --fix $(SRC) $(TESTS)
	$(VENV)/bin/ruff format $(SRC) $(TESTS)

typecheck: ## Run mypy in strict mode
	$(VENV)/bin/mypy

test: ## Run the whole suite
	$(PY) -m pytest

test-fast: ## Run everything except the slow markers
	$(PY) -m pytest -m "not slow"

coverage: ## Run the suite with a coverage report
	$(PY) -m pytest --cov=backpacking --cov-report=term-missing --cov-report=xml

check: lint typecheck test ## Everything CI runs

seed: ## Load the sample corridor into a local database
	$(PY) scripts/seed_demo.py

serve: ## Run the API with reload
	$(VENV)/bin/uvicorn backpacking.api.main:app --reload --port 8000

migrate: ## Apply migrations
	$(VENV)/bin/alembic upgrade head

revision: ## Autogenerate a migration, MESSAGE=...
	$(VENV)/bin/alembic revision --autogenerate -m "$(MESSAGE)"

docker-build: ## Build the runtime image
	docker build -t backpacking:local .

docker-up: ## Bring up the api and its database
	docker compose up --build -d

docker-down: ## Tear it back down
	docker compose down -v

clean: ## Remove build and cache directories
	rm -rf build dist *.egg-info .pytest_cache .mypy_cache .ruff_cache .hypothesis htmlcov
	find . -name '__pycache__' -type d -prune -exec rm -rf {} +
