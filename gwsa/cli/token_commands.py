"""CLI commands for standalone token generation."""

import sys
import click
import json
import os
import subprocess
from pathlib import Path
from .auth.scopes import resolve_scopes
from .auth.check_access import FEATURE_SCOPES, IDENTITY_SCOPES
from gwsa.sdk.auth import SCOPE_ALIASES
from .setup_local import CLIENT_SECRETS_FILE

# Build dynamic help string for scopes
# Combine single aliases and feature names
ALL_ALIAS_KEYS = set(SCOPE_ALIASES.keys()) | set(FEATURE_SCOPES.keys())
AVAILABLE_SCOPES = ", ".join(sorted(list(ALL_ALIAS_KEYS)))
SCOPE_HELP = f"Comma-separated list of scopes ({AVAILABLE_SCOPES}) or full URLs."

@click.group()
def token():
    """Generate and manage standalone Google API tokens."""
    pass

@token.command("generate")
@click.argument("source", type=click.Choice(["adc", "custom"]))
@click.option("--scopes", help=SCOPE_HELP)
@click.option("--output", "-o", type=click.Path(), help="Write token JSON to this file instead of stdout.")
def generate_cmd(source, scopes, output):
    """Generate a Google API token JSON without affecting profiles.
    
    SOURCE: 'adc' uses gcloud CLI; 'custom' uses local OAuth flow (requires client secrets).
    
    This command performs an interactive authentication flow and outputs the resulting
    credential JSON. It does NOT save the token to any gwsa profile.
    """
    # 1. Resolve Scopes
    if scopes:
        requested_scopes = resolve_scopes([s.strip() for s in scopes.split(",")])
    else:
        # Default to all feature scopes (same as refresh)
        all_scopes = {s for s_set in FEATURE_SCOPES.values() for s in s_set} | IDENTITY_SCOPES
        requested_scopes = list(all_scopes)

    token_data = None

    if source == "adc":
        click.echo("Initiating ADC Login via gcloud...", err=True)
        # Add cloud-platform scope for ADC standard compatibility
        if "https://www.googleapis.com/auth/cloud-platform" not in requested_scopes:
            requested_scopes.append("https://www.googleapis.com/auth/cloud-platform")
            
        scopes_str = ",".join(sorted(requested_scopes))
        gcloud_command = ["gcloud", "auth", "application-default", "login", f"--scopes={scopes_str}"]

        try:
            # We don't capture output here so the user sees the gcloud prompts
            subprocess.run(gcloud_command, check=True)
            
            # Locate the generated file
            if sys.platform == "win32":
                adc_path = Path(os.environ.get("APPDATA", "")) / "gcloud" / "application_default_credentials.json"
            else:
                adc_path = Path.home() / ".config" / "gcloud" / "application_default_credentials.json"
            
            if not adc_path.exists():
                click.secho(f"Error: ADC file not found after login at {adc_path}", fg="red", err=True)
                sys.exit(1)
                
            with open(adc_path, "r") as f:
                token_data = json.load(f)
                
        except subprocess.CalledProcessError as e:
            click.secho(f"gcloud command failed.", fg="red", err=True)
            sys.exit(1)
        except Exception as e:
            click.secho(f"Error generating ADC token: {e}", fg="red", err=True)
            sys.exit(1)

    else: # custom
        if not os.path.exists(CLIENT_SECRETS_FILE):
            click.secho("Error: Client credentials not configured.", fg="red", err=True)
            click.echo(f"Please run 'gwsa client import' first or ensure {CLIENT_SECRETS_FILE} exists.", err=True)
            sys.exit(1)

        click.echo("Initiating OAuth flow via browser...", err=True)
        try:
            from google_auth_oauthlib.flow import InstalledAppFlow
            flow = InstalledAppFlow.from_client_secrets_file(CLIENT_SECRETS_FILE, requested_scopes)
            creds = flow.run_local_server(port=0)
            
            token_data = json.loads(creds.to_json())
            token_data["type"] = "authorized_user"
        except Exception as e:
            click.secho(f"OAuth flow failed: {e}", fg="red", err=True)
            sys.exit(1)

    # 2. Output handling
    if token_data:
        output_json = json.dumps(token_data, indent=2)
        if output:
            try:
                with open(output, "w") as f:
                    f.write(output_json)
                click.echo(f"Token saved to {output}", err=True)
            except Exception as e:
                click.secho(f"Failed to write to {output}: {e}", fg="red", err=True)
                sys.exit(1)
        else:
            click.echo(output_json)
