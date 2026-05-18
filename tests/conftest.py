"""Top-level test configuration.

Integration-only fixtures (mcp-app user bootstrap, per-account test
config, CLI runner) live in ``tests/integration/conftest.py`` so
they fire only when the integration suite runs. Bare ``pytest``
ignores ``tests/integration`` by default and never loads them.

This file registers shared pytest markers used across suites.
"""


def pytest_configure(config):
    config.addinivalue_line(
        "markers", "integration: mark test as an integration test"
    )
    config.addinivalue_line(
        "markers",
        "requires_email: mark test as requiring test emails to be configured",
    )
