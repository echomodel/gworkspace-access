"""Scope aliases and resolver functions - re-exports from SDK."""

from gwsa.sdk.auth import (
    SCOPE_ALIASES,
    FEATURE_SCOPES,
    resolve_scope_alias,
    get_effective_scopes,
    has_scope,
)

# Create reverse mapping for display
REVERSE_SCOPE_ALIASES = {v: k for k, v in reversed(SCOPE_ALIASES.items())}


def resolve_scopes(scopes: list) -> list:
    """
    Resolve a list of scope aliases or full URLs into unique full URLs.
    
    Supports:
    1. Full URLs
    2. Single-URL aliases from SCOPE_ALIASES (e.g. 'mail-read')
    3. Multi-URL feature sets from FEATURE_SCOPES (e.g. 'chat')
    """
    resolved = set()
    
    for scope in scopes:
        # Check Feature Scopes (Multi-URL)
        if scope in FEATURE_SCOPES:
            resolved.update(FEATURE_SCOPES[scope])
        # Check Single Aliases
        elif scope in SCOPE_ALIASES:
            resolved.add(SCOPE_ALIASES[scope])
        # Assume Full URL
        else:
            resolved.add(scope)
            
    return list(resolved)


def get_aliases_for_scopes(scopes: list) -> list:
    """Convert full scope URLs to their preferred aliases for display."""
    aliased = [REVERSE_SCOPE_ALIASES.get(scope, scope) for scope in scopes]
    return sorted(aliased)