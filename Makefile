.DEFAULT_GOAL := help
SHELL := /bin/bash
.ONESHELL:

VENV := backend/.venv

.PHONY: help
help:
	@echo "make setup  - create venv, install backend + frontend dependencies"
	@echo "make dev    - run backend (:8731) and frontend (:5183) together"

.PHONY: setup
setup:
	python3 -m venv $(VENV)
	$(VENV)/bin/pip install --upgrade pip
	$(VENV)/bin/pip install -r backend/requirements.txt
	cd frontend && npm install
	@echo ""
	@echo "Setup complete. Run 'make dev' to start the app."

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
	@echo "Starting backend on http://localhost:8731 and frontend on http://localhost:5183"
	@echo "Open http://localhost:5183 in your browser. Press Ctrl+C to stop both."
	set -m
	trap 'kill -- -$$BACKEND_PID -$$FRONTEND_PID 2>/dev/null' EXIT INT TERM
	$(VENV)/bin/uvicorn app.main:app --app-dir backend --reload-dir backend --port 8731 --reload & BACKEND_PID=$$!
	( cd frontend && npm run dev -- --port 5183 ) & FRONTEND_PID=$$!
	wait
