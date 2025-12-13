"""CLI decorators for scope checking and profile validation.

Also contains shared display helpers for profile status and guidance.
"""

import logging
import sys
from datetime import datetime
from functools import wraps

import click

from gwsa.sdk.auth import resolve_scope_alias, get_effective_scopes
from gwsa.sdk.profiles import get_active_profile, get_profile_status, list_profiles

logger = logging.getLogger(__name__)


# =============================================================================
# Shared Display Helpers (used by profiles_commands.py, __main__.py, decorators)
# =============================================================================

def format_time_ago(iso_timestamp: str) -> str:
    """Format an ISO timestamp as a human-readable 'time ago' string."""
    if not iso_timestamp:
        return "never"
    try:
        dt = datetime.fromisoformat(iso_timestamp)
        delta = datetime.now() - dt
        if delta.days > 0:
            return f"{delta.days}d ago"
        elif delta.seconds >= 3600:
            return f"{delta.seconds // 3600}h ago"
        elif delta.seconds >= 60:
            return f"{delta.seconds // 60}m ago"
        else:
            return "just now"
    except Exception:
        return "unknown"


def format_status(status: dict, width: int = 0) -> str:
    """Format a profile status dict as a colored string.

    Args:
        status: Profile status dict with 'valid' and 'status' keys
        width: If > 0, pad the text to this width BEFORE applying color
               (ANSI codes don't count toward visible width)
    """
    if status["valid"]:
        text = "valid"
        color = "green"
    elif status["status"] == "stale":
        text = "STALE"
        color = "red"
    elif status["status"] == "unvalidated":
        text = "unvalidated"
        color = "yellow"
    else:
        text = "ERROR"
        color = "red"

    if width > 0:
        text = text.ljust(width)
    return click.style(text, fg=color)


def show_profile_guidance(active_profile_name: str = None,
                          active_is_valid: bool = False,
                          has_any_valid: bool = False,
                          has_active: bool = False):
    """Show guidance based on profile state. Reusable across commands.

    Args:
        active_profile_name: Name of active profile (if any)
        active_is_valid: Whether the active profile is valid
        has_any_valid: Whether any valid profiles exist (excluding active if invalid)
        has_active: Whether there is an active profile set
    """
    if has_active and active_is_valid:
        click.secho("Ready to use.", fg="green")
    elif has_active and not active_is_valid:
        click.secho("Active profile is not valid.", fg="red")
        click.echo(f"\nTo fix:")
        click.echo(f"  gwsa profiles refresh {active_profile_name}")
        if has_any_valid:
            click.echo("\nOr switch to a valid profile:")
            click.echo("  gwsa profiles use <name>")
    elif not has_active and has_any_valid:
        click.secho("No active profile selected.", fg="yellow")
        click.echo("\nTo activate a profile:")
        click.echo("  gwsa profiles use <name>")
    elif not has_active and not has_any_valid:
        click.secho("No valid profiles available.", fg="red")
        click.echo("\nTo get started:")
        click.echo("  gwsa profiles add <name>       # Create a new profile")
        click.echo("  gwsa profiles refresh adc      # Or authenticate via gcloud")


def _get_profile_guidance_state() -> dict:
    """Get the current profile state for guidance display.

    Returns dict with:
        - active_profile_name: Name of active profile or None
        - active_is_valid: Whether active profile is valid
        - has_any_valid: Whether any valid profiles exist
        - has_active: Whether there is an active profile
    """
    profiles = list_profiles()
    active_profile = get_active_profile()

    has_active = active_profile is not None
    active_profile_name = active_profile["name"] if active_profile else None
    active_is_valid = False
    has_any_valid = False

    for p in profiles:
        status = get_profile_status(p["name"])
        if status["valid"]:
            if p.get("is_active"):
                active_is_valid = True
            else:
                has_any_valid = True

    # If active is invalid, count other valid profiles
    if has_active and not active_is_valid:
        has_any_valid = any(
            get_profile_status(p["name"])["valid"]
            for p in profiles if p["name"] != active_profile_name
        )

    return {
        "active_profile_name": active_profile_name,
        "active_is_valid": active_is_valid,
        "has_any_valid": has_any_valid,
        "has_active": has_active,
    }


# =============================================================================
# Internal helper for decorator
# =============================================================================

def _show_profile_guidance_for_decorator():
    """Show guidance for require_scopes decorator failures."""
    state = _get_profile_guidance_state()
    show_profile_guidance(**state)


def require_scopes(*required_aliases):
    """
    Decorator to ensure that the required scopes for a command are present.
    Also validates that the active profile is valid (not stale/unvalidated).
    It understands that write scopes (e.g., 'mail-modify') imply read scopes.
    """
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            # Get active profile
            profile = get_active_profile()
            if not profile:
                click.secho("Error: No active profile configured.", fg="red")
                _show_profile_guidance_for_decorator()
                sys.exit(1)

            # Check profile validity using canonical routine
            status = get_profile_status(profile["name"])
            if not status["valid"]:
                click.secho(f"Error: Active profile '{profile['name']}' is not valid.", fg="red")
                click.echo(f"  Status: {status['status']}")
                click.echo(f"  Reason: {status['reason']}")
                click.echo(f"\nTo fix:")
                click.echo(f"  gwsa profiles refresh {profile['name']}")

                # Check if there are other valid profiles
                profiles = list_profiles()
                other_valid = [p for p in profiles if p["name"] != profile["name"]
                              and get_profile_status(p["name"])["valid"]]
                if other_valid:
                    click.echo("\nOr switch to a valid profile:")
                    click.echo("  gwsa profiles use <name>")
                sys.exit(1)

            # Get validated scopes from profile
            validated_scopes = profile.get("scopes", [])
            if not validated_scopes:
                click.secho(f"Error: No scopes found for profile '{profile['name']}'.", fg="red")
                click.echo(f"\nTo fix:")
                click.echo(f"  gwsa profiles refresh {profile['name']}")
                sys.exit(1)

            # Resolve required aliases to URLs
            required_urls = set(resolve_scope_alias(alias) for alias in required_aliases)

            # Get effective scopes (including implied ones)
            effective_scopes = get_effective_scopes(validated_scopes)

            if not required_urls.issubset(effective_scopes):
                missing = required_urls - effective_scopes
                click.secho("Error: Missing required scopes for this command.", fg="red")
                click.echo(f"  Required: {', '.join(required_aliases)}")
                click.echo(f"  Missing:  {', '.join(missing)}")
                click.echo(f"\nTo fix:")
                click.echo(f"  gwsa profiles refresh {profile['name']}")
                sys.exit(1)

            return f(*args, **kwargs)
        return decorated_function
    return decorator
