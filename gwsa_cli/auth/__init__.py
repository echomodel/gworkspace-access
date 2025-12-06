"""Auth utilities for gwsa.

These are standalone authentication utilities that do NOT affect gwsa configuration.
They can be used to create tokens for other projects or test credential validity.
"""
import click
from functools import wraps
from ..config import get_config_value

def scope_check_decorator(required_scopes: list[str]):
    """
    A decorator for Click commands to perform a quick check of cached authentication scopes.

    Commands decorated with this will fail fast if the required scopes are not found
    in the cached `validated_scopes` within `config.yaml`.
    """
    def decorator(f):
        @wraps(f)
        def wrapper(*args, **kwargs):
            cached_scopes = set(get_config_value("auth.validated_scopes", default=[]))
            missing_scopes = set(required_scopes) - cached_scopes

            if missing_scopes:
                missing_str = ", ".join(sorted(list(missing_scopes)))
                raise click.ClickException(
                    f"Insufficient permissions. This command requires the following scopes: "
                    f"{missing_str}. Please re-run 'gwsa setup' to re-authenticate and grant them."
                )
            return f(*args, **kwargs)
        return wrapper
    return decorator

