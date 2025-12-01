import os
import logging
import hashlib
import json
from pathlib import Path
from typing import Tuple, Dict, Optional

# Import mail related constants from the mail package's __init__.py
from .mail import USER_TOKEN_FILE, SCOPES

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
    :param new_user: If True, force a new OAuth flow by deleting any existing user_token.json.
    """
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials
    from google_auth_oauthlib.flow import InstalledAppFlow

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
            creds = Credentials.from_authorized_user_file(USER_TOKEN_FILE, SCOPES)
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
                return False

            try:
                flow = InstalledAppFlow.from_client_secrets_file(
                    CLIENT_SECRETS_FILE, SCOPES
                )
                creds = flow.run_local_server(port=0) # Port 0 for dynamic port
                logger.info("New user authorization completed via browser.")
            except Exception as e:
                logger.error(f"Failed to complete new user authorization flow: {e}")
                return False

        # Save token with type field for ADC compatibility
        token_data = json.loads(creds.to_json())
        token_data["type"] = "authorized_user"
        with open(USER_TOKEN_FILE, "w") as token:
            json.dump(token_data, token, indent=2)
        logger.debug(f"User credentials saved to {USER_TOKEN_FILE}.")
    else:
        logger.info("User credentials are valid.")

    return True


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
    click.echo("=" * 80)

    for key, value in data.items():
        if key == "status":
            continue  # Skip status as we already displayed it
        if isinstance(value, list):
            value = ", ".join(value) if value else "(none)"
        elif value is None:
            value = "(not set)"

        click.echo(f"  {key:<30} {str(value):<45}")

    click.echo("=" * 80)


def run_setup(new_user: bool = False, client_creds: str = None, status_only: bool = False):
    """
    Setup or check status - single unified path with conditional actions and reporting.

    Stage 1: Evaluate what needs to be done (same logic for all paths)
    Stage 2: Execute if not status_only, else report what would happen

    :param new_user: Force new OAuth flow
    :param client_creds: Path to client_secrets.json to copy
    :param status_only: If True, skip write operations and report what would happen
    """
    import click
    import shutil

    if not status_only:
        logger.info("Starting local setup script...")

    # Ensure config directory exists (always, needed for both paths)
    gwa_dir = Path(_CONFIG_DIR)
    gwa_dir.mkdir(parents=True, exist_ok=True)

    # ===== STAGE 1: EVALUATE WHAT NEEDS TO BE DONE (same for all paths) =====

    # Plan for client secrets
    client_action_needed = False
    client_secrets_existed = os.path.exists(CLIENT_SECRETS_FILE)
    files_are_identical = False

    if client_creds:
        if os.path.exists(client_creds):
            # Check if files are identical (avoid redundant copy)
            if client_secrets_existed:
                source_hash = hash_file(Path(client_creds))
                dest_hash = hash_file(Path(CLIENT_SECRETS_FILE))
                files_are_identical = source_hash == dest_hash

            client_action_needed = not files_are_identical
        else:
            logger.error(f"Error: Client secrets file not found: {client_creds}")
            return False

    # Plan for user token
    user_action_needed = False
    user_token_existed = os.path.exists(USER_TOKEN_FILE)

    if new_user or not user_token_existed:
        user_action_needed = True

    # ===== STAGE 2: EXECUTE IF NOT STATUS_ONLY =====

    client_action_performed = False
    user_action_performed = False

    if not status_only:
        # Execute client secrets copy if needed
        if client_creds and client_action_needed:
            shutil.copy(client_creds, CLIENT_SECRETS_FILE)
            logger.info(f"Client secrets copied from {client_creds} to {CLIENT_SECRETS_FILE}")
            client_action_performed = True

        # Execute user token setup if needed
        if user_action_needed:
            if not ensure_user_token_json(new_user=new_user):
                return False
            user_action_performed = True

    # ===== STAGE 3: DETERMINE STATUS INDICATORS =====

    # After execution (or evaluation), determine what status to report
    # In status_only mode, action_needed becomes the indicator
    # In setup mode, action_performed becomes the indicator

    if status_only:
        client_action_performed = client_action_needed
        user_action_performed = user_action_needed

    # Display configuration status (same output for both paths)
    click.echo("\n" + "=" * 80)
    click.echo("gworkspace-access (gwsa) Configuration Status")
    click.echo("=" * 80)

    click.echo("\nCONFIGURATION PATH SEARCH")
    click.echo("=" * 80)
    status_indicator = "✓ FOUND" if gwa_dir.exists() else "✗ not found"
    click.echo(f"  {status_indicator:<10} {gwa_dir}")
    click.echo("=" * 80)

    # Check client and user credentials (same checks for both paths)
    client_ok, client_data = check_client_config(status_only=status_only)
    print_status_table("CLIENT APPLICATION CONFIGURATION", client_ok, client_data, status_only=status_only, action_performed=client_action_performed)

    user_ok, user_data = check_user_credentials(status_only=status_only)
    print_status_table("USER AUTHENTICATION", user_ok, user_data, status_only=status_only, action_performed=user_action_performed)

    # Overall status (same output for both paths)
    click.echo("\n" + "=" * 80)
    if client_ok and user_ok:
        click.echo("✓ gwsa is fully configured and ready to use")
        return True
    elif client_ok and not user_ok:
        click.echo("⚠ Client app configured but user authentication missing")
        click.echo("  Run: gwsa setup")
        return False
    elif not client_ok and user_ok:
        click.echo("⚠ User authenticated but client app configuration missing")
        click.echo("  This is unusual - check your gworkspace-access installation")
        return False
    else:
        click.echo("✗ gwsa is not properly configured")
        if not gwa_dir.exists():
            click.echo("  gworkspace-access not found - install it from:")
            click.echo("  https://github.com/krisrowe/gworkspace-access")
        else:
            click.echo("  Run: gwsa setup")
        return False

if __name__ == "__main__":
    import sys
    if not run_setup():
        sys.exit(1)