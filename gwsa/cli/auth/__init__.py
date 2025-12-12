"""Auth utilities for gwsa CLI.

Re-exports from SDK and provides CLI-specific auth decorators.
"""

# Re-export SDK auth functions
from gwsa.sdk.auth import (
    get_credentials,
    get_token_info,
    refresh_credentials,
    SCOPE_ALIASES,
    FEATURE_SCOPES,
    IDENTITY_SCOPES,
)

# CLI-specific re-exports
from .check_access import (
    get_active_credentials,
    test_apis,
    test_gmail_access,
    test_docs_access,
    test_sheets_access,
    test_drive_access,
    SUPPORTED_APIS,
)

__all__ = [
    "get_credentials",
    "get_active_credentials",
    "get_token_info",
    "refresh_credentials",
    "test_apis",
    "SCOPE_ALIASES",
    "FEATURE_SCOPES",
    "IDENTITY_SCOPES",
    "SUPPORTED_APIS",
]
