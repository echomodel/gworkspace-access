import logging
from functools import wraps
import sys

from .config import get_config_value
from .auth.scopes import resolve_scopes, get_aliases_for_scopes

logger = logging.getLogger(__name__)

def require_scopes(*required_aliases):
    """
    Decorator to ensure that the required scopes for a command are present.
    It understands that write scopes (e.g., 'mail-modify') imply read scopes.
    """
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            if not get_config_value("auth.mode"):
                logger.error("gwsa is not configured. Please run 'gwsa setup' first.")
                sys.exit(1)

            validated_scopes = get_config_value("auth.validated_scopes", [])
            if not validated_scopes:
                logger.error("No validated scopes found in config. Please run 'gwsa setup' to re-authenticate.")
                sys.exit(1)

            # --- Intelligent Scope Check ---
            required_urls = set(resolve_scopes(list(required_aliases)))
            available_urls = set(validated_scopes)

            # Create an expanded set of available scopes that includes implied read scopes
            expanded_available = available_urls.copy()
            for scope in available_urls:
                if scope.endswith((".modify", ".readwrite", "/drive")):
                    read_scope = scope.replace(".modify", ".readonly").replace(".readwrite", ".readonly").replace("/drive", "/drive.readonly")
                    expanded_available.add(read_scope)

            if not required_urls.issubset(expanded_available):
                logger.error("Missing required scopes for this command.")
                required_display = get_aliases_for_scopes(list(required_urls))
                found_display = get_aliases_for_scopes(validated_scopes)
                logger.error(f"  Required: {', '.join(required_display)}")
                logger.error(f"  Found:    {', '.join(found_display)}")
                logger.error("\nPlease run 'gwsa setup' to re-authenticate with the required scopes.")
                sys.exit(1)

            return f(*args, **kwargs)
        return decorated_function
    return decorator
