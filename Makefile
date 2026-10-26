.PHONY: help setup sandbox-image browser-setup push-keys token-key lint lint-fix check-generated run dev build test test-cov test-unit test-integration test-fe test-fe-unit test-fe-component test-fe-e2e test-fe-visual test-fe-visual-update test-fe-visual-report test-fe-visual-browse test-fe-watch decode-stack lock test-all pre-commit audit migration openapi types clean deploy reload update rollback _update _rollback _build_and_reload vacuum update-currency backup backup-list defrag-memories

VENV := .venv
# Use venv binaries if available, otherwise fall back to system commands (for CI)
ifneq ($(wildcard $(VENV)/bin/python),)
PYTHON := $(VENV)/bin/python
PIP := $(VENV)/bin/pip
RUFF := $(VENV)/bin/ruff
MYPY := $(VENV)/bin/mypy
LINT_IMPORTS := $(VENV)/bin/lint-imports
else
PYTHON := python
PIP := pip
RUFF := ruff
MYPY := mypy
LINT_IMPORTS := lint-imports
endif
NPM := npm
# E2E server port: override to run a second E2E suite side by side
# (`make test-fe-e2e E2E_PORT=8011` in another worktree or session)
E2E_PORT ?= 8001
export E2E_PORT

# Deploy hosts may pin a newer node than the distro ships (Debian 13 stops at
# node 20, below what vite will require) - see .nvmrc. That pinned toolchain
# is installed per-user and linked into ~/.local/bin, never system-wide: the
# host runs other people's node services off /usr/bin/node and must not have
# the runtime swapped under them. Harmless no-op where the directory is absent.
export PATH := $(HOME)/.local/bin:$(PATH)

help:
	@echo "Moneypenny - Available targets:"
	@echo ""
	@echo "  setup                 Create venv and install dependencies"
	@echo "  sandbox-image         Build custom Docker image for code sandbox"
	@echo "  browser-setup         Install Playwright and Chromium for browser tool"
	@echo "  dev                   Run Flask + Vite dev servers concurrently"
	@echo "  run                   Run Flask server only"
	@echo "  build                 Production build (Vite)"
	@echo ""
	@echo "  lint                  Run all linters (ruff, mypy, eslint, knip)"
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
	@echo "  test-fe-e2e           Build, then run frontend E2E tests (Playwright)"
	@echo "  test-fe-visual        Run visual regression tests"
	@echo "  test-fe-visual-update Update local (darwin) visual baselines; CI compares linux ones (/regen-baselines)"
	@echo "  test-fe-visual-report Open visual test report in browser"
	@echo "  test-fe-visual-browse Open baseline screenshot directories"
	@echo "  test-fe-watch         Run frontend tests in watch mode"
	@echo ""
	@echo "  test-all              Run all tests (backend + frontend)"
	@echo "  pre-commit            Run lint + test-all"
	@echo ""
	@echo "  audit                 Run dependency vulnerability scan"
	@echo "  migration             Create new database migration (NAME=xxx)"
	@echo "  openapi               Export OpenAPI spec to static/openapi.json"
	@echo "  types                 Generate TypeScript types from OpenAPI spec"
	@echo ""
	@echo "  clean                 Remove venv, caches, and build artifacts"
	@echo "  deploy                Deploy to systemd - full restart"
	@echo "  reload                Graceful reload - zero downtime (backend only)"
	@echo "  update                Pull, rebuild, graceful reload (one at a time)"
	@echo "  rollback              Code back to the commit before the last update"
	@echo "  vacuum                Run database vacuum manually"
	@echo "  decode-stack          Decode minified E2E/CI stack frames (log on stdin)"
	@echo "  lock                  Re-pin requirements*.txt after editing requirements*.in"
	@echo "  update-currency       Update currency exchange rates manually"
	@echo "  backup                Create database backup manually"
	@echo "  backup-list           List existing database backups"
	@echo "  defrag-memories       Run memory defragmentation manually"

# uv takes the Python version from .python-version (plain venv uses whatever
# python3 is); npm ci installs the lockfile as is (npm install rewrites it)
setup:
	@if command -v uv >/dev/null 2>&1; then \
		uv venv --seed --allow-existing --python "$$(cat .python-version)" $(VENV) && \
		uv pip install --python $(VENV)/bin/python -r requirements.txt -r requirements-dev.txt; \
	else \
		python3 -m venv $(VENV) && $(PIP) install --upgrade pip && $(PIP) install -r requirements.txt -r requirements-dev.txt; \
	fi
	cd web && $(NPM) ci
	@echo ""
	@echo "Setup complete. Activate with: source $(VENV)/bin/activate"
	@echo ""
	@echo "Optional: Build custom sandbox image for better code execution performance:"
	@echo "  make sandbox-image"

# Build custom Docker image for code sandbox with pre-installed fonts
# Automatically cleans up old versions to prevent image bloat
sandbox-image:
	@echo "Building custom code sandbox Docker image..."
	@echo ""
	@# Build new image
	docker build -t moneypenny-sandbox:local docker/code-sandbox/
	@echo ""
	@# Remove dangling images (old layers that are no longer used)
	@if docker images -f "dangling=true" -q 2>/dev/null | grep -q .; then \
		echo "Cleaning up dangling images..."; \
		docker images -f "dangling=true" -q | xargs -r docker rmi 2>/dev/null || true; \
		echo ""; \
	fi
	@echo "✓ Sandbox image built: moneypenny-sandbox:local"
	@echo ""
	@echo "Update your .env file with:"
	@echo "  CODE_SANDBOX_IMAGE=moneypenny-sandbox:local"

# Install Playwright and Chromium browser for the browser automation tool
browser-setup:
	@echo "Installing Playwright and Chromium..."
	$(PIP) install playwright
	$(PYTHON) -m playwright install chromium --with-deps
	@echo ""
	@echo "✓ Playwright and Chromium installed"
	@echo ""
	@echo "Enable the browser tool in .env:"
	@echo "  BROWSER_ENABLED=true"

# Generate a VAPID key pair for Web Push notifications
push-keys:
	$(PYTHON) scripts/generate_vapid_keys.py

# Generate a Fernet key for token encryption at rest
token-key:
	@$(PYTHON) -c "from cryptography.fernet import Fernet; print('Add to your .env:'); print(); print('TOKEN_ENCRYPTION_KEY=' + Fernet.generate_key().decode())"

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
	$(RUFF) check src/ tests/ scripts/ evals/
	$(RUFF) format --check src/ tests/ scripts/ evals/
	$(MYPY) src/ evals/
	$(LINT_IMPORTS)
	cd web && $(NPM) run typecheck && $(NPM) run lint && $(NPM) run knip && $(NPM) run format:check
	@$(MAKE) --no-print-directory check-generated

# P1: the committed OpenAPI spec and TS types must match the schemas. Regenerates
# them; when that changed anything, the fresh files are left to commit.
GENERATED_API := static/openapi.json web/src/types/generated-api.ts
check-generated:
	@before=$$(cat $(GENERATED_API) | shasum); \
	$(MAKE) --no-print-directory openapi types > /dev/null 2>&1; \
	if [ "$$before" != "$$(cat $(GENERATED_API) | shasum)" ]; then \
		echo "The OpenAPI spec or TS types were stale - regenerated them, commit the result"; exit 1; \
	fi

lint-fix:
	$(RUFF) check --fix src/ tests/ scripts/ evals/
	$(RUFF) format src/ tests/ scripts/ evals/
	cd web && $(NPM) run lint:fix

run:
	$(PYTHON) -m src.app

test:
	$(PYTHON) -m pytest tests/ -v -n auto

eval: ## Run agent eval harness (golden cases, hits live Gemini API)
	$(PYTHON) evals/run.py

test-cov:
	$(PYTHON) -m pytest tests/ -v -n auto --cov=src --cov-report=html --cov-report=term

test-unit:
	$(PYTHON) -m pytest tests/unit/ -v

test-integration:
	$(PYTHON) -m pytest tests/integration/ -v

# Frontend tests
test-fe-unit:
	cd web && $(NPM) run test:unit

test-fe-component:
	cd web && $(NPM) run test:component

test-fe-e2e: build
	@echo "Cleaning up any hanging e2e servers..."
	@if [ -f .e2e-server-$(E2E_PORT).pid ]; then \
		PID=$$(cat .e2e-server-$(E2E_PORT).pid 2>/dev/null); \
		if [ -n "$$PID" ] && kill -0 $$PID 2>/dev/null; then \
			echo "Killing e2e server (PID: $$PID)..."; \
			kill $$PID 2>/dev/null || true; \
			sleep 1; \
		fi; \
		rm -f .e2e-server-$(E2E_PORT).pid; \
	fi
	@echo "Running E2E tests..."
	cd web && $(NPM) run test:e2e

test-fe-visual: build
	cd web && $(NPM) run test:visual

test-fe-visual-update: build
	cd web && $(NPM) run test:visual:update

# Linux baselines (used by CI) - runs the suite in the Playwright Docker
# image against a mock server on the host
test-fe-visual-linux:
	scripts/visual_linux.sh

test-fe-visual-linux-update:
	scripts/visual_linux.sh --update-snapshots

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

# Full pre-commit check: lint + all tests (E2E rebuilds the frontend first)
pre-commit: lint test-all
	@echo "All pre-commit checks passed!"

# Dependency vulnerability scan
# Findings are reported but non-blocking; an audit that cannot run fails.
# Both tools exit 1 for findings and for errors alike, so the JSON report
# decides: no parseable report (or npm's "error" key) means it did not run.
audit:
	@echo "Running Python dependency audit..."
	@$(PIP) install -q pip-audit
	@report=$$(mktemp); \
	$(PYTHON) -m pip_audit -r requirements.txt -r requirements-dev.txt -f json -o $$report --progress-spinner off; \
	$(PYTHON) -c 'import json, sys; deps = json.load(open(sys.argv[1]))["dependencies"]; found = ["  %s %s: %s" % (d["name"], d["version"], v["id"]) for d in deps for v in d.get("vulns", [])]; print("\n".join(found)); print("%d known vulnerabilities (non-blocking)" % len(found))' $$report \
		|| { echo "pip-audit could not run"; rm -f $$report; exit 1; }; \
	rm -f $$report
	@echo ""
	@echo "Running Node.js dependency audit..."
	@report=$$(mktemp); \
	(cd web && $(NPM) audit --audit-level=high --json > $$report); \
	$(PYTHON) -c 'import json, sys; d = json.load(open(sys.argv[1])); sys.exit("npm audit could not run: %s" % d["error"]) if "error" in d else None; counts = d["metadata"]["vulnerabilities"]; print(", ".join("%s: %s" % kv for kv in counts.items())); print("Details: cd web && npm audit (non-blocking)") if counts["total"] else None' $$report \
		|| { rm -f $$report; exit 1; }; \
	rm -f $$report

# Create a new database migration file
# Usage: make migration NAME=add_preferences_table
migration:
	@if [ -z "$(NAME)" ]; then \
		echo "Usage: make migration NAME=description_of_change"; \
		exit 1; \
	fi
	@NEXT=$$(ls migrations/*.py 2>/dev/null | grep -v __pycache__ | sort | tail -1 | sed 's/.*\///' | sed 's/_.*//' | awk '{printf "%04d", $$1+1}'); \
	FILE="migrations/$${NEXT}_$(NAME).py"; \
	echo '"""' > "$$FILE"; \
	echo "$(NAME)" >> "$$FILE"; \
	echo '"""' >> "$$FILE"; \
	echo 'from yoyo import step' >> "$$FILE"; \
	echo '' >> "$$FILE"; \
	echo 'steps = [' >> "$$FILE"; \
	echo '    step(' >> "$$FILE"; \
	echo '        # Apply' >> "$$FILE"; \
	echo '        """' >> "$$FILE"; \
	echo '        -- TODO: Add SQL here' >> "$$FILE"; \
	echo '        """,' >> "$$FILE"; \
	echo '        # Rollback' >> "$$FILE"; \
	echo '        """' >> "$$FILE"; \
	echo '        -- TODO: Add rollback SQL here' >> "$$FILE"; \
	echo '        """,' >> "$$FILE"; \
	echo '    ),' >> "$$FILE"; \
	echo ']' >> "$$FILE"; \
	echo "Created migration: $$FILE"

# Export OpenAPI spec by running Flask app briefly
# The app exports spec on startup to static/openapi.json
openapi:
	FLASK_ENV=testing $(PYTHON) -c "from src.app import create_app; app = create_app(); import json; open('static/openapi.json', 'w').write(json.dumps(app.spec, indent=2))"
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
	cp -f systemd/moneypenny.service ~/.config/systemd/user/
	cp -f systemd/moneypenny-vacuum.service ~/.config/systemd/user/
	cp -f systemd/moneypenny-vacuum.timer ~/.config/systemd/user/
	cp -f systemd/moneypenny-currency.service ~/.config/systemd/user/
	cp -f systemd/moneypenny-currency.timer ~/.config/systemd/user/
	cp -f systemd/moneypenny-backup.service ~/.config/systemd/user/
	cp -f systemd/moneypenny-backup.timer ~/.config/systemd/user/
	cp -f systemd/moneypenny-memory-defrag.service ~/.config/systemd/user/
	cp -f systemd/moneypenny-memory-defrag.timer ~/.config/systemd/user/
	cp -f systemd/moneypenny-agent-scheduler.service ~/.config/systemd/user/
	cp -f systemd/moneypenny-agent-scheduler.timer ~/.config/systemd/user/
	cp -f systemd/moneypenny-file-cleanup.service ~/.config/systemd/user/
	cp -f systemd/moneypenny-file-cleanup.timer ~/.config/systemd/user/
	systemctl --user daemon-reload
	systemctl --user enable moneypenny
	systemctl --user enable moneypenny-vacuum.timer
	systemctl --user enable moneypenny-currency.timer
	systemctl --user enable moneypenny-backup.timer
	systemctl --user enable moneypenny-memory-defrag.timer
	systemctl --user enable moneypenny-agent-scheduler.timer
	systemctl --user enable moneypenny-file-cleanup.timer
	systemctl --user start moneypenny-vacuum.timer
	systemctl --user start moneypenny-currency.timer
	systemctl --user start moneypenny-backup.timer
	systemctl --user start moneypenny-memory-defrag.timer
	systemctl --user start moneypenny-agent-scheduler.timer
	systemctl --user start moneypenny-file-cleanup.timer
	systemctl --user restart moneypenny
	@echo "Deployed. View logs with: journalctl --user -u moneypenny -f"
	@echo "Timers enabled. Check with: systemctl --user list-timers"

# Graceful reload - zero downtime for code changes (does NOT rebuild frontend)
reload:
	systemctl --user reload moneypenny
	@echo "Graceful reload triggered. Workers will restart after finishing current requests."

# Full update with dependencies rebuild and graceful reload
# npm ci, not npm install: install mutates package-lock.json on version
# drift, and the dirty lockfile then blocks the next git pull --ff-only.
# npm ci is not enough on its own though - it still normalizes the lockfile
# when the deploy host's npm is OLDER than the one that generated it (npm 9
# strips the `libc` entries npm 10+ writes for optional platform packages).
# That silently dirties the tree and aborts the NEXT deploy, which is how a
# routine dependency bump broke one on Sep 25 2026. On a deploy host the
# lockfile is a build input, never a local edit worth keeping, so discard
# any generated drift before pulling.
# One deploy at a time (S11): a quick second deploy once stranded a half-applied
# migration and crash-looped the app (Aug 22 2026)
update:
	@command -v flock >/dev/null || { echo "make update needs flock (util-linux)"; exit 1; }
	flock --nonblock .deploy.lock $(MAKE) --no-print-directory _update

_update:
	@mkdir -p .deploy
	git rev-parse HEAD > .deploy/previous-sha
	git checkout -q main  # a rollback leaves HEAD detached
	git checkout -- web/package-lock.json 2>/dev/null || true
	git pull --ff-only
	$(PIP) install -r requirements.txt
	# Keep the agent browser tool's Chromium in lockstep with the playwright
	# package: a version bump changes the required build, and pip install alone
	# leaves the old binary stale (the tool then fails with "run playwright
	# install"). No-op download when already current; no --with-deps (unattended,
	# no sudo - system libs come from the one-time `make browser-setup`).
	$(PYTHON) -m playwright install chromium
	# Migrations apply when the new workers start and can't be rolled back by
	# `make rollback`: take a backup first when this deploy brings any
	@if ! git diff --quiet "$$(cat .deploy/previous-sha)" HEAD -- migrations/; then \
		echo "New migrations - backing up the databases first"; \
		$(PYTHON) scripts/backup_databases.py; \
	fi
	$(MAKE) --no-print-directory _build_and_reload

# Code-only rollback to the commit before the last deploy (S11). A deploy that
# ran migrations also needs the databases restored (docs/deployment.md).
rollback:
	@test -s .deploy/previous-sha || { echo "No previous deploy recorded"; exit 1; }
	flock --nonblock .deploy.lock $(MAKE) --no-print-directory _rollback

_rollback:
	git checkout -q --detach "$$(cat .deploy/previous-sha)"
	$(PIP) install -r requirements.txt
	$(MAKE) --no-print-directory _build_and_reload

# The build lands beside the live assets and is copied over them without
# deleting anything: the old workers keep serving their chunks until the
# reload. Chunks only the previous build used go once the new workers pass.
_build_and_reload:
	cd web && npm ci && npm run build -- --outDir ../static/assets.new --emptyOutDir
	mkdir -p static/assets && cp -R static/assets.new/. static/assets/
	# Reloads, then waits for the NEW workers: right after a reload the old
	# workers still answer, so a plain health curl passed while the new ones
	# crash-looped (Oct 13 2026). /api/ready, not /api/health: it also fails
	# while a leaked transaction holds the write lock (Oct 25 2026)
	$(PYTHON) scripts/deploy_health_gate.py --unit moneypenny --url http://localhost:8000/api/ready
	cd static/assets.new && find . -type f | sort > ../assets.keep
	cd static/assets && find . -type f | sort | comm -23 - ../assets.keep | xargs -r rm -f
	rm -rf static/assets.new static/assets.keep

vacuum:
	$(PYTHON) scripts/vacuum_databases.py

# requirements.txt is a lock: every package pinned, so the laptop, CI and
# the production host install the same versions. Edit the ranges in
# requirements.in, then run this (keeps existing pins where they still fit;
# Dependabot bumps the pins). --universal: one lock valid on macOS and Linux.
# requirements.txt = runtime (production installs only this); requirements-dev.txt
# = tools on top, constrained to the runtime pins (P5). Existing pins are kept.
LOCK_FLAGS = --universal --python-version 3.14 --custom-compile-command "make lock"
lock:
	uv pip compile requirements.in -o requirements.txt $(LOCK_FLAGS)
	uv pip compile requirements-dev.in -o requirements-dev.txt $(LOCK_FLAGS)

# Decode minified E2E/CI stack frames: a sourcemap build of this commit has
# the same chunk hashes as the tested build (make decode-stack < job.log)
decode-stack:
	@node web/scripts/decode-stack.cjs

update-currency:
	$(PYTHON) scripts/update_currency_rates.py

backup:
	$(PYTHON) scripts/backup_databases.py

backup-list:
	$(PYTHON) scripts/backup_databases.py --list

defrag-memories:
	$(PYTHON) scripts/defragment_memories.py
