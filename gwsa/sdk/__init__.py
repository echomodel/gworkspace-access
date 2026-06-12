"""GWSA SDK — Core library for Google Workspace API access.

Credential resolution flows through mcp-app's ``current_user``
ContextVar. The gwsa CLI bootstraps this from the local user store
(see ``gwsa.cli.__main__``); the MCP server gets it from
``mcp_app.App``'s HTTP middleware or stdio bootstrap.

The ``profiles`` submodule still exists for the one-shot
``gwsa-admin migrate`` read path, but is no longer used at runtime
and is not re-exported here.

Example usage:
    from gwsa.sdk import mail

    # Inside a request context (current_user set):
    messages, metadata = mail.search("from:user@example.com")
"""

from . import config
from . import auth
from . import mail
from . import docs
from . import drive
from . import sheets

__all__ = ["config", "auth", "mail", "docs", "drive", "sheets"]
