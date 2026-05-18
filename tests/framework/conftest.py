"""Shared fixtures for mcp-app framework tests.

The mcp-app testing pack expects an ``app`` fixture that returns
this solution's ``App`` instance. The rest of the test pack is
generic and verifies framework conformance against that app.
"""

import pytest

from gwsa import app as gwsa_app


@pytest.fixture(scope="session")
def app():
    """Provide the gwsa App object to mcp-app's test pack."""
    return gwsa_app
