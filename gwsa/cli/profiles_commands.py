"""CLI commands for profile management."""

import sys
import click
from datetime import datetime

from .profiles import (
    ADC_PROFILE_NAME,
    list_profiles,
    get_active_profile_name,
    set_active_profile,
    profile_exists,
    delete_profile,
    create_profile,
    check_adc_changed,
    is_valid_profile_name,
)


def _format_time_ago(iso_timestamp: str) -> str:
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


@click.group()
def profiles():
    """Manage authentication profiles for multiple Google identities."""
    pass


@profiles.command("list")
def list_cmd():
    """List all available profiles."""
    profile_list = list_profiles()

    if not profile_list:
        click.echo("No profiles configured.")
        return

    click.echo("\nProfiles:")
    click.echo("-" * 70)

    for p in profile_list:
        # Build status indicators
        markers = []
        if p["is_active"]:
            markers.append("active")
        if p["is_adc"]:
            markers.append("built-in")
            # ADC is "stale" if changed since validation, "unvalidated" if never validated
            if p.get("adc_changed"):
                if p.get("last_validated"):
                    markers.append(click.style("STALE", fg="red"))
                else:
                    markers.append(click.style("unvalidated", fg="yellow"))

        marker_str = f" ({', '.join(markers)})" if markers else ""

        # Format email
        email = p.get("email") or "(not validated)"
        if p["is_adc"] and p.get("adc_changed") and p.get("email"):
            email = click.style(f"{email} (may have changed)", fg="yellow")

        # Format scopes
        scope_count = len(p.get("scopes", []))
        scope_str = f"{scope_count} scopes" if scope_count else "no scopes"

        # Format last validated
        validated_str = _format_time_ago(p.get("last_validated"))

        # Output
        name_display = p["name"]
        if p["is_active"]:
            name_display = click.style(f"* {p['name']}", fg="green", bold=True)
        else:
            name_display = f"  {p['name']}"

        click.echo(f"{name_display:20}{marker_str}")
        click.echo(f"      Email: {email}")
        click.echo(f"      Scopes: {scope_str}   Validated: {validated_str}")

        # Warning for stale ADC
        if p["is_adc"] and p.get("adc_changed") and p.get("last_validated"):
            click.secho("      ⚠ ADC credentials changed. Run 'gwsa setup --use-adc' to re-validate.",
                       fg="yellow")
        click.echo()


@profiles.command("current")
def current_cmd():
    """Show the currently active profile."""
    active = get_active_profile_name()
    if active:
        click.echo(f"Active profile: {active}")
        if active == ADC_PROFILE_NAME and check_adc_changed():
            click.secho("  Warning: ADC credentials have changed since last validation.",
                       fg="yellow")
    else:
        click.echo("No active profile. Using legacy configuration.")


@profiles.command("use")
@click.argument("name")
@click.option("--force", "-f", is_flag=True, help="Force switch even if ADC is stale.")
def use_cmd(name, force):
    """Switch to a different profile.

    NAME is the profile to activate. Use 'adc' for Application Default Credentials.
    """
    from .profiles import load_adc_cached_metadata

    if not is_valid_profile_name(name) and name != ADC_PROFILE_NAME:
        click.secho(f"Invalid profile name: {name}", fg="red")
        sys.exit(1)

    if name != ADC_PROFILE_NAME and not profile_exists(name):
        click.secho(f"Profile not found: {name}", fg="red")
        click.echo("Use 'gwsa profiles list' to see available profiles.")
        sys.exit(1)

    # Check for stale ADC
    if name == ADC_PROFILE_NAME and check_adc_changed():
        adc_meta = load_adc_cached_metadata()
        if adc_meta.get("last_validated"):
            # ADC was validated before but has changed
            click.secho("Error: ADC credentials have changed since last validation.", fg="red")
            click.echo("The cached email and scopes may no longer be accurate.")
            click.echo("\nOptions:")
            click.echo("  1. Run 'gwsa setup --use-adc' to re-validate ADC")
            click.echo("  2. Use --force to switch anyway (not recommended)")
            if not force:
                sys.exit(1)
            click.secho("\nProceeding with --force...", fg="yellow")

    if set_active_profile(name):
        click.secho(f"Switched to profile: {name}", fg="green")
        if name == ADC_PROFILE_NAME:
            if check_adc_changed() and not load_adc_cached_metadata().get("last_validated"):
                click.secho("  Note: ADC has not been validated yet. "
                           "Run 'gwsa setup --use-adc' to validate.", fg="yellow")
    else:
        click.secho(f"Failed to switch to profile: {name}", fg="red")
        sys.exit(1)


@profiles.command("create")
@click.argument("name")
@click.option("--client-creds", type=click.Path(exists=True),
              help="Path to OAuth client secrets file.")
def create_cmd(name, client_creds):
    """Create a new token profile.

    NAME is the profile name (alphanumeric, hyphens, underscores allowed).

    This will open a browser for OAuth consent.
    """
    import json
    from google_auth_oauthlib.flow import InstalledAppFlow
    from .auth.check_access import FEATURE_SCOPES, IDENTITY_SCOPES, get_token_info
    from .setup_local import CLIENT_SECRETS_FILE

    if name == ADC_PROFILE_NAME:
        click.secho("Cannot create profile with reserved name 'adc'.", fg="red")
        sys.exit(1)

    if not is_valid_profile_name(name):
        click.secho(f"Invalid profile name: {name}", fg="red")
        click.echo("Use alphanumeric characters, hyphens, or underscores (1-32 chars).")
        sys.exit(1)

    if profile_exists(name):
        click.secho(f"Profile already exists: {name}", fg="red")
        click.echo("Delete it first with 'gwsa profiles delete'.")
        sys.exit(1)

    # Determine client secrets path
    secrets_path = client_creds or CLIENT_SECRETS_FILE
    import os
    if not os.path.exists(secrets_path):
        click.secho(f"Client secrets not found: {secrets_path}", fg="red")
        if not client_creds:
            click.echo("Specify --client-creds or run 'gwsa setup --client-creds' first.")
        sys.exit(1)

    # Collect all scopes
    all_scopes = list({scope for scope_set in FEATURE_SCOPES.values() for scope in scope_set} | IDENTITY_SCOPES)

    click.echo(f"Creating profile '{name}'...")
    click.echo("A browser window will open for authentication.")

    try:
        flow = InstalledAppFlow.from_client_secrets_file(secrets_path, all_scopes)
        creds = flow.run_local_server(port=0)

        # Get token info for email and scopes
        token_info = get_token_info(creds)
        email = token_info.get("email")
        scopes = token_info.get("scopes", [])

        # Save token data
        token_data = json.loads(creds.to_json())
        token_data["type"] = "authorized_user"

        if create_profile(name, token_data, email=email, scopes=scopes):
            click.secho(f"\nProfile '{name}' created successfully!", fg="green")
            if email:
                click.echo(f"  Email: {email}")
            click.echo(f"  Scopes: {len(scopes)}")
            click.echo(f"\nTo use this profile: gwsa profiles use {name}")
        else:
            click.secho(f"Failed to create profile: {name}", fg="red")
            sys.exit(1)

    except Exception as e:
        click.secho(f"Error creating profile: {e}", fg="red")
        sys.exit(1)


@profiles.command("delete")
@click.argument("name")
@click.option("--yes", "-y", is_flag=True, help="Skip confirmation prompt.")
def delete_cmd(name, yes):
    """Delete a profile.

    NAME is the profile to delete. Cannot delete the built-in 'adc' profile.
    """
    if name == ADC_PROFILE_NAME:
        click.secho("Cannot delete built-in 'adc' profile.", fg="red")
        sys.exit(1)

    if not profile_exists(name):
        click.secho(f"Profile not found: {name}", fg="red")
        sys.exit(1)

    active = get_active_profile_name()
    if active == name:
        click.secho(f"Warning: '{name}' is the active profile.", fg="yellow")

    if not yes:
        if not click.confirm(f"Delete profile '{name}'?"):
            click.echo("Cancelled.")
            return

    if delete_profile(name):
        click.secho(f"Profile '{name}' deleted.", fg="green")
        if active == name:
            click.echo("No active profile. Run 'gwsa profiles use <name>' to select one.")
    else:
        click.secho(f"Failed to delete profile: {name}", fg="red")
        sys.exit(1)
