.PHONY: install test framework-test integration-test clean uninstall help venv

# Auto-create venv on first invocation; idempotent thereafter.
venv:
	@if [ ! -d ".venv" ]; then \
		python3 -m venv .venv && \
		. .venv/bin/activate && pip install --upgrade pip && pip install -e '.[dev]'; \
	fi

# Install all three CLIs (gwsa, gwsa-mcp, gwsa-admin) with pipx for end-user use.
install:
	@command -v pipx >/dev/null 2>&1 || (echo "pipx not found; install with: pip install pipx"; exit 1)
	@echo "Installing gworkspace-access with pipx..."
	@pipx install -e . --force 2>/dev/null || pipx install . --force
	@echo "Done. CLIs installed: gwsa, gwsa-mcp, gwsa-admin"

# Default test target — unit + framework only. Fast, offline, no credentials.
test: venv
	@. .venv/bin/activate && pytest

# Framework conformance tests only.
framework-test: venv
	@. .venv/bin/activate && pytest tests/framework/ -v

# Real-user integration suite — hits live Gmail/Drive. Requires a configured
# local account (gwsa-admin connect local + gwsa-admin accounts add).
integration-test: venv
	@. .venv/bin/activate && pytest tests/integration/real-user/ -v

clean:
	rm -rf .venv build/ dist/ *.egg-info/ .pytest_cache/
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true

uninstall:
	pipx uninstall gwsa 2>/dev/null || true

help:
	@echo "Targets:"
	@echo "  install          - Install with pipx (gwsa + gwsa-mcp + gwsa-admin)"
	@echo "  test             - Run unit + framework tests (auto-creates venv)"
	@echo "  framework-test   - Run only the mcp-app framework conformance tests"
	@echo "  integration-test - Run real-user integration tests (requires creds)"
	@echo "  clean            - Remove venv and build artifacts"
	@echo "  uninstall        - Remove from pipx"
