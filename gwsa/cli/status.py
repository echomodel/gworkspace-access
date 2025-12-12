"""Status command for checking gwsa configuration and credential status."""

import json
import hashlib
import os
from pathlib import Path
from typing import Dict, Tuple, Optional
import click

from . import setup_local


def get_gworkspace_access_dir() -> Tuple[Optional[Path], list]:
    """Find gworkspace-access directory.
    Returns (found_path, list_of_checked_paths)
    """
    # Check environment variable first
    env_path = os.getenv('GWSA_CONFIG_DIR')
    if env_path:
        path = Path(env_path)
        checked_paths = [env_path]
        if path.exists():
            return path, checked_paths
        else:
            return None, checked_paths

    # Check XDG Base Directory standard location
    home_dir = Path.home()
    gwa_dir = home_dir / '.config' / 'gworkspace-access'
    checked_paths = [str(gwa_dir)]

    if gwa_dir.exists():
        return gwa_dir, checked_paths

    return None, checked_paths


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
    except Exception as e:
        return {"error": str(e)}


def check_client_config() -> Tuple[bool, Dict]:
    """Check client application configuration"""
    gwa_dir, checked_paths = get_gworkspace_access_dir()

    if not gwa_dir:
        return False, {
            "status": "NOT FOUND",
            "message": "gworkspace-access directory not found",
            "paths_checked": checked_paths,
            "client_creds_hash": None,
            "project_id": None
        }

    client_secrets_path = gwa_dir / 'client_secrets.json'

    if not client_secrets_path.exists():
        return False, {
            "status": "MISSING CONFIG",
            "message": "client_secrets.json not found",
            "client_creds_hash": None,
            "project_id": None
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

    return True, {
        "status": "CONFIGURED",
        "client_secrets_file": str(client_secrets_path),
        "client_creds_hash": creds_hash,
        "project_id": project_id,
        "client_id_prefix": client_id,
        "scopes": client_secrets.get('installed', {}).get('scopes', [])
    }


def check_user_credentials() -> Tuple[bool, Dict]:
    """Check user credential status"""
    gwa_dir, checked_paths = get_gworkspace_access_dir()

    if not gwa_dir:
        return False, {
            "status": "GWA NOT FOUND",
            "paths_checked": checked_paths
        }

    user_token_path = gwa_dir / 'user_token.json'

    if not user_token_path.exists():
        return False, {
            "status": "NO USER TOKEN",
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

    return True, {
        "status": "AUTHENTICATED",
        "user_token_path": str(user_token_path),
        "user_token_hash": token_hash,
        "scopes": user_token.get('scopes', []),
        "expiry": user_token.get('expiry', 'UNKNOWN')
    }


def print_table(title: str, status_ok: bool, data: Dict) -> None:
    """Print a formatted status table"""
    status_indicator = "✓" if status_ok else "✗"
    click.echo(f"\n{status_indicator} {title}")
    click.echo("=" * 80)

    for key, value in data.items():
        if isinstance(value, list):
            value = ", ".join(value) if value else "(none)"
        elif value is None:
            value = "(not set)"

        click.echo(f"  {key:<30} {str(value):<45}")

    click.echo("=" * 80)


def status():
    """Check gwsa configuration and credential status."""
    click.echo("\n" + "=" * 80)
    click.echo("gworkspace-access (gwsa) Configuration Status")
    click.echo("=" * 80)

    # Show installation check
    gwa_dir, checked_paths = get_gworkspace_access_dir()
    click.echo("\nCONFIGURATION PATH SEARCH")
    click.echo("=" * 80)
    for path in checked_paths:
        status_indicator = "✓ FOUND" if gwa_dir and str(gwa_dir) == path else "✗ not found"
        click.echo(f"  {status_indicator:<10} {path}")
    click.echo("=" * 80)

    # Check client configuration
    client_ok, client_data = check_client_config()
    print_table("CLIENT APPLICATION CONFIGURATION", client_ok, client_data)

    # Check user credentials
    user_ok, user_data = check_user_credentials()
    print_table("USER AUTHENTICATION", user_ok, user_data)

    # Overall status
    click.echo("\n" + "=" * 80)
    if client_ok and user_ok:
        click.echo("✓ gwsa is fully configured and ready to use")
        return 0
    elif client_ok and not user_ok:
        click.echo("⚠ Client app configured but user authentication missing")
        click.echo("  Run: gwsa setup")
        return 1
    elif not client_ok and user_ok:
        click.echo("⚠ User authenticated but client app configuration missing")
        click.echo("  This is unusual - check your gworkspace-access installation")
        return 1
    else:
        click.echo("✗ gwsa is not properly configured")
        if not get_gworkspace_access_dir()[0]:
            click.echo("  gworkspace-access not found - install it from:")
            click.echo("  https://github.com/krisrowe/gworkspace-access")
        else:
            click.echo("  Run: gwsa setup")
        return 1
