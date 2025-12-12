import os
import logging
import hashlib
import json
from pathlib import Path
from typing import Tuple, Dict, Optional
from datetime import datetime

# Import mail related constants from the mail package's __init__.py
from .mail import USER_TOKEN_FILE
from .auth.check_access import get_active_credentials, REQUIRED_SCOPES, get_token_info, get_token_scopes, get_feature_status, test_apis, IDENTITY_SCOPES
from .config import get_config_value, set_config_value, get_config_file_path

# --- Setup Logging ---
# Only configure basicConfig if a handler has not already been added
# This prevents re-configuring logging if a parent script (like a CLI) already set it up.
if not logging.root.handlers:
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(levelname)s - %(message)s'
    )
logger = logging.getLogger(__name__)

# Use ~/.config/gworkspace-access for storing credentials
_CONFIG_DIR = os.path.expanduser("~/.config/gworkspace-access")
CLIENT_SECRETS_FILE = os.path.join(_CONFIG_DIR, "client_secrets.json")


def hash_file(filepath: Path, truncate: int = 8) -> str:
    """Create a short hash of file contents"""
    try:
        with open(filepath, 'r') as f:
            content = f.read()
        return hashlib.sha256(content.encode()).hexdigest()[:truncate]
    except Exception:
        return "ERROR"


def load_json_safe(filepath: Path) -> Dict:
    """Safely load JSON file"""
    try:
        with open(filepath, 'r') as f:
            return json.load(f)
    except json.JSONDecodeError:
        return {"error": f"Invalid JSON in {filepath}"}
    except Exception as e:
        return {"error": str(e)}


def check_client_config(status_only: bool = False) -> Tuple[bool, Dict]:
    """Check client application configuration"""
    gwa_dir = Path(_CONFIG_DIR)

    if not gwa_dir.exists():
        return False, {
            "status": "NOT FOUND",
            "message": f"gworkspace-access directory not found at {gwa_dir}",
        }

    client_secrets_path = gwa_dir / 'client_secrets.json'

    if not client_secrets_path.exists():
        return False, {
            "status": "MISSING",
            "message": "client_secrets.json not found",
        }

    client_secrets = load_json_safe(client_secrets_path)
    creds_hash = hash_file(client_secrets_path)
    project_id = client_secrets.get('installed', {}).get('project_id', 'UNKNOWN')
    client_id = client_secrets.get('installed', {}).get('client_id', 'UNKNOWN')[:20]

    if 'error' in client_secrets:
        return False, {
            "status": "PARSE ERROR",
            "error": client_secrets['error'],
            "client_creds_hash": creds_hash,
            "project_id": project_id
        }

    status_indicator = "VERIFIED" if status_only else "READY"
    return True, {
        "status": status_indicator,
        "client_secrets_file": str(client_secrets_path),
        "client_creds_hash": creds_hash,
        "project_id": project_id,
        "client_id_prefix": client_id,
        "scopes": client_secrets.get('installed', {}).get('scopes', [])
    }


def check_user_credentials(status_only: bool = False) -> Tuple[bool, Dict]:
    """Check user credential status"""
    gwa_dir = Path(_CONFIG_DIR)

    if not gwa_dir.exists():
        return False, {
            "status": "NOT FOUND",
            "message": f"gworkspace-access directory not found at {gwa_dir}",
        }

    user_token_path = gwa_dir / 'user_token.json'

    if not user_token_path.exists():
        return False, {
            "status": "MISSING",
            "user_token_path": str(user_token_path),
            "message": "user_token.json not found - run 'gwsa setup' to authenticate"
        }

    user_token = load_json_safe(user_token_path)
    token_hash = hash_file(user_token_path)

    if 'error' in user_token:
        return False, {
            "status": "PARSE ERROR",
            "user_token_path": str(user_token_path),
            "user_token_hash": token_hash,
            "error": user_token['error']
        }

    status_indicator = "VERIFIED" if status_only else "READY"
    return True, {
        "status": status_indicator,
        "user_token_path": str(user_token_path),
        "user_token_hash": token_hash,
        "scopes": user_token.get('scopes', []),
        "expiry": user_token.get('expiry', 'UNKNOWN')
    }



def ensure_user_token_json(new_user: bool = False):
    """
    Ensures user_token.json is present and valid, performing OAuth flow if necessary.
    This function will be interactive via a browser.

    When performing a new OAuth flow, requests all feature scopes (mail, sheets, docs, drive)
    so the resulting token can be used for all gwsa features.

    :param new_user: If True, force a new OAuth flow by deleting any existing user_token.json.
    :return: The loaded/created credentials object on success, None on failure.
    """
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials
    from google_auth_oauthlib.flow import InstalledAppFlow
    from .auth.check_access import FEATURE_SCOPES

    # Collect all scopes from all features plus identity scopes for a complete token
    all_scopes = list({scope for scope_set in FEATURE_SCOPES.values() for scope in scope_set} | IDENTITY_SCOPES)

    # Ensure config directory exists
    os.makedirs(_CONFIG_DIR, exist_ok=True)
    logger.debug(f"Ensured config directory exists: {_CONFIG_DIR}")

    logger.info(f"Ensuring user credentials ({USER_TOKEN_FILE})...")

    if new_user and os.path.exists(USER_TOKEN_FILE):
        os.remove(USER_TOKEN_FILE)
        logger.info(f"Removed existing {USER_TOKEN_FILE} due to --new-user flag.")

    creds = None
    if os.path.exists(USER_TOKEN_FILE):
        logger.debug(f"Found {USER_TOKEN_FILE}. Attempting to load user credentials.")
        try:
            creds = Credentials.from_authorized_user_file(USER_TOKEN_FILE, all_scopes)
            logger.debug("User credentials loaded.")
        except Exception as e:
            logger.warning(f"Failed to load user credentials from {USER_TOKEN_FILE}: {e}")
            creds = None # Force re-auth
    else:
        logger.debug(f"{USER_TOKEN_FILE} not found. Will proceed with new user authorization flow.")

    if not creds or not creds.valid:
        logger.debug("User credentials not valid or not found. Checking for expiration/refresh.")
        if creds and creds.expired and creds.refresh_token:
            logger.info("User credentials expired, attempting to refresh token.")
            try:
                creds.refresh(Request())
                logger.info("User token refreshed successfully.")
            except Exception as e:
                logger.warning(f"Failed to refresh token: {e}. Initiating new authorization flow.")
                creds = None # Force new auth flow if refresh fails

        if not creds: # If refresh failed or creds were never valid
            logger.info("Initiating new user authorization flow via browser.")
            if not os.path.exists(CLIENT_SECRETS_FILE):
                logger.error(f"Error: Client credentials file '{CLIENT_SECRETS_FILE}' not found.")
                logger.error("Cannot initiate user authorization flow without client credentials.")
                logger.error(f"Please ensure '{CLIENT_SECRETS_FILE}' is present (run 'gwsa setup' first if needed).")
                return None

            try:
                flow = InstalledAppFlow.from_client_secrets_file(
                    CLIENT_SECRETS_FILE, all_scopes
                )
                creds = flow.run_local_server(port=0) # Port 0 for dynamic port
                logger.info("New user authorization completed via browser.")
            except Exception as e:
                logger.error(f"Failed to complete new user authorization flow: {e}")
                return None

        # Save token with type field for ADC compatibility
        token_data = json.loads(creds.to_json())
        token_data["type"] = "authorized_user"
        with open(USER_TOKEN_FILE, "w") as token:
            json.dump(token_data, token, indent=2)
        logger.debug(f"User credentials saved to {USER_TOKEN_FILE}.")
    else:
        logger.info("User credentials are valid.")

    return creds


def create_token_for_scopes(client_creds_path: str, output_path: str, scopes: list[str]) -> bool:
    """
    Create a new OAuth token for the specified scopes and save it to the output path.

    This function performs a fresh OAuth flow using the provided client credentials
    and saves the resulting token to the specified output location. It does NOT
    touch the gwsa configuration or the standard user_token.json.

    :param client_creds_path: Path to the client_secrets.json (OAuth client credentials)
    :param output_path: Path where the new user_token.json should be saved
    :param scopes: List of Google API scopes to request
    :return: True if successful, False otherwise
    """
    from google_auth_oauthlib.flow import InstalledAppFlow

    if not os.path.exists(client_creds_path):
        logger.error(f"Error: Client credentials file not found: {client_creds_path}")
        return False

    if not scopes:
        logger.error("Error: At least one scope must be specified")
        return False

    # Ensure the output directory exists
    output_dir = os.path.dirname(output_path)
    if output_dir:
        os.makedirs(output_dir, exist_ok=True)
        logger.debug(f"Ensured output directory exists: {output_dir}")

    logger.info(f"Creating OAuth token for scopes: {scopes}")
    logger.info(f"Using client credentials: {client_creds_path}")
    logger.info(f"Output token file: {output_path}")

    try:
        flow = InstalledAppFlow.from_client_secrets_file(
            client_creds_path, scopes
        )
        creds = flow.run_local_server(port=0)
        logger.info("User authorization completed via browser.")

        # Save token with type field for ADC compatibility
        token_data = json.loads(creds.to_json())
        token_data["type"] = "authorized_user"
        with open(output_path, "w") as token_file:
            json.dump(token_data, token_file, indent=2)
        logger.info(f"Token saved to {output_path}")

        return True
    except Exception as e:
        logger.error(f"Failed to complete OAuth flow: {e}")
        return False

def print_status_table(title: str, status_ok: bool, data: Dict, status_only: bool = False, action_performed: bool = False) -> None:
    """Print a formatted status table with action indicator and unique icons.

    In setup mode (status_only=False):
    - ✓ [VERIFIED] when configuration is complete and valid, no action needed
    - ✔ [COMPLETED] when we just performed a setup action in this execution

    In status-only mode (status_only=True):
    - ✓ [VERIFIED] when configuration is complete and valid, no action would be needed
    - ◐ [NEEDED] when something would be set up if not in status-only mode
    - ✗ [MISSING] when configuration is missing entirely
    """
    import click

    # Determine the action indicator and icon
    if status_ok:
        if action_performed:
            if status_only:
                action_indicator = "NEEDED"
                status_symbol = "◐"  # Partially filled circle for "would be set"
            else:
                action_indicator = "COMPLETED"
                status_symbol = "✔"  # Check mark for completed
        else:
            action_indicator = "VERIFIED"
            status_symbol = "✓"  # Check for verified
    else:
        if status_only:
            action_indicator = "MISSING"
        else:
            action_indicator = data.get("status", "MISSING")
        status_symbol = "✗"  # X for missing/error

    click.echo(f"\n{status_symbol} {title} [{action_indicator}]")
    click.echo("=" * 50)

    for key, value in data.items():
        if key == "status":
            continue  # Skip status as we already displayed it
        if isinstance(value, list):
            value = ", ".join(value) if value else "(none)"
        elif value is None:
            value = "(not set)"

        click.echo(f"  {key:<30} {str(value):<45}")

    click.echo("=" * 80)


def _atomic_client_creds_setup(client_creds_path_str: str, force_new_user: bool) -> bool:
    """
    Handles the --client-creds setup atomically.

    Requests all feature scopes (mail, sheets, docs, drive) during the OAuth flow
    so the resulting token can be used for all gwsa features.
    """
    import tempfile
    import shutil
    from google_auth_oauthlib.flow import InstalledAppFlow
    from .auth.check_access import FEATURE_SCOPES

    provided_creds_path = Path(client_creds_path_str)
    if not provided_creds_path.exists():
        logger.error(f"Error: Client secrets file not found: {client_creds_path_str}")
        return False

    temp_dir = Path(tempfile.mkdtemp(dir=_CONFIG_DIR))
    temp_client_secrets = temp_dir / "client_secrets.json"
    temp_user_token = temp_dir / "user_token.json"

    # Collect all scopes from all features plus identity scopes for a complete token
    all_scopes = list({scope for scope_set in FEATURE_SCOPES.values() for scope in scope_set} | IDENTITY_SCOPES)

    try:
        shutil.copy(provided_creds_path, temp_client_secrets)
        logger.info(f"Staged new client secrets to temporary file: {temp_client_secrets}")

        logger.info("Initiating new user authorization flow via browser...")
        flow = InstalledAppFlow.from_client_secrets_file(str(temp_client_secrets), all_scopes)
        creds = flow.run_local_server(port=0)
        logger.info("New user authorization completed successfully.")

        token_data = json.loads(creds.to_json())
        token_data["type"] = "authorized_user"
        with open(temp_user_token, "w") as token_file:
            json.dump(token_data, token_file, indent=2)
        logger.info(f"Staged new user token to temporary file: {temp_user_token}")

        # --- Atomic Commit ---
        logger.info("Committing new credentials...")
        shutil.move(str(temp_client_secrets), CLIENT_SECRETS_FILE)
        shutil.move(str(temp_user_token), USER_TOKEN_FILE)
        logger.info("Successfully replaced old credentials with new ones.")

        return True

    except Exception as e:
        logger.error(f"Failed to complete OAuth flow: {e}")
        logger.error("Your old credentials (if any) have been left untouched.")
        return False
    finally:
        if temp_dir.exists():
            shutil.rmtree(temp_dir)
            logger.debug(f"Cleaned up temporary directory: {temp_dir}")

def _get_status_report(deep_check: bool = False) -> Dict:
    """
    Gathers all status information and returns it as a dictionary.
    This function contains the core logic and is designed to be tested.
    """
    config_file = get_config_file_path()
    if not config_file.exists():
        return {"status": "NOT_CONFIGURED"}

    auth_mode = get_config_value("auth.mode")
    if not auth_mode:
        return {"status": "NOT_CONFIGURED"}

    report = {"status": "CONFIGURED", "mode": auth_mode}

    try:
        creds, source = get_active_credentials()
        report["source"] = source
        report["creds_valid"] = creds.valid
        report["creds_expired"] = creds.expired
        report["creds_refreshable"] = hasattr(creds, 'refresh_token') and creds.refresh_token is not None

        try:
            token_info = get_token_info(creds)
            granted_scopes = set(token_info["scopes"])
            report["user_email"] = token_info.get("email")
            report["scope_validation_error"] = None
            report["feature_status"] = get_feature_status(granted_scopes)
        except Exception as e:
            report["scope_validation_error"] = str(e)
            report["feature_status"] = {}

        if deep_check:
            apis_to_test = [f for f, supported in report.get("feature_status", {}).items() if supported]
            if apis_to_test:
                try:
                    report["api_results"] = test_apis(creds, only=apis_to_test)
                    report["api_error"] = None
                except Exception as e:
                    report["api_results"] = {}
                    report["api_error"] = str(e)
            else:
                report["api_results"] = {}
                report["api_error"] = None

    except Exception as e:
        report["status"] = "ERROR"
        report["error_details"] = str(e)

    return report

def _display_status_report(report: Dict, is_ready: bool):
    """
    Takes a status report dictionary and prints it to the console with rich formatting.
    """
    import click

    click.secho("\nGoogle Workspace Access (gwsa)", fg="blue")
    click.secho("------------------------------", fg="blue")

    if report["status"] == "NOT_CONFIGURED":
        click.secho("\nConfiguration Status:", fg="yellow", nl=False)
        click.echo(" NOT CONFIGURED")
        click.echo("\n---")
        click.secho("\n⚙️ Action Required", fg="magenta", bold=True)
        click.echo("The `gwsa` tool is not ready. Configure credentials using one of the following methods:")
        click.echo("\n* Option 1: Use Google Cloud ADC (Recommended)")
        click.echo("    1. Authenticate with `gcloud`:")
        click.echo("       $ gcloud auth application-default login")
        click.echo("    2. Configure gwsa:")
        click.echo("       $ gwsa setup --use-adc")
        click.echo("\n* Option 2: Use OAuth Client Secrets File")
        click.echo("    1. Configure gwsa directly:")
        click.echo("       $ gwsa setup --client-creds /path/to/your/client_secrets.json")
        click.echo("\n---")
        click.secho("\nRESULT: NOT READY", fg="red", bold=True)
        return

    click.secho("\nConfiguration Status:", fg="yellow", nl=False)
    click.echo(f" CONFIGURED (Mode: {report.get('mode', 'unknown')})")

    if report["status"] == "ERROR":
        click.echo("\n---")
        click.secho("\n❌ ERROR: Credentials Not Found or Invalid", fg="red", bold=True)
        click.echo(f"The tool is configured for '{report.get('mode')}' mode, but failed to load credentials.")
        click.echo(f"Error details: {report.get('error_details')}")
        click.echo("\n---")
        click.secho("\n⚙️ Action Required", fg="magenta", bold=True)
        if report.get('mode') == 'adc':
            click.echo("Your Application Default Credentials (ADC) may be missing, expired, or lack required scopes.")
            click.echo("Try re-authenticating with gcloud:")
            click.echo("   $ gcloud auth application-default login")
            click.echo("Then, re-run setup to validate and cache the new scopes:")
            click.echo("   $ gwsa setup --use-adc")
        elif report.get('mode') == 'token':
            click.echo("Your user_token.json file may be missing, corrupted, or expired.")
            click.echo("Try re-authorizing the application:")
            click.echo("   $ gwsa setup --client-creds /path/to/your/client_secrets.json --new-user")
        click.echo("\n---")
        click.secho("\nRESULT: NOT READY", fg="red", bold=True)
        return

    # --- Detailed Report for Configured State ---
    click.echo("\n---")
    click.echo(f"Credential source: {report.get('source')}")
    if report.get('user_email'):
        click.echo(f"Authenticated user: {report.get('user_email')}")

    click.echo("\nCredential Status:")
    if report.get('creds_valid'):
        click.secho("  ✓ Valid", fg="green")
    else:
        click.secho("  ✗ Invalid", fg="red")
    click.echo(f"  - Expired: {report.get('creds_expired')}")
    if report.get('creds_refreshable'):
        click.echo("  - Refreshable: Yes")
    else:
        click.echo("  - Refreshable: No")

    click.echo("\nFeature Support (based on scopes):")
    if report.get("scope_validation_error"):
        click.secho(f"  ✗ Could not validate scopes: {report.get('scope_validation_error')}", fg="red")
    else:
        for feature, supported in report.get("feature_status", {}).items():
            if supported:
                click.secho(f"  ✓ {feature.capitalize()}", fg="green")
            else:
                click.secho(f"  ✗ {feature.capitalize()}", fg="red")

    if report.get("api_results"):
        click.echo("\nLive API Access (Deep Check):")
        for api_name, result in report["api_results"].items():
            if result["success"]:
                status_msg = "OK"
                if "label_count" in result:
                    status_msg = f'OK ({result["label_count"]} labels)'
                click.secho(f"  ✓ {api_name:10} {status_msg}", fg="green")
            else:
                click.secho(f"  ✗ {api_name:10} FAILED", fg="red")

    click.echo("\n---")
    
    if is_ready:
        click.secho("\nRESULT: READY", fg="green", bold=True)
    else:
        click.secho("\nRESULT: NOT READY", fg="red", bold=True)


def _get_detailed_status_data(creds, source: str, deep_check: bool = False) -> Dict:
    """
    Gathers detailed status information for a given credential and returns it as a dictionary.
    """
    report = {
        "source": source,
        "creds_valid": creds.valid,
        "creds_expired": creds.expired,
        "creds_refreshable": hasattr(creds, 'refresh_token') and creds.refresh_token is not None,
        "scope_validation_error": None,
        "feature_status": {},
        "api_results": {},
        "api_error": None,
        "user_email": None,
    }

    try:
        token_info = get_token_info(creds)
        granted_scopes = set(token_info["scopes"])
        report["user_email"] = token_info.get("email")
        report["granted_scopes"] = granted_scopes
        report["feature_status"] = get_feature_status(granted_scopes)
    except Exception as e:
        report["scope_validation_error"] = str(e)

    if deep_check:
        apis_to_test = [f for f, supported in report.get("feature_status", {}).items() if supported]
        if apis_to_test:
            try:
                report["api_results"] = test_apis(creds, only=apis_to_test)
            except Exception as e:
                report["api_error"] = str(e)

    return report

def run_setup(new_user: bool = False, client_creds: str = None, use_adc: bool = False, adc_login: bool = False, status_only: bool = False):
    """
    Setup or check status - single unified path with conditional actions and reporting.
    """
    import click
    import shutil
    import subprocess
    import google.auth.exceptions
    from .auth.check_access import FEATURE_SCOPES

    if not (new_user or client_creds or use_adc or adc_login):
        status_only = True

    gwa_dir = Path(_CONFIG_DIR)
    gwa_dir.mkdir(parents=True, exist_ok=True)

    if status_only:
        report = _get_status_report(deep_check=False)
        is_ready = report["status"] in ["READY", "CONFIGURED"] and report.get("creds_valid", False)
        _display_status_report(report, is_ready=is_ready)
        return is_ready

    # --- Active Setup Logic ---
    if adc_login:
        click.echo("\n" + "=" * 50)
        click.echo("Initiating ADC Login and Configuration")
        click.echo("=" * 50)
        
        all_scopes = {scope for scope_set in FEATURE_SCOPES.values() for scope in scope_set} | IDENTITY_SCOPES
        all_scopes.add("https://www.googleapis.com/auth/cloud-platform")
        scopes_str = ",".join(sorted(list(all_scopes)))
        gcloud_command = ["gcloud", "auth", "application-default", "login", f"--scopes={scopes_str}"]

        click.echo("Executing gcloud command to grant credentials...")
        
        try:
            # We capture output to check for the quota project warning
            result = subprocess.run(gcloud_command, check=True, capture_output=True, text=True)
            
            if "Cannot find a quota project" in result.stderr:
                click.secho("\nℹ️ NOTICE: Quota Project Required", fg="cyan", bold=True)
                click.echo("\nGoogle has authenticated you, but you must set a 'quota project' for billing and usage tracking.")
                click.echo("Please run the following command, replacing YOUR_PROJECT_ID with your Google Cloud project ID:")
                click.secho("\n  gcloud auth application-default set-quota-project YOUR_PROJECT_ID\n", fg="yellow")
                click.echo("After running the command above, re-run setup to finalize configuration:")
                click.secho("\n  gwsa setup --use-adc\n", fg="cyan")
                return False # Stop here and let the user fix their gcloud config

            click.echo("\ngcloud login successful. Now verifying and configuring gwsa...")
            use_adc = True 

        except (subprocess.CalledProcessError, FileNotFoundError) as e:
            click.secho("\n❌ ERROR: gcloud command failed.", fg="red", bold=True)
            click.echo("Please ensure `gcloud` is installed and in your PATH, then try again.")
            stderr = getattr(e, 'stderr', '')
            if stderr:
                click.echo(f"\nDetails:\n{stderr}")
            return False

    if use_adc:
        click.echo("\n" + "=" * 50)
        click.echo("Configuring for Application Default Credentials (ADC)")
        click.echo("=" * 50)
        try:
            creds, source = get_active_credentials(use_adc=True)
            click.echo(f"  ✓ ADC credentials loaded from: {source}")

            report = _get_detailed_status_data(creds, source, deep_check=False)
            report["status"] = "CONFIGURED"
            report["mode"] = "adc"

            is_ready = report.get("creds_refreshable", False) and not report.get("scope_validation_error")
            if "feature_status" in report and report["feature_status"]:
                is_ready = is_ready and all(report["feature_status"].values())

            if is_ready:
                set_config_value("auth.mode", "adc")
                set_config_value("auth.validated_scopes", list(report.get("granted_scopes", [])))
                set_config_value("auth.last_scope_check", datetime.now().isoformat())
                logger.info("ADC configured and validated scopes cached.")
                _display_status_report(report, is_ready=True)
                return True
            else:
                _display_status_report(report, is_ready=False)
                click.echo("\n---")
                click.secho("\n❌ ERROR: ADC validation failed.", fg="red", bold=True)
                click.echo("Your ADC credentials are not valid or are missing required scopes.")
                click.secho("\n⚙️ Action Required", fg="magenta", bold=True)
                click.echo("To grant full functionality, run the following command:")
                
                all_scopes = {scope for scope_set in FEATURE_SCOPES.values() for scope in scope_set} | IDENTITY_SCOPES
                scopes_str = ",".join(sorted(list(all_scopes)))
                gcloud_command = f"gcloud auth application-default login --scopes={scopes_str}"

                click.secho(f"\n   {gcloud_command}\n", fg="cyan")
                click.echo("Then, re-run this setup command:")
                click.secho("\n   gwsa setup --use-adc\n", fg="cyan")
                return False

        except google.auth.exceptions.DefaultCredentialsError as e:
            click.secho(f"\n❌ ERROR: {e}", fg="red", bold=True)
            click.secho("\n⚙️ Action Required", fg="magenta", bold=True)
            click.echo("Application Default Credentials are not set up on this machine.")
            click.echo("To grant full functionality, run the following command:")
            
            all_scopes = {scope for scope_set in FEATURE_SCOPES.values() for scope in scope_set} | IDENTITY_SCOPES
            all_scopes.add("https://www.googleapis.com/auth/cloud-platform")
            scopes_str = ",".join(sorted(list(all_scopes)))
            gcloud_command = f"gcloud auth application-default login --scopes={scopes_str}"

            click.secho(f"\n   {gcloud_command}\n", fg="cyan")
            click.echo("Then, re-run this setup command:")
            click.secho("\n   gwsa setup --use-adc\n", fg="cyan")
            return False
        except Exception as e:
            click.echo(f"✗ Failed to configure ADC: {e}")
            return False

    elif client_creds:
        click.echo("\n" + "=" * 50)
        click.echo("Configuring for OAuth Token (user_token.json)")
        click.echo("=" * 50)
        
        if not _atomic_client_creds_setup(client_creds, True): # client-creds always implies new user
             click.echo("✗ User authentication failed. Configuration not saved.")
             return False

        # Set auth.mode FIRST so get_active_credentials() knows where to look
        set_config_value("auth.mode", "token")

        # Post-setup validation and configuration save
        creds, source = get_active_credentials()
        details_report = _get_detailed_status_data(creds, source, deep_check=False)
        report = {"status": "CONFIGURED", "mode": "token"}
        report.update(details_report)
        is_ready = report.get("creds_refreshable", False) and not report.get("scope_validation_error") and all(report.get("feature_status", {}).values())
        set_config_value("auth.validated_scopes", list(report.get("granted_scopes", [])))
        set_config_value("auth.last_scope_check", datetime.now().isoformat())
        logger.info("Token auth configured and validated scopes cached.")

        _display_status_report(report, is_ready=is_ready)
        return is_ready

    elif new_user:
        click.echo("\n" + "=" * 50)
        click.echo("Re-authenticating user for existing configuration")
        click.echo("=" * 50)
        if not os.path.exists(CLIENT_SECRETS_FILE):
            click.secho("\n❌ ERROR: client_secrets.json not found.", fg="red", bold=True)
            click.echo("Cannot re-authenticate without the client secrets file.")
            click.echo("Please run setup with the --client-creds flag first:")
            click.secho("\n  gwsa setup --client-creds /path/to/client_secrets.json\n", fg="cyan")
            return False

        if not _atomic_client_creds_setup(CLIENT_SECRETS_FILE, True): # new-user always implies new user
             click.echo("✗ User authentication failed. Configuration not saved.")
             return False

        # Set auth.mode FIRST so get_active_credentials() knows where to look
        set_config_value("auth.mode", "token")

        # Post-setup validation and configuration save
        creds, source = get_active_credentials()
        details_report = _get_detailed_status_data(creds, source, deep_check=False)
        report = {"status": "CONFIGURED", "mode": "token"}
        report.update(details_report)
        is_ready = report.get("creds_refreshable", False) and not report.get("scope_validation_error") and all(report.get("feature_status", {}).values())
        set_config_value("auth.validated_scopes", list(report.get("granted_scopes", [])))
        set_config_value("auth.last_scope_check", datetime.now().isoformat())
        logger.info("Token auth configured and validated scopes cached.")

        _display_status_report(report, is_ready=is_ready)
        return is_ready

    else: # Fallback if no specific config action taken
        click.secho("No configuration action specified. Use --use-adc, --adc-login, or --client-creds.", fg="yellow")
        return False

