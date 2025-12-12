"""CLI decorators for scope checking."""

import logging
import sys
from functools import wraps

from gwsa.sdk.auth import resolve_scope_alias, get_effective_scopes
from gwsa.sdk.profiles import get_active_profile, load_profile_metadata

logger = logging.getLogger(__name__)


def require_scopes(*required_aliases):
    """
    Decorator to ensure that the required scopes for a command are present.
    It understands that write scopes (e.g., 'mail-modify') imply read scopes.
    """
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            # Get active profile
            profile = get_active_profile()
            if not profile:
                logger.error("No active profile configured. Run 'gwsa setup' or 'gwsa profiles use <name>' first.")
                sys.exit(1)

            # Get validated scopes from profile
            validated_scopes = profile.get("scopes", [])
            if not validated_scopes:
                logger.error("No validated scopes found for profile. Please run 'gwsa setup' to re-authenticate.")
                sys.exit(1)

            # Resolve required aliases to URLs
            required_urls = set(resolve_scope_alias(alias) for alias in required_aliases)

            # Get effective scopes (including implied ones)
            effective_scopes = get_effective_scopes(validated_scopes)

            if not required_urls.issubset(effective_scopes):
                missing = required_urls - effective_scopes
                logger.error("Missing required scopes for this command.")
                logger.error(f"  Required: {', '.join(required_aliases)}")
                logger.error(f"  Missing:  {', '.join(missing)}")
                logger.error("\nPlease run 'gwsa setup' to re-authenticate with the required scopes.")
                sys.exit(1)

            return f(*args, **kwargs)
        return decorated_function
    return decorator
