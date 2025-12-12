"""GWSA SDK - Core library for Google Workspace API access.

This SDK provides programmatic access to Google Workspace APIs with
multi-profile authentication support. It can be used by:
- The gwsa CLI
- The gwsa MCP server
- Third-party applications

Example usage:
    from gwsa.sdk import profiles, mail

    # List available profiles
    for profile in profiles.list_profiles():
        print(f"{profile['name']}: {profile['email']}")

    # Search emails using active profile
    messages, metadata = mail.search("from:someone@example.com")
"""

from . import config
from . import profiles
from . import auth
from . import mail
from . import docs

__all__ = ["config", "profiles", "auth", "mail", "docs"]
