"""CLI commands for managing OAuth client credentials."""

import os
import sys
import json
import shutil
import hashlib
import click

from .setup_local import CLIENT_SECRETS_FILE


@click.group()
def client():
    """Manage OAuth client credentials.

    Client credentials (client_secrets.json) are required before creating profiles.
    Get these from Google Cloud Console > APIs & Services > Credentials.
    """
    pass


@client.command("show")
def show_cmd():
    """Show current client credentials status.

    Displays client ID and configuration status.
    The client secret is NOT displayed for security.
    """
    if not os.path.exists(CLIENT_SECRETS_FILE):
        click.secho("No client credentials configured.", fg="yellow")
        click.echo(f"\nExpected location: {CLIENT_SECRETS_FILE}")
        click.echo("\nTo configure:")
        click.echo("  gwsa client import /path/to/client_secrets.json")
        click.echo("\nGet credentials from:")
        click.echo("  Google Cloud Console > APIs & Services > Credentials")
        sys.exit(1)

    try:
        with open(CLIENT_SECRETS_FILE, 'r') as f:
            data = json.load(f)

        # Handle different formats (installed app vs web)
        if "installed" in data:
            creds = data["installed"]
            cred_type = "Desktop App"
        elif "web" in data:
            creds = data["web"]
            cred_type = "Web App"
        else:
            click.secho("Unknown client secrets format.", fg="red")
            sys.exit(1)

        client_id = creds.get("client_id", "unknown")
        project_id = creds.get("project_id", "unknown")

        # For secret, show only that it exists and a hash prefix (safe to display)
        client_secret = creds.get("client_secret", "")
        if client_secret:
            secret_hash = hashlib.sha256(client_secret.encode()).hexdigest()[:8]
            secret_display = f"configured (hash: {secret_hash}...)"
        else:
            secret_display = "NOT SET"

        click.echo(f"\nClient Credentials")
        click.echo("-" * 40)
        click.echo(f"  Location:      {CLIENT_SECRETS_FILE}")
        click.echo(f"  Type:          {cred_type}")
        click.echo(f"  Project ID:    {project_id}")
        click.echo(f"  Client ID:     {client_id}")
        click.echo(f"  Client Secret: {secret_display}")
        click.echo("-" * 40)
        click.secho("Ready for profile creation.", fg="green")

    except json.JSONDecodeError as e:
        click.secho(f"Error: Invalid JSON in client secrets file.", fg="red")
        click.echo(f"  {e}")
        sys.exit(1)
    except Exception as e:
        click.secho(f"Error reading client secrets: {e}", fg="red")
        sys.exit(1)


@client.command("import")
@click.argument("path", type=click.Path(exists=True))
def import_cmd(path):
    """Import client credentials from a file.

    PATH is the path to your client_secrets.json file downloaded from
    Google Cloud Console > APIs & Services > Credentials.

    The file will be copied to gwsa's config directory.
    """
    # Validate the file is valid JSON with expected structure
    try:
        with open(path, 'r') as f:
            data = json.load(f)

        if "installed" not in data and "web" not in data:
            click.secho("Error: Invalid client secrets format.", fg="red")
            click.echo("Expected 'installed' or 'web' key in JSON.")
            click.echo("\nMake sure you downloaded the correct file from:")
            click.echo("  Google Cloud Console > APIs & Services > Credentials")
            sys.exit(1)

        # Extract client_id for confirmation
        creds = data.get("installed") or data.get("web")
        client_id = creds.get("client_id", "unknown")

    except json.JSONDecodeError as e:
        click.secho(f"Error: Invalid JSON file.", fg="red")
        click.echo(f"  {e}")
        sys.exit(1)
    except Exception as e:
        click.secho(f"Error reading file: {e}", fg="red")
        sys.exit(1)

    # Don't copy if it's already the same file
    if os.path.abspath(path) == os.path.abspath(CLIENT_SECRETS_FILE):
        click.echo("File is already at the configured location.")
        return

    # Copy file
    try:
        os.makedirs(os.path.dirname(CLIENT_SECRETS_FILE), exist_ok=True)
        shutil.copy(path, CLIENT_SECRETS_FILE)
        click.secho("Client credentials imported successfully.", fg="green")
        click.echo(f"  Client ID: {client_id}")
        click.echo(f"  Saved to:  {CLIENT_SECRETS_FILE}")
        click.echo("\nNext step:")
        click.echo("  gwsa profiles add <name>")
    except Exception as e:
        click.secho(f"Error copying file: {e}", fg="red")
        sys.exit(1)
