#!/usr/bin/env bash
# Run the visual regression suite inside the Playwright Linux container,
# against the e2e mock server running on the host. This is how the
# *-linux.png baselines (used by CI) are generated and verified locally.
#
# Usage:
#   scripts/visual_linux.sh            # verify against linux baselines
#   scripts/visual_linux.sh --update-snapshots   # regenerate baselines
#
# Requirements: Docker, a production build in static/ (make build), and
# node_modules installed (linux-compatible packages are resolved inside
# the container via the mounted repo; @playwright/test is pure JS).
set -euo pipefail

cd "$(dirname "$0")/.."

PLAYWRIGHT_VERSION=$(node -p "require('./web/package.json').devDependencies['@playwright/test']")
IMAGE="mcr.microsoft.com/playwright:v${PLAYWRIGHT_VERSION}-jammy"

echo "Using image: $IMAGE"

# Kill any stale mock server, then start a fresh one on the host
lsof -tiTCP:8001 -sTCP:LISTEN | xargs kill 2>/dev/null || true
sleep 1
.venv/bin/python tests/e2e-server.py >/tmp/e2e-server-visual-linux.log 2>&1 &
SERVER_PID=$!
trap 'kill $SERVER_PID 2>/dev/null || true' EXIT

for _ in $(seq 1 30); do
  if curl -sf -o /dev/null http://localhost:8001/; then break; fi
  sleep 1
done
curl -sf -o /dev/null http://localhost:8001/ || { echo "e2e server failed to start"; exit 1; }

# host-gateway maps host.docker.internal on Linux; it is built in on macOS
docker run --rm \
  --add-host=host.docker.internal:host-gateway \
  -v "$PWD":/work -w /work/web \
  -e PW_BASE_URL=http://host.docker.internal:8001 \
  -e CI=1 \
  --ipc=host \
  "$IMAGE" \
  npx playwright test tests/visual "$@"
