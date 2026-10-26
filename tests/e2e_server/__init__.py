"""The mock Flask server Playwright E2E runs against (entry: tests/e2e-server.py).

`settings` sets the test environment at import; every `src` import in this
package is function-local, so it runs after that (src/config.py reads the
environment at import).
"""
