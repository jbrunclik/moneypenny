.PHONY: help setup lint lint-fix run dev build test test-cov test-unit test-integration test-fe test-fe-unit test-fe-component test-fe-e2e test-fe-visual test-fe-visual-update test-fe-visual-report test-fe-visual-browse test-fe-watch test-all clean deploy

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
	@echo "  clean                 Remove venv, caches, and build artifacts"
	@echo "  deploy                Deploy to systemd (Hetzner)"

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
	$(RUFF) check src/ tests/
	$(RUFF) format --check src/ tests/
	$(MYPY) src/
	cd web && $(NPM) run typecheck && $(NPM) run lint

lint-fix:
	$(RUFF) check --fix src/ tests/
	$(RUFF) format src/ tests/
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
	cp -f ai-chatbot.service ~/.config/systemd/user/
	systemctl --user daemon-reload
	systemctl --user enable ai-chatbot
	systemctl --user restart ai-chatbot
	@echo "Deployed. View logs with: journalctl --user -u ai-chatbot -f"
