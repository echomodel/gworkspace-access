"""CLI commands for profile management."""

import sys
import click
import json
import os
import shutil
from pathlib import Path

from .profiles import (
    list_profiles,
    get_active_profile_name,
    set_active_profile,
    profile_exists,
    delete_profile,
    create_profile,
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

    NAME is the profile to activate.

    By default, calls Google's tokeninfo API to verify credentials are still valid.
    Use --no-recheck to trust the cached validation status instead.
    Either way, the profile must already be listed as valid (not stale or unvalidated).
    """
    from .profiles import get_profile_status
    from .auth.check_access import get_token_info

    if not is_valid_profile_name(name):
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
@click.option("--basic-scopes/--all-scopes", default=False, 
              help="Only request basic identity and cloud-platform scopes (useful for orgs that block Workspace scopes)")
def refresh_cmd(name, basic_scopes):
    """Re-authenticate an existing profile.

    NAME is the profile to refresh. The profile must already exist.

    For token profiles: Opens a browser for OAuth consent.
    For ADC: Runs 'gcloud auth application-default login'.

    Requires client credentials to be configured first via 'gwsa client import'.
    """
    import os
    import json
    import subprocess
    from .profiles import load_profile_metadata, update_profile_metadata
    from .auth.check_access import FEATURE_SCOPES, IDENTITY_SCOPES, get_token_info
    from .setup_local import CLIENT_SECRETS_FILE

    if not is_valid_profile_name(name):
        click.secho(f"Invalid profile name: {name}", fg="red")
        sys.exit(1)

    if not profile_exists(name):
        click.secho(f"Profile not found: {name}", fg="red")
        click.echo("Use 'gwsa profiles add' to create a new profile.")
        sys.exit(1)

    metadata = load_profile_metadata(name)
    profile_type = metadata.get("type", "oauth")

    click.echo(f"Refreshing {profile_type.upper()} profile '{name}'...")
    click.echo("A browser window will open for authentication.")

    try:
        import tempfile
        import shutil
        from google.oauth2.credentials import Credentials

        # Work in a temp file so we don't destroy the current token until validation succeeds
        token_path = get_profile_token_path(name)
        temp_fd, temp_path = tempfile.mkstemp(dir=token_path.parent, suffix='.tmp')
        os.close(temp_fd)

        if profile_type == "adc":
            # Backup central ADC file to prevent gcloud from clobbering it
            central_adc = Path.home() / ".config" / "gcloud" / "application_default_credentials.json"
            backup_path = None
            if central_adc.exists():
                backup_path = central_adc.with_suffix(".json.gwsa-backup")
                shutil.copy2(str(central_adc), str(backup_path))

            try:
                if basic_scopes:
                    all_scopes = list(IDENTITY_SCOPES)
                    click.echo("Using basic identity scopes only.")
                else:
                    all_scopes = list({scope for scope_set in FEATURE_SCOPES.values() for scope in scope_set} | IDENTITY_SCOPES)
                    
                all_scopes.append("https://www.googleapis.com/auth/cloud-platform")
                scopes_str = ",".join(sorted(set(all_scopes)))
                
                login_cmd = [
                    "gcloud", "auth", "application-default", "login",
                    f"--scopes={scopes_str}",
                ]
                click.echo("Running gcloud to refresh Application Default Credentials...")
                result = subprocess.run(login_cmd)
                if result.returncode != 0:
                    click.secho("Error: gcloud auth application-default login failed.", fg="red")
                    sys.exit(1)
                
                # Rehydrate existing quota project from the old token file
                with open(token_path, 'r') as f:
                    old_token = json.load(f)
                existing_quota = old_token.get("quota_project_id")
                
                if existing_quota:
                    click.echo(f"Restoring quota project '{existing_quota}'...")
                    quota_cmd = ["gcloud", "auth", "application-default", "set-quota-project", existing_quota]
                    result = subprocess.run(quota_cmd)
                    if result.returncode != 0:
                        click.secho(f"Warning: Failed to restore quota project '{existing_quota}'.", fg="yellow")

                # Load the new token from the central ADC path, then save to our temporary validate path
                with open(central_adc, 'r') as f:
                    token_data = json.load(f)
                creds = Credentials.from_authorized_user_info(token_data)
                
                with open(temp_path, 'w') as f:
                    json.dump(token_data, f, indent=2)

            finally:
                # Restore the original central ADC file
                if backup_path and backup_path.exists():
                    shutil.move(str(backup_path), str(central_adc))
                    click.echo("Restored original central ADC credentials.")
                elif not backup_path:
                    # There was no original file; remove the one gcloud created
                    if central_adc.exists():
                        central_adc.unlink()

        else:
            # OAuth flow
            if not os.path.exists(CLIENT_SECRETS_FILE):
                click.secho("Client credentials not configured.", fg="red")
                click.echo("\nTo configure:")
                click.echo("  gwsa client import /path/to/client_secrets.json")
                sys.exit(1)

            from google_auth_oauthlib.flow import InstalledAppFlow
            all_scopes = list({scope for scope_set in FEATURE_SCOPES.values() for scope in scope_set} | IDENTITY_SCOPES)
            flow = InstalledAppFlow.from_client_secrets_file(CLIENT_SECRETS_FILE, all_scopes)
            creds = flow.run_local_server(port=0)

            token_data = json.loads(creds.to_json())
            token_data["type"] = "authorized_user"
            with open(temp_path, 'w') as f:
                json.dump(token_data, f, indent=2)

        # Validate with tokeninfo
        click.echo("Validating new credentials...")
        token_info = get_token_info(creds)
        email = token_info.get("email")
        scopes = token_info.get("scopes", [])

        if not email:
            click.secho("Error: Could not retrieve email from credentials or missing email scope.", fg="red")
            if os.path.exists(temp_path):
                os.remove(temp_path)
            sys.exit(1)

        # Atomic replace of the token file
        shutil.move(temp_path, token_path)

        # Update metadata
        update_profile_metadata(name, email=email, scopes=scopes)

        click.secho(f"\nProfile '{name}' refreshed successfully!", fg="green")
        click.echo(f"  Email: {email}")
        click.echo(f"  Scopes: {len(scopes)}")

    except Exception as e:
        click.secho(f"Error refreshing profile: {e}", fg="red")
        click.echo("Your existing profile has not been modified.")
        if 'temp_path' in locals() and os.path.exists(temp_path):
            os.remove(temp_path)
        sys.exit(1)


@profiles.command("add")
@click.argument("name")
@click.option("--type", "profile_type", type=click.Choice(["oauth", "adc"]), default="oauth", help="Type of profile to create.")
@click.option("--quota-project", help="Quota project to apply (required for ADC profiles).")
@click.option("--basic-scopes/--all-scopes", default=False, 
              help="Only request basic identity and cloud-platform scopes (useful for orgs that block Workspace scopes)")
def add_cmd(name, profile_type, quota_project, basic_scopes):
    """Add a new Google identity profile to the vault.

    This creates a new profile context for authentication.
    The profile must NOT already exist. Use 'refresh' to update existing profiles.

    If --type=oauth (default), opens a browser for standard OAuth consent.
    If --type=adc, runs gcloud auth application-default login to create an isolated token.
    """
    import json
    import os
    import tempfile
    import subprocess
    from google_auth_oauthlib.flow import InstalledAppFlow
    from google.oauth2.credentials import Credentials
    from .auth.check_access import FEATURE_SCOPES, IDENTITY_SCOPES, get_token_info
    from .setup_local import CLIENT_SECRETS_FILE
    from gwsa.sdk.profiles import ProfileType

    if not is_valid_profile_name(name):
        click.secho(f"Invalid profile name: {name}", fg="red")
        click.echo("Use alphanumeric characters, hyphens, or underscores (1-32 chars).")
        sys.exit(1)

    if profile_exists(name):
        click.secho(f"Profile already exists: {name}", fg="red")
        click.echo("Use 'gwsa profiles refresh' to re-authenticate existing profiles.")
        sys.exit(1)

    if profile_type == "adc" and not quota_project:
        click.secho("Error: --quota-project is required when creating an ADC profile.", fg="red")
        sys.exit(1)

    # Check client secrets exist (only required for OAuth)
    if profile_type == "oauth" and not os.path.exists(CLIENT_SECRETS_FILE):
        click.secho("Client credentials not configured.", fg="red")
        click.echo("\nTo configure:")
        click.echo("  gwsa client import /path/to/client_secrets.json")
        sys.exit(1)

    # Collect all scopes (cloud-platform is required for ADC)
    if basic_scopes:
        all_scopes = list(IDENTITY_SCOPES)
        click.echo("Using basic identity scopes only.")
    else:
        all_scopes = list({scope for scope_set in FEATURE_SCOPES.values() for scope in scope_set} | IDENTITY_SCOPES)
        
    all_scopes.append("https://www.googleapis.com/auth/cloud-platform")
    all_scopes = sorted(set(all_scopes))

    click.echo(f"Creating {profile_type.upper()} profile '{name}'...")
    click.echo("A browser window will open for authentication.")

    try:
        if profile_type == "adc":
            # gcloud always writes to the central ADC location, so we
            # backup the existing file, let gcloud write, copy to vault,
            # then restore the original.
            central_adc = Path.home() / ".config" / "gcloud" / "application_default_credentials.json"
            backup_path = None
            if central_adc.exists():
                backup_path = central_adc.with_suffix(".json.gwsa-backup")
                shutil.copy2(str(central_adc), str(backup_path))

            try:
                scopes_str = ",".join(all_scopes)
                login_cmd = [
                    "gcloud", "auth", "application-default", "login",
                    f"--scopes={scopes_str}",
                ]
                click.echo("Running gcloud to generate Application Default Credentials...")
                result = subprocess.run(login_cmd)
                if result.returncode != 0:
                    click.secho("Error: gcloud auth application-default login failed.", fg="red")
                    sys.exit(1)

                # Set quota project
                click.echo(f"Setting quota project to '{quota_project}'...")
                quota_cmd = [
                    "gcloud", "auth", "application-default", "set-quota-project", quota_project
                ]
                result = subprocess.run(quota_cmd)
                if result.returncode != 0:
                    click.secho("Error: Failed to set quota project.", fg="red")
                    sys.exit(1)

                # Read the generated file from the central location
                with open(central_adc, 'r') as f:
                    token_data = json.load(f)
                creds = Credentials.from_authorized_user_info(token_data)
            finally:
                # Restore the original central ADC file
                if backup_path and backup_path.exists():
                    shutil.move(str(backup_path), str(central_adc))
                    click.echo("Restored original central ADC credentials.")
                elif not backup_path:
                    # There was no original file; remove the one gcloud created
                    if central_adc.exists():
                        central_adc.unlink()
        else:
            # OAuth flow
            flow = InstalledAppFlow.from_client_secrets_file(CLIENT_SECRETS_FILE, all_scopes)
            creds = flow.run_local_server(port=0)
            token_data = json.loads(creds.to_json())
            token_data["type"] = "authorized_user"

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

        # Create profile only after validation succeeds
        ptype = ProfileType.ADC if profile_type == "adc" else ProfileType.OAUTH
        if create_profile(name, token_data, profile_type=ptype, email=email, scopes=scopes):
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

    NAME is the profile to delete.
    """
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

    """
    import shutil
    import yaml

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
    """
    if not name:
        name = get_active_profile_name()
        if not name:
            click.secho("No active profile selected. Please specify a profile name.", fg="red")
            sys.exit(1)

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
@profiles.command("apply")
@click.argument("name", required=False)
def apply_cmd(name):
    """Apply a profile's credentials to the global gcloud ADC path.

    NAME is the profile to apply. If omitted, uses the active profile.
    This copies the profile's credential file to the standard gcloud location
    (~/.config/gcloud/application_default_credentials.json), making it the
    default identity for all standard Google Cloud SDKs and tools on this machine.
    """
    if not name:
        name = get_active_profile_name()
        if not name:
            click.secho("No active profile selected. Please specify a profile name.", fg="red")
            sys.exit(1)

    if not profile_exists(name):
        click.secho(f"Profile not found: {name}", fg="red")
        sys.exit(1)

    token_path = get_profile_token_path(name)
    if not token_path.exists():
        click.secho(f"Error: Credential file missing for profile '{name}'.", fg="red")
        sys.exit(1)

    # Determine global gcloud ADC path
    central_adc_dir = Path.home() / ".config" / "gcloud"
    central_adc_file = central_adc_dir / "application_default_credentials.json"
    
    # Ensure directory exists
    central_adc_dir.mkdir(parents=True, exist_ok=True)
    
    import shutil
    try:
        shutil.copy2(str(token_path), str(central_adc_file))
        click.secho(f"Successfully applied profile '{name}' to global gcloud ADC.", fg="green")
        click.echo(f"  Target: {central_adc_file}")
    except Exception as e:
        click.secho(f"Error applying profile to global ADC path: {e}", fg="red")
        sys.exit(1)
