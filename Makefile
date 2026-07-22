.DEFAULT_GOAL := help
SHELL := /bin/bash

# Recipes here do NOT use .ONESHELL: macOS ships GNU Make 3.81, which ignores it
# and runs each line in its own shell. Multi-statement blocks that must share
# shell state (the version guard, the dev server orchestration) are therefore
# written as single backslash-continued logical lines. Standalone commands stay
# one-per-line so Make checks each exit status and stops on the first failure.

VENV := backend/.venv

# The backend needs Python >= 3.11 (datetime.UTC, plus PEP 604 `X | None`
# annotations that Pydantic evaluates at import). macOS ships 3.9 as `python3`,
# which builds a venv that installs fine but crashes on startup — so pick the
# newest suitable interpreter instead of assuming `python3`. Override with
# `make setup PYTHON=/path/to/python3.12`.
PYTHON ?= $(shell for p in python3.13 python3.12 python3.11 python3; do \
		command -v $$p >/dev/null 2>&1 || continue; \
		"$$p" -c 'import sys; sys.exit(0 if sys.version_info[:2] >= (3, 11) else 1)' 2>/dev/null \
			&& { echo $$p; break; }; \
	done)

.PHONY: help
help:
	@echo "make setup  - create venv, install backend + frontend dependencies"
	@echo "make seed   - load schema + rubrics + default accounts + RAG corpora"
	@echo "make dev    - run backend (:8731) and frontend (:5183) together"
	@echo ""
	@echo "First time: make setup && make seed && make dev"

.PHONY: setup
setup:
	@if [ -z "$(PYTHON)" ]; then \
		echo "No Python >= 3.11 found. The backend uses datetime.UTC and PEP 604" >&2; \
		echo "unions, which require 3.11+ (system python3 on macOS is 3.9)." >&2; \
		echo "" >&2; \
		echo "Install one, then re-run 'make setup':" >&2; \
		echo "  brew install python@3.12" >&2; \
		echo "Or point make at a specific interpreter:" >&2; \
		echo "  make setup PYTHON=/path/to/python3.12" >&2; \
		exit 1; \
	fi
	@echo "Using $$($(PYTHON) --version) ($$(command -v $(PYTHON)))"
	@echo "Creating virtual environment…"
	@$(PYTHON) -m venv $(VENV)
	@echo "Installing backend dependencies…"
	@$(VENV)/bin/pip install --disable-pip-version-check --quiet --upgrade pip
	@$(VENV)/bin/pip install --disable-pip-version-check --quiet -r backend/requirements.txt
	@echo "Installing frontend dependencies…"
	@cd frontend && npm install --no-fund --no-audit --loglevel=error
	@echo ""
	@echo "Setup complete. Run 'make seed' next."

.PHONY: seed
seed:
	@if [ ! -x "$(VENV)/bin/python" ]; then \
		echo "Backend venv not found — run 'make setup' first." >&2; \
		exit 1; \
	fi
	@PYTHONPATH=backend $(VENV)/bin/python -m app.seed_all

.PHONY: dev
dev:
	@if [ ! -x "$(VENV)/bin/uvicorn" ]; then \
		echo "Backend venv not found — run 'make setup' first." >&2; \
		exit 1; \
	fi
	@if [ ! -d "frontend/node_modules" ]; then \
		echo "Frontend dependencies not found — run 'make setup' first." >&2; \
		exit 1; \
	fi
	@if [ ! -f "backend/data/app.sqlite3" ]; then \
		echo "Database not found — run 'make seed' first." >&2; \
		exit 1; \
	fi
	@if ! "$(VENV)/bin/python" -c 'import sys; sys.exit(0 if sys.version_info[:2] >= (3, 11) else 1)' 2>/dev/null; then \
		echo "Backend venv is $$("$(VENV)/bin/python" --version 2>&1), but the app needs Python >= 3.11." >&2; \
		echo "Rebuild it: rm -rf $(VENV) && make setup" >&2; \
		exit 1; \
	fi
	@if (exec 3<>/dev/tcp/127.0.0.1/8731) 2>/dev/null; then \
		exec 3<&-; exec 3>&-; \
		echo "Port 8731 is already in use — another 'make dev' (this checkout or a different one) may already be running." >&2; \
		echo "Find it with: lsof -i :8731  (or) ss -ltnp | grep 8731" >&2; \
		exit 1; \
	fi
	@if (exec 3<>/dev/tcp/127.0.0.1/5183) 2>/dev/null; then \
		exec 3<&-; exec 3>&-; \
		echo "Port 5183 is already in use — another 'make dev' may already be running." >&2; \
		echo "Find it with: lsof -i :5183  (or) ss -ltnp | grep 5183" >&2; \
		exit 1; \
	fi
	@echo "Starting backend on http://localhost:8731 and frontend on http://localhost:5183"
	@echo "Open http://localhost:5183 in your browser. Press Ctrl+C to stop both."
	@set -m; \
	trap 'kill -- -$$BACKEND_PID -$$FRONTEND_PID 2>/dev/null' EXIT INT TERM; \
	$(VENV)/bin/uvicorn app.main:app --app-dir backend --reload-dir backend --port 8731 --reload \
		--timeout-graceful-shutdown 5 & \
	BACKEND_PID=$$!; \
	( cd frontend && npm run dev -- --port 5183 ) & \
	FRONTEND_PID=$$!; \
	wait
