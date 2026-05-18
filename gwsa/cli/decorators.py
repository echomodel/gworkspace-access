"""CLI decorators.

Preflight scope checking was a feature of the legacy local-vault
profile model (every profile stored its validated_scopes from
tokeninfo). Under mcp-app a tool's required scopes are an attribute
of the deployed token, not a static per-profile fact, so missing
scopes surface as a Google 403 at call time rather than a friendly
preflight error. The ``require_scopes`` decorator is preserved as a
no-op so its 17+ existing callsites stay valid until scope checking
is redesigned against the new identity model.
"""

from functools import wraps


def require_scopes(*required_aliases):
    """No-op decorator preserved for callsite compatibility.

    The legacy implementation validated scopes against the active
    profile's tokeninfo cache. That data lives on a per-account
    basis under mcp-app, and the gwsa CLI may select an account at
    call time; a one-shot preflight check no longer matches the
    runtime model. Scope errors now come from Google's API as 403s.
    """
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            return f(*args, **kwargs)
        return decorated_function
    return decorator
