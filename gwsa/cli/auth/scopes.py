"""Scope aliases and resolver functions - re-exports from SDK."""

# Re-export from SDK auth
from gwsa.sdk.auth import (
    SCOPE_ALIASES,
    resolve_scope_alias,
    get_effective_scopes,
    has_scope,
)

# Create reverse mapping for display
REVERSE_SCOPE_ALIASES = {v: k for k, v in reversed(SCOPE_ALIASES.items())}


def resolve_scopes(scopes: list) -> list:
    """Resolve a list of scope aliases or full URLs into unique full URLs."""
    resolved = [resolve_scope_alias(scope) for scope in scopes]
    return list(set(resolved))


def get_aliases_for_scopes(scopes: list) -> list:
    """Convert full scope URLs to their preferred aliases for display."""
    aliased = [REVERSE_SCOPE_ALIASES.get(scope, scope) for scope in scopes]
    return sorted(aliased)
