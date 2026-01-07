.PHONY: help setup lint lint-fix run dev build test test-cov test-unit test-integration test-fe test-fe-unit test-fe-component test-fe-e2e test-fe-visual test-fe-visual-update test-fe-visual-report test-fe-visual-browse test-fe-watch test-all openapi types clean deploy reload update vacuum update-currency backup backup-list defrag-memories

VENV := .venv
# Use venv binaries if available, otherwise fall back to system commands (for CI)
ifneq ($(wildcard $(VENV)/bin/python),)
PYTHON := $(VENV)/bin/python
PIP := $(VENV)/bin/pip
RUFF := $(VENV)/bin/ruff
MYPY := $(VENV)/bin/mypy
else
PYTHON := python
PIP := pip
RUFF := ruff
MYPY := mypy
endif
NPM := npm

help:
	@echo "AI Chatbot - Available targets:"
	@echo ""
	@echo "  setup                 Create venv and install dependencies"
	@echo "  dev                   Run Flask + Vite dev servers concurrently"
	@echo "  run                   Run Flask server only"
	@echo "  build                 Production build (Vite)"
	@echo ""
	@echo "  lint                  Run all linters (ruff, mypy, eslint)"
	@echo "  lint-fix              Auto-fix linting issues"
	@echo ""
	@echo "  test                  Run backend tests"
	@echo "  test-unit             Run backend unit tests only"
	@echo "  test-integration      Run backend integration tests only"
	@echo "  test-cov              Run backend tests with coverage report"
	@echo ""
	@echo "  test-fe               Run all frontend tests (unit + component + e2e)"
	@echo "  test-fe-unit          Run frontend unit tests"
	@echo "  test-fe-component     Run frontend component tests"
	@echo "  test-fe-e2e           Run frontend E2E tests (Playwright)"
	@echo "  test-fe-visual        Run visual regression tests"
	@echo "  test-fe-visual-update Update visual regression baselines"
	@echo "  test-fe-visual-report Open visual test report in browser"
	@echo "  test-fe-visual-browse Open baseline screenshot directories"
	@echo "  test-fe-watch         Run frontend tests in watch mode"
	@echo ""
	@echo "  test-all              Run all tests (backend + frontend)"
	@echo ""
	@echo "  openapi               Export OpenAPI spec to static/openapi.json"
	@echo "  types                 Generate TypeScript types from OpenAPI spec"
	@echo ""
	@echo "  clean                 Remove venv, caches, and build artifacts"
	@echo "  deploy                Deploy to systemd (Hetzner) - full restart"
	@echo "  reload                Graceful reload - zero downtime (backend only)"
	@echo "  update                Rebuild frontend + graceful reload"
	@echo "  vacuum                Run database vacuum manually"
	@echo "  update-currency       Update currency exchange rates manually"
	@echo "  backup                Create database backup manually"
	@echo "  backup-list           List existing database backups"
	@echo "  defrag-memories       Run memory defragmentation manually"

setup:
	python3 -m venv $(VENV)
	$(PIP) install --upgrade pip
	$(PIP) install -r requirements.txt
	cd web && $(NPM) install
	@echo "Setup complete. Activate with: source $(VENV)/bin/activate"

# Development: run Flask and Vite dev server concurrently
# Uses npx concurrently to manage both processes (Ctrl+C kills both)
dev:
	npx concurrently --kill-others --names "flask,vite" \
		"$(PYTHON) -m src.app" \
		"cd web && $(NPM) run dev"

# Production build
build:
	cd web && $(NPM) run build

lint:
	$(RUFF) check src/ tests/ scripts/
	$(RUFF) format --check src/ tests/ scripts/
	$(MYPY) src/
	cd web && $(NPM) run typecheck && $(NPM) run lint

lint-fix:
	$(RUFF) check --fix src/ tests/ scripts/
	$(RUFF) format src/ tests/ scripts/
	cd web && $(NPM) run lint:fix

run:
	$(PYTHON) -m src.app

test:
	$(PYTHON) -m pytest tests/ -v

test-cov:
	$(PYTHON) -m pytest tests/ -v --cov=src --cov-report=html --cov-report=term

test-unit:
	$(PYTHON) -m pytest tests/unit/ -v

test-integration:
	$(PYTHON) -m pytest tests/integration/ -v

# Frontend tests
test-fe-unit:
	cd web && $(NPM) run test:unit

test-fe-component:
	cd web && $(NPM) run test:component

test-fe-e2e:
	@echo "Cleaning up any hanging e2e servers..."
	@if [ -f .e2e-server.pid ]; then \
		PID=$$(cat .e2e-server.pid 2>/dev/null); \
		if [ -n "$$PID" ] && kill -0 $$PID 2>/dev/null; then \
			echo "Killing e2e server (PID: $$PID)..."; \
			kill $$PID 2>/dev/null || true; \
			sleep 1; \
		fi; \
		rm -f .e2e-server.pid; \
	fi
	@echo "Running E2E tests..."
	cd web && $(NPM) run test:e2e

test-fe-visual:
	cd web && $(NPM) run test:visual

test-fe-visual-update:
	cd web && $(NPM) run test:visual:update

# Open visual test report in browser for spot-checking
# Run after test-fe-visual to review any diffs
test-fe-visual-report:
	@if [ -f web/playwright-report/index.html ]; then \
		echo "Opening visual test report in browser..."; \
		open web/playwright-report/index.html 2>/dev/null || \
		xdg-open web/playwright-report/index.html 2>/dev/null || \
		echo "Report available at: web/playwright-report/index.html"; \
	else \
		echo "No report found. Run 'make test-fe-visual' first."; \
	fi

# Generate and open HTML gallery of visual test baselines
test-fe-visual-browse:
	@node web/scripts/visual-gallery.cjs
	@echo "Opening visual gallery in browser..."
	@open web/visual-gallery.html 2>/dev/null || \
		xdg-open web/visual-gallery.html 2>/dev/null || \
		echo "Gallery available at: web/visual-gallery.html"

test-fe: test-fe-unit test-fe-component test-fe-e2e

test-fe-watch:
	cd web && $(NPM) run test:watch

# All tests (backend + frontend)
test-all: test test-fe

# Export OpenAPI spec by running Flask app briefly
# The app exports spec on startup to static/openapi.json
openapi:
	$(PYTHON) -c "from src.app import create_app; app = create_app(); import json; open('static/openapi.json', 'w').write(json.dumps(app.spec, indent=2))"
	@echo "OpenAPI spec exported to static/openapi.json"

# Generate TypeScript types from OpenAPI spec
# Run 'make openapi' first if you've changed backend schemas
types:
	cd web && $(NPM) run types:generate
	@echo "TypeScript types generated at web/src/types/generated-api.ts"

clean:
	rm -rf $(VENV)
	rm -rf __pycache__ src/__pycache__ src/**/__pycache__ tests/__pycache__ tests/**/__pycache__
	rm -rf .mypy_cache .ruff_cache .pytest_cache .coverage htmlcov
	rm -rf *.egg-info
	rm -rf web/node_modules
	rm -rf static/assets
	rm -rf web/playwright-report web/test-results
	rm -rf tests/e2e-test*.db
	find . -type f -name "*.pyc" -delete

deploy:
	@mkdir -p ~/.config/systemd/user
	cp -f systemd/ai-chatbot.service ~/.config/systemd/user/
	cp -f systemd/ai-chatbot-vacuum.service ~/.config/systemd/user/
	cp -f systemd/ai-chatbot-vacuum.timer ~/.config/systemd/user/
	cp -f systemd/ai-chatbot-currency.service ~/.config/systemd/user/
	cp -f systemd/ai-chatbot-currency.timer ~/.config/systemd/user/
	cp -f systemd/ai-chatbot-backup.service ~/.config/systemd/user/
	cp -f systemd/ai-chatbot-backup.timer ~/.config/systemd/user/
	cp -f systemd/ai-chatbot-memory-defrag.service ~/.config/systemd/user/
	cp -f systemd/ai-chatbot-memory-defrag.timer ~/.config/systemd/user/
	systemctl --user daemon-reload
	systemctl --user enable ai-chatbot
	systemctl --user enable ai-chatbot-vacuum.timer
	systemctl --user enable ai-chatbot-currency.timer
	systemctl --user enable ai-chatbot-backup.timer
	systemctl --user enable ai-chatbot-memory-defrag.timer
	systemctl --user start ai-chatbot-vacuum.timer
	systemctl --user start ai-chatbot-currency.timer
	systemctl --user start ai-chatbot-backup.timer
	systemctl --user start ai-chatbot-memory-defrag.timer
	systemctl --user restart ai-chatbot
	@echo "Deployed. View logs with: journalctl --user -u ai-chatbot -f"
	@echo "Timers enabled. Check with: systemctl --user list-timers"

# Graceful reload - zero downtime for code changes (does NOT rebuild frontend)
reload:
	systemctl --user reload ai-chatbot
	@echo "Graceful reload triggered. Workers will restart after finishing current requests."

# Full update with dependencies rebuild and graceful reload
update:
	$(PIP) install -r requirements.txt
	cd web && npm install && npm run build
	systemctl --user reload ai-chatbot
	@echo "Dependencies updated, frontend rebuilt, graceful reload triggered."

vacuum:
	$(PYTHON) scripts/vacuum_databases.py

update-currency:
	$(PYTHON) scripts/update_currency_rates.py

backup:
	$(PYTHON) scripts/backup_databases.py

backup-list:
	$(PYTHON) scripts/backup_databases.py --list

defrag-memories:
	$(PYTHON) scripts/defragment_memories.py
