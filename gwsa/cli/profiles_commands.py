"""CLI commands for profile management."""

import sys
import click
import json
import os
from pathlib import Path

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
    get_profile_dir,
    get_profile_token_path,
)
from gwsa.sdk.config import get_config_file_path
from .decorators import format_time_ago, format_status, show_profile_guidance


@click.group()
def profiles():
    """Manage authentication profiles for multiple Google identities."""
    pass


@profiles.command("list")
def list_cmd():
    """List all available profiles."""
    from .profiles import get_profile_status

    profile_list = list_profiles()

    if not profile_list:
        click.echo("No profiles configured.")
        click.echo("\nTo get started:")
        click.echo("  gwsa profiles add <name>       # Create a new profile")
        click.echo("  gwsa profiles refresh adc      # Or authenticate via gcloud")
        return

    # Track state for guidance
    has_active = False
    active_is_valid = False
    has_any_valid = False
    active_profile_name = None

    # Build table data
    rows = []
    for p in profile_list:
        status = get_profile_status(p["name"])

        if p["is_active"]:
            has_active = True
            active_profile_name = p["name"]
            active_is_valid = status["valid"]
        if status["valid"]:
            has_any_valid = True

        # Name column (with active indicator) - pad BEFORE coloring
        if p["is_active"]:
            name_text = f"* {p['name']}".ljust(16)
            name_col = click.style(name_text, fg="green", bold=True)
        else:
            name_col = f"  {p['name']}".ljust(16)

        # Status column - use width param to pad before coloring
        status_col = format_status(status, width=12)

        # Email column
        email = p.get("email") or "-"
        if len(email) > 28:
            email = email[:25] + "..."
        email_col = email.ljust(28)

        # Validated column
        validated_col = format_time_ago(p.get("last_validated")).ljust(10)

        rows.append((name_col, status_col, email_col, validated_col, p, status))

    # Print table header
    click.echo()
    click.echo(f"{ 'PROFILE':<16}  { 'STATUS':<12}  { 'EMAIL':<28}  { 'VALIDATED':<10}")
    click.echo("-" * 74)

    # Print rows - columns already padded, just space-separate
    for name_col, status_col, email_col, validated_col, p, status in rows:
        click.echo(f"{name_col}  {status_col}  {email_col}  {validated_col}")

        # Show warning for active invalid profile
        if not status["valid"] and p["is_active"]:
            click.secho(f"  ⚠ Run 'gwsa profiles refresh {p['name']}' to fix.", fg="yellow")

    click.echo("-" * 74)

    # Show guidance using shared function
    show_profile_guidance(
        active_profile_name=active_profile_name,
        active_is_valid=active_is_valid,
        has_any_valid=has_any_valid,
        has_active=has_active
    )


@profiles.command("current")
def current_cmd():
    """Show the currently active profile and its status."""
    from .profiles import get_profile_status, get_active_profile, list_profiles

    profile = get_active_profile()

    if not profile:
        # Check if there are any valid profiles
        profiles = list_profiles()
        has_any_valid = any(get_profile_status(p["name"])["valid"] for p in profiles)
        show_profile_guidance(has_active=False, has_any_valid=has_any_valid)
        return

    # Get status
    status = get_profile_status(profile["name"])

    click.echo(f"\nActive profile: {profile['name']}")

    if profile.get("is_adc"):
        click.echo("  Type: Application Default Credentials (ADC)")
    else:
        click.echo("  Type: OAuth Token")

    click.echo(f"  Status: {format_status(status)}")
    if not status["valid"]:
        click.echo(f"  Reason: {status['reason']}")

    if profile.get("email"):
        click.echo(f"  Email: {profile['email']}")

    scopes = profile.get("scopes", [])
    click.echo(f"  Scopes: {len(scopes)}")

    # Show guidance using shared function
    if not status["valid"]:
        profiles = list_profiles()
        has_any_valid = any(p["name"] != profile["name"] and get_profile_status(p["name"])["valid"]
                          for p in profiles)
        show_profile_guidance(
            active_profile_name=profile["name"],
            active_is_valid=False,
            has_any_valid=has_any_valid,
            has_active=True
        )


@profiles.command("use")
@click.argument("name")
@click.option("--no-recheck", is_flag=True,
              help="Trust cached status without calling Google APIs to re-verify.")
def use_cmd(name, no_recheck):
    """Switch to a different profile.

    NAME is the profile to activate. Use 'adc' for Application Default Credentials.

    By default, calls Google's tokeninfo API to verify credentials are still valid.
    Use --no-recheck to trust the cached validation status instead.
    Either way, the profile must already be listed as valid (not stale or unvalidated).
    """
    from .profiles import get_profile_status
    from .auth.check_access import get_token_info

    if not is_valid_profile_name(name) and name != ADC_PROFILE_NAME:
        click.secho(f"Invalid profile name: {name}", fg="red")
        sys.exit(1)

    # Check profile status using shared validity routine
    status = get_profile_status(name)

    if not status["exists"]:
        click.secho(f"Profile not found: {name}", fg="red")
        click.echo("Use 'gwsa profiles list' to see available profiles.")
        sys.exit(1)

    if not status["valid"]:
        click.secho(f"Error: Profile '{name}' is not valid.", fg="red")
        click.echo(f"  Status: {status['status']}")
        click.echo(f"  Reason: {status['reason']}")
        click.echo(f"\nRun 'gwsa profiles refresh {name}' to re-validate.")
        sys.exit(1)

    # Profile is valid according to cached status
    # If --no-recheck, skip network validation
    if no_recheck:
        if set_active_profile(name):
            click.secho(f"Switched to profile: {name}", fg="green")
            if status["email"]:
                click.echo(f"  Email: {status['email']}")
            click.secho("  (validation skipped due to --no-recheck)", fg="yellow")
        else:
            click.secho(f"Failed to switch to profile: {name}", fg="red")
            sys.exit(1)
        return

    # Perform network validation (tokeninfo call)
    click.echo(f"Validating profile '{name}'...")

    try:
        from gwsa.sdk.auth import get_credentials

        creds, source = get_credentials(profile=name)

        # Refresh if needed
        if not creds.valid:
            from google.auth.transport.requests import Request
            if hasattr(creds, 'refresh_token') and creds.refresh_token:
                creds.refresh(Request())
            else:
                click.secho("Error: Credentials expired and cannot be refreshed.", fg="red")
                click.echo(f"Run 'gwsa profiles refresh {name}' to re-authenticate.")
                sys.exit(1)

        # Call tokeninfo to validate
        token_info = get_token_info(creds)
        email = token_info.get("email")
        scopes = token_info.get("scopes", [])

        # Update cached metadata with fresh validation
        from .profiles import update_profile_metadata
        update_profile_metadata(name, email=email, scopes=scopes)

        if set_active_profile(name):
            click.secho(f"Switched to profile: {name}", fg="green")
            if email:
                click.echo(f"  Email: {email}")
            click.echo(f"  Scopes: {len(scopes)}")
        else:
            click.secho(f"Failed to switch to profile: {name}", fg="red")
            sys.exit(1)

    except Exception as e:
        click.secho(f"Error validating profile: {e}", fg="red")
        click.echo(f"Run 'gwsa profiles refresh {name}' to re-authenticate.")
        sys.exit(1)

@profiles.command("refresh")
@click.argument("name")
def refresh_cmd(name):
    """Re-authenticate an existing profile.

    NAME is the profile to refresh. The profile must already exist.

    For token profiles: Opens a browser for OAuth consent.
    For ADC: Runs 'gcloud auth application-default login'.

    Requires client credentials to be configured first via 'gwsa client import'.
    """
    import os
    import json
    import subprocess
    from .profiles import (
        load_adc_cached_metadata,
        update_adc_cached_metadata,
        get_profile_token_path,
        update_profile_metadata,
    )
    from .auth.check_access import FEATURE_SCOPES, IDENTITY_SCOPES, get_token_info
    from .setup_local import CLIENT_SECRETS_FILE

    # ADC refresh
    if name == ADC_PROFILE_NAME:
        click.echo("Refreshing ADC credentials...")
        click.echo("This will open a browser for Google Cloud authentication.")

        # Build scopes for gcloud command
        all_scopes = {scope for scope_set in FEATURE_SCOPES.values() for scope in scope_set} | IDENTITY_SCOPES
        all_scopes.add("https://www.googleapis.com/auth/cloud-platform")
        scopes_str = ",".join(sorted(list(all_scopes)))
        gcloud_command = ["gcloud", "auth", "application-default", "login", f"--scopes={scopes_str}"]

        # Extract existing quota project before gcloud wipes it
        existing_quota_project = None
        from .profiles import get_adc_quota_project
        try:
            existing_quota_project = get_adc_quota_project()
        except Exception:
            pass

        try:
            result = subprocess.run(gcloud_command, check=True, capture_output=True, text=True)

            if "Cannot find a quota project" in result.stderr:
                if existing_quota_project:
                    click.secho(f"\nℹ️  Notice: Restoring previous quota project ({existing_quota_project}) to the new ADC profile...", fg="cyan")
                    restore_cmd = ["gcloud", "auth", "application-default", "set-quota-project", existing_quota_project]
                    try:
                        subprocess.run(restore_cmd, check=True, capture_output=True, text=True)
                    except subprocess.CalledProcessError as e:
                        click.secho(f"\n❌ Error restoring quota project: {e.stderr}", fg="red")
                        sys.exit(1)
                else:
                    click.secho("\nℹ️  NOTICE: Quota Project Required", fg="cyan", bold=True)
                    click.echo("\nGoogle has authenticated you, but you must set a 'quota project'.")
                    click.echo("Run the following command, replacing YOUR_PROJECT_ID with your project ID:")
                    click.secho("\n  gcloud auth application-default set-quota-project YOUR_PROJECT_ID\n", fg="yellow")
                    click.echo("Then run this command again to complete validation.")
                    sys.exit(1)

            click.echo("gcloud login successful. Validating credentials...")

            # Validate and cache
            import google.auth
            from google.auth.transport.requests import Request

            creds, project = google.auth.default()
            if not creds.valid:
                creds.refresh(Request())

            token_info = get_token_info(creds)
            email = token_info.get("email")
            scopes = token_info.get("scopes", [])

            update_adc_cached_metadata(email=email, scopes=scopes)

            click.secho(f"\nADC profile refreshed successfully!", fg="green")
            if email:
                click.echo(f"  Email: {email}")
            click.echo(f"  Scopes: {len(scopes)}")

        except subprocess.CalledProcessError as e:
            click.secho(f"gcloud command failed: {e.stderr}", fg="red")
            sys.exit(1)
        except FileNotFoundError:
            click.secho("Error: gcloud not found. Please install Google Cloud SDK.", fg="red")
            sys.exit(1)
        except Exception as e:
            click.secho(f"Error refreshing ADC: {e}", fg="red")
            sys.exit(1)

        return

    # Token profile refresh
    if not is_valid_profile_name(name):
        click.secho(f"Invalid profile name: {name}", fg="red")
        sys.exit(1)

    if not profile_exists(name):
        click.secho(f"Profile not found: {name}", fg="red")
        click.echo("Use 'gwsa profiles add' to create a new profile.")
        sys.exit(1)

    # Check client secrets exist
    if not os.path.exists(CLIENT_SECRETS_FILE):
        click.secho("Client credentials not configured.", fg="red")
        click.echo("\nTo configure:")
        click.echo("  gwsa client import /path/to/client_secrets.json")
        sys.exit(1)

    # Collect all scopes
    all_scopes = list({scope for scope_set in FEATURE_SCOPES.values() for scope in scope_set} | IDENTITY_SCOPES)

    click.echo(f"Refreshing profile '{name}'...")
    click.echo("A browser window will open for authentication.")

    try:
        from google_auth_oauthlib.flow import InstalledAppFlow
        import tempfile
        import shutil

        flow = InstalledAppFlow.from_client_secrets_file(CLIENT_SECRETS_FILE, all_scopes)
        creds = flow.run_local_server(port=0)

        # FIRST: Validate with tokeninfo before making any changes
        # If this fails, we haven't touched the existing profile
        click.echo("Validating new credentials...")
        token_info = get_token_info(creds)
        email = token_info.get("email")
        scopes = token_info.get("scopes", [])

        if not email:
            click.secho("Error: Could not retrieve email from credentials.", fg="red")
            click.echo("Your existing profile has not been modified.")
            sys.exit(1)

        # Prepare token data
        token_data = json.loads(creds.to_json())
        token_data["type"] = "authorized_user"

        # Write to temp file first, then atomic move
        token_path = get_profile_token_path(name)
        temp_fd, temp_path = tempfile.mkstemp(dir=token_path.parent, suffix='.tmp')
        try:
            with os.fdopen(temp_fd, 'w') as f:
                json.dump(token_data, f, indent=2)
            # Atomic replace
            shutil.move(temp_path, token_path)
        except Exception:
            # Clean up temp file if move failed
            if os.path.exists(temp_path):
                os.remove(temp_path)
            raise

        # Update metadata (only after token file is successfully written)
        update_profile_metadata(name, email=email, scopes=scopes)

        click.secho(f"\nProfile '{name}' refreshed successfully!", fg="green")
        click.echo(f"  Email: {email}")
        click.echo(f"  Scopes: {len(scopes)}")

    except Exception as e:
        click.secho(f"Error refreshing profile: {e}", fg="red")
        click.echo("Your existing profile has not been modified.")
        sys.exit(1)


@profiles.command("add")
@click.argument("name")
def add_cmd(name):
    """Create a new token profile.

    NAME is the profile name (alphanumeric, hyphens, underscores allowed).
    The profile must NOT already exist. Use 'refresh' to update existing profiles.

    This will open a browser for OAuth consent.

    Requires client credentials to be configured first via 'gwsa client import'.
    """
    import json
    from google_auth_oauthlib.flow import InstalledAppFlow
    from .auth.check_access import FEATURE_SCOPES, IDENTITY_SCOPES, get_token_info
    from .setup_local import CLIENT_SECRETS_FILE
    import os

    if name == ADC_PROFILE_NAME:
        click.secho("Cannot add 'adc' - it is a built-in profile.", fg="red")
        click.echo("Use 'gwsa profiles refresh adc' to re-authenticate ADC.")
        sys.exit(1)

    if not is_valid_profile_name(name):
        click.secho(f"Invalid profile name: {name}", fg="red")
        click.echo("Use alphanumeric characters, hyphens, or underscores (1-32 chars).")
        sys.exit(1)

    if profile_exists(name):
        click.secho(f"Profile already exists: {name}", fg="red")
        click.echo("Use 'gwsa profiles refresh' to re-authenticate existing profiles.")
        sys.exit(1)

    # Check client secrets exist
    if not os.path.exists(CLIENT_SECRETS_FILE):
        click.secho("Client credentials not configured.", fg="red")
        click.echo("\nTo configure:")
        click.echo("  gwsa client import /path/to/client_secrets.json")
        sys.exit(1)

    # Collect all scopes
    all_scopes = list({scope for scope_set in FEATURE_SCOPES.values() for scope in scope_set} | IDENTITY_SCOPES)

    click.echo(f"Creating profile '{name}'...")
    click.echo("A browser window will open for authentication.")

    try:
        flow = InstalledAppFlow.from_client_secrets_file(CLIENT_SECRETS_FILE, all_scopes)
        creds = flow.run_local_server(port=0)

        # FIRST: Validate with tokeninfo before creating profile
        # If this fails, no profile is created
        click.echo("Validating credentials...")
        token_info = get_token_info(creds)
        email = token_info.get("email")
        scopes = token_info.get("scopes", [])

        if not email:
            click.secho("Error: Could not retrieve email from credentials.", fg="red")
            click.echo("No profile was created.")
            sys.exit(1)

        # Prepare token data
        token_data = json.loads(creds.to_json())
        token_data["type"] = "authorized_user"

        # Create profile only after validation succeeds
        if create_profile(name, token_data, email=email, scopes=scopes):
            click.secho(f"\nProfile '{name}' created successfully!", fg="green")
            click.echo(f"  Email: {email}")
            click.echo(f"  Scopes: {len(scopes)}")
            click.echo(f"\nTo use this profile: gwsa profiles use {name}")
        else:
            click.secho(f"Failed to create profile: {name}", fg="red")
            sys.exit(1)

    except Exception as e:
        click.secho(f"Error creating profile: {e}", fg="red")
        click.echo("No profile was created.")
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


@profiles.command("rename")
@click.argument("old_name")
@click.argument("new_name")
def rename_cmd(old_name, new_name):
    """Rename a profile.

    OLD_NAME is the current profile name.
    NEW_NAME is the new name for the profile.

    Cannot rename the built-in 'adc' profile.
    """
    import shutil
    import yaml

    # Fail fast: can't rename ADC
    if old_name == ADC_PROFILE_NAME:
        click.secho("Cannot rename built-in 'adc' profile.", fg="red")
        sys.exit(1)

    # Fail fast: can't rename TO adc
    if new_name == ADC_PROFILE_NAME:
        click.secho("Cannot use reserved name 'adc'.", fg="red")
        sys.exit(1)

    # Fail fast: invalid new name
    if not is_valid_profile_name(new_name):
        click.secho(f"Invalid profile name: {new_name}", fg="red")
        click.echo("Use alphanumeric characters, hyphens, or underscores (1-32 chars).")
        sys.exit(1)

    # Fail fast: source doesn't exist
    if not profile_exists(old_name):
        click.secho(f"Profile not found: {old_name}", fg="red")
        sys.exit(1)

    # Fail fast: target already exists
    if profile_exists(new_name):
        click.secho(f"Profile already exists: {new_name}", fg="red")
        sys.exit(1)

    # Get paths
    old_dir = get_profile_dir(old_name)
    new_dir = get_profile_dir(new_name)

    # Check if this is the active profile
    active = get_active_profile_name()
    was_active = (active == old_name)

    # Atomic operation: rename folder first
    try:
        shutil.move(str(old_dir), str(new_dir))
    except Exception as e:
        click.secho(f"Failed to rename profile folder: {e}", fg="red")
        sys.exit(1)

    # If this was the active profile, update config
    if was_active:
        try:
            config_path = get_config_file_path()
            with open(config_path, 'r') as f:
                config = yaml.safe_load(f) or {}
            config['active_profile'] = new_name
            with open(config_path, 'w') as f:
                yaml.safe_dump(config, f, default_flow_style=False)
        except Exception as e:
            # Rollback: rename folder back
            click.secho(f"Failed to update config, rolling back: {e}", fg="red")
            try:
                shutil.move(str(new_dir), str(old_dir))
            except Exception:
                click.secho("CRITICAL: Rollback failed. Manual recovery may be needed.", fg="red")
            sys.exit(1)

    click.secho(f"Profile '{old_name}' renamed to '{new_name}'.", fg="green")
    if was_active:
        click.echo(f"Active profile updated to '{new_name}'.")


@profiles.command("export")
@click.argument("name", required=False)
def export_cmd(name):
    """Export the credentials for a profile to stdout.

    NAME is the profile to export. If omitted, uses the active profile.
    This outputs the raw JSON content of the credential file, suitable for
    saving to a file (e.g. > creds.json) for use with GOOGLE_APPLICATION_CREDENTIALS.

    For 'adc', it attempts to locate the system-wide application default credentials.
    """
    if not name:
        name = get_active_profile_name()
        if not name:
            click.secho("No active profile selected. Please specify a profile name.", fg="red")
            sys.exit(1)

    if name == ADC_PROFILE_NAME:
        # Standard gcloud ADC location
        if sys.platform == "win32":
            adc_path = Path(os.environ.get("APPDATA", "")) / "gcloud" / "application_default_credentials.json"
        else:
            adc_path = Path.home() / ".config" / "gcloud" / "application_default_credentials.json"
        
        if not adc_path.exists():
            click.secho(f"Error: ADC credentials file not found at {adc_path}", fg="red")
            click.echo("Run 'gcloud auth application-default login' to create it.")
            sys.exit(1)
        
        token_path = adc_path
    else:
        if not profile_exists(name):
            click.secho(f"Profile not found: {name}", fg="red")
            sys.exit(1)

        token_path = get_profile_token_path(name)
        if not token_path.exists():
            click.secho(f"Error: Credential file missing for profile '{name}'.", fg="red")
            sys.exit(1)

    # Read and dump to stdout
    try:
        with open(token_path, 'r') as f:
            click.echo(f.read())
    except Exception as e:
        click.secho(f"Error reading credential file: {e}", fg="red")
        sys.exit(1)
