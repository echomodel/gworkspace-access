"""GWSA CLI - Command-line interface for Google Workspace Access."""

import logging
import os
import sys
import json
from functools import wraps
from dotenv import load_dotenv
import click

from gwsa import __version__
from gwsa.sdk import mail as sdk_mail
from gwsa.sdk.auth import get_credentials

from . import setup_local
from .sheets_commands import sheets as sheets_module
from .docs_commands import docs as docs_module
from .drive_commands import drive_group as drive_module
from .config_commands import config_group as config_module
from .profiles_commands import profiles as profiles_module
from .client_commands import client as client_module
from .chat import chat as chat_module


# Configure logging at the application level
if not logging.root.handlers:
    LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()
    logging.basicConfig(level=getattr(logging, LOG_LEVEL),
                        format='%(asctime)s - %(levelname)s - %(message)s')
# Suppress noisy INFO logs from googleapiclient and google_auth_oauthlib
logging.getLogger('googleapiclient.discovery').setLevel(logging.WARNING)
logging.getLogger('googleapiclient.discovery_cache').setLevel(logging.WARNING)
logging.getLogger('google_auth_oauthlib.flow').setLevel(logging.WARNING)
logger = logging.getLogger(__name__)


from .decorators import require_scopes, format_status, show_profile_guidance


@click.group()
def gwsa():
    """Gmail Workspace Assistant (GWSA) CLI.

    A personal Gmail Workspace Assistant for managing emails via command line.
    """
    pass


# Status command - shows current configuration and profile status
@click.command()
@click.option('--check', is_flag=True, help='Run deep validation with live API calls.')
def status(check):
    """Show current configuration and profile status.

    Displays the active profile, validation status, and feature availability.
    Use --check for deep validation that makes live API calls.
    """
    from .profiles import get_active_profile, get_profile_status, list_profiles

    click.echo("\n" + "=" * 50)
    click.echo("gwsa Status")
    click.echo("=" * 50)

    # Get active profile
    active = get_active_profile()
    if not active:
        click.echo()
        profiles = list_profiles()
        has_any_valid = any(get_profile_status(p["name"])["valid"] for p in profiles)
        show_profile_guidance(has_active=False, has_any_valid=has_any_valid)
        sys.exit(1)

    # Show active profile info
    profile_status = get_profile_status(active["name"])

    click.echo(f"\nActive Profile: {active['name']}")
    if active.get("is_adc"):
        click.echo("  Type: Application Default Credentials (ADC)")
    else:
        click.echo("  Type: OAuth Token")

    click.echo(f"  Status: {format_status(profile_status)}")
    if not profile_status["valid"]:
        click.echo(f"  Reason: {profile_status['reason']}")

    if active.get("email"):
        click.echo(f"  Email: {active['email']}")

    scopes = active.get("scopes", [])
    click.echo(f"  Scopes: {len(scopes)}")

    # Deep check if requested
    if check:
        click.echo("\nRunning deep validation...")
        try:
            creds, source = get_credentials()
            report = setup_local._get_detailed_status_data(creds, source, deep_check=True)

            click.echo("\nFeature Support:")
            for feature, supported in report.get("feature_status", {}).items():
                if supported:
                    click.secho(f"  ✓ {feature}", fg="green")
                else:
                    click.secho(f"  ✗ {feature}", fg="red")

            if report.get("api_results"):
                click.echo("\nLive API Access:")
                for api_name, result in report["api_results"].items():
                    if result.get("success"):
                        click.secho(f"  ✓ {api_name}", fg="green")
                    else:
                        click.secho(f"  ✗ {api_name}: {result.get('error', 'failed')}", fg="red")

        except Exception as e:
            click.secho(f"\nDeep validation failed: {e}", fg="red")
            sys.exit(1)

    click.echo("\n" + "=" * 50)
    if profile_status["valid"]:
        show_profile_guidance(
            active_profile_name=active["name"],
            active_is_valid=True,
            has_any_valid=True,
            has_active=True
        )
    else:
        profiles = list_profiles()
        has_any_valid = any(
            p["name"] != active["name"] and get_profile_status(p["name"])["valid"]
            for p in profiles
        )
        show_profile_guidance(
            active_profile_name=active["name"],
            active_is_valid=False,
            has_any_valid=has_any_valid,
            has_active=True
        )
        sys.exit(1)


# Mail group
@click.group()
def mail():
    """Operations related to Gmail."""
    pass


# Mail search command
@click.command()
@click.argument('query')
@click.option('--page-token', default=None,
              help="Token for pagination (from previous search's nextPageToken).")
@click.option('--max-results', type=int, default=25,
              help='Maximum number of messages to return (default 25, due to body extraction cost).')
@click.option('--format', type=click.Choice(['full', 'metadata']), default='full',
              help="'full' includes body and snippet (slower); 'metadata' is fast with headers and labelIds only.")
@require_scopes('mail-read')
def search(query, page_token, max_results, format):
    """Search for emails. Output is in JSON format."""
    try:
        logger.debug(f"Executing mail search with query: '{query}'")
        messages, metadata = sdk_mail.search_messages(
            query, page_token=page_token, max_results=max_results, format=format
        )
        logger.info(f"Found {len(messages)} messages (estimated total: {metadata['resultSizeEstimate']})")
        if metadata.get('nextPageToken'):
            logger.info(f"More pages available. Use --page-token {metadata['nextPageToken']} to fetch next page")
        click.echo(json.dumps(messages, indent=2))
    except Exception as e:
        logger.critical(f"An error occurred during mail search: {e}", exc_info=True)
        sys.exit(1)


# Mail read command
@click.command()
@click.argument('message_id')
@require_scopes('mail-read')
def read_command(message_id):
    """Read a specific email by ID."""
    try:
        logger.debug(f"Executing mail read for message ID: '{message_id}'")
        message_details = sdk_mail.read_message(message_id)
        click.echo(json.dumps(message_details, indent=2))
    except Exception as e:
        logger.critical(f"An error occurred during mail read for ID {message_id}: {e}", exc_info=True)
        sys.exit(1)


# Mail label command
@click.command()
@click.argument('message_id')
@click.argument('label_name')
@click.option('--remove', is_flag=True,
              help='Remove the label instead of adding it.')
@require_scopes('mail-modify')
def label_command(message_id, label_name, remove):
    """Add or remove labels from an email."""
    try:
        action = "removing" if remove else "adding"
        logger.debug(f"{action.capitalize()} label '{label_name}' for message ID: '{message_id}'")
        if remove:
            updated_message = sdk_mail.remove_label(message_id, label_name)
        else:
            updated_message = sdk_mail.add_label(message_id, label_name)
        click.echo(json.dumps(updated_message, indent=2))
    except Exception as e:
        logger.critical(f"An error occurred during mail label for ID {message_id}: {e}", exc_info=True)
        sys.exit(1)


# Add commands to groups using add_command()
gwsa.add_command(status, name='status')
gwsa.add_command(client_module, name='client')
gwsa.add_command(config_module, name='config')
gwsa.add_command(profiles_module, name='profiles')
gwsa.add_command(mail)
gwsa.add_command(sheets_module, name='sheets')
gwsa.add_command(docs_module, name='docs')
gwsa.add_command(drive_module, name='drive')
gwsa.add_command(chat_module, name='chat')

mail.add_command(search)
mail.add_command(read_command, name='read')
mail.add_command(label_command, name='label')


def main():
    """Entry point for the CLI."""
    load_dotenv()
    gwsa()


if __name__ == "__main__":
    main()
