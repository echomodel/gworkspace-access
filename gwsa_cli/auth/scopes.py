# gwsa_cli/auth/scopes.py

"""Central definition of scope aliases and resolver functions."""

SCOPE_ALIASES = {
    # Mail
    "mail-read": "https://www.googleapis.com/auth/gmail.readonly",
    "mail-modify": "https://www.googleapis.com/auth/gmail.modify",
    "mail-labels": "https://www.googleapis.com/auth/gmail.labels",
    "mail": "https://www.googleapis.com/auth/gmail.modify",  # 'mail' is an alias for full write access

    # Sheets
    "sheets-read": "https://www.googleapis.com/auth/spreadsheets.readonly",
    "sheets": "https://www.googleapis.com/auth/spreadsheets",

    # Docs
    "docs-read": "https://www.googleapis.com/auth/documents.readonly",
    "docs": "https://www.googleapis.com/auth/documents",

    # Drive
    "drive-read": "https://www.googleapis.com/auth/drive.readonly",
    "drive-metadata-read": "https://www.googleapis.com/auth/drive.metadata.readonly",
    "drive": "https://www.googleapis.com/auth/drive",
}

# Create a reverse mapping for display purposes, preferring shorter aliases for the same URL
REVERSE_SCOPE_ALIASES = {v: k for k, v in reversed(SCOPE_ALIASES.items())}


def resolve_scopes(scopes: list[str]) -> list[str]:
    """
    Resolves a list of scope aliases or full URLs into a list of unique, full URLs.
    """
    resolved = [SCOPE_ALIASES.get(scope, scope) for scope in scopes]
    return list(set(resolved))


def get_aliases_for_scopes(scopes: list[str]) -> list[str]:
    """
    Converts a list of full scope URLs to their preferred aliases for display.
    Falls back to the full URL if no alias is defined.
    """
    aliased = [REVERSE_SCOPE_ALIASES.get(scope, scope) for scope in scopes]
    return sorted(aliased)
