"""mcp-app framework conformance tests for gwsa.

Imports the mcp-app testing pack modules:

- ``iam``: auth enforcement (every tool wrapped, JWT middleware, admin auth)
- ``wiring``: app and entry-point wiring (CLIs, tools_module discovery, App fields)
- ``tools``: tool protocol conformance (docstrings, type hints, return types)
- ``health``: ``/health`` endpoint behavior

Tests are parameterised against the ``app`` fixture from ``conftest.py``.
"""

from mcp_app.testing.iam import *  # noqa: F401, F403
from mcp_app.testing.wiring import *  # noqa: F401, F403
from mcp_app.testing.tools import *  # noqa: F401, F403
from mcp_app.testing.health import *  # noqa: F401, F403
