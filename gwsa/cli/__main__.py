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
from .config_commands import config_group as config_module
from .profiles_commands import profiles as profiles_module
from .auth import check_access as check_access_module
from .auth import create_token as create_token_module


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


from .decorators import require_scopes


@click.group()
def gwsa():
    """Gmail Workspace Assistant (GWSA) CLI.

    A personal Gmail Workspace Assistant for managing emails via command line.
    """
    pass


# Setup command
from click_option_group import optgroup, MutuallyExclusiveOptionGroup

# ... (other imports)

@click.command()
@optgroup.group('Configuration Mode', cls=MutuallyExclusiveOptionGroup)
@optgroup.option('--client-creds', type=click.Path(exists=True), help='Configure using an OAuth client secrets file (implies --new-user).')
@optgroup.option('--use-adc', is_flag=True, help='Configure to use existing Application Default Credentials.')
@optgroup.option('--adc-login', is_flag=True, help='Initiate the ADC login flow and configure gwsa.')
@click.option('--new-user', is_flag=True, help='Force a new user authentication flow for an existing configuration.')
def setup(client_creds, use_adc, adc_login, new_user):
    """Set up local environment and credentials, or check status."""
    # Using --client-creds always implies a new user is needed to match the tokens.
    if client_creds:
        new_user = True

    status_only = not (client_creds or use_adc or adc_login or new_user)

    if not setup_local.run_setup(
        new_user=new_user, 
        client_creds=client_creds, 
        use_adc=use_adc, 
        adc_login=adc_login,
        status_only=status_only
    ):
        sys.exit(1)


# Create-token command
@click.command()
@click.option('--scope', '-s', 'scopes', multiple=True, required=True,
              help='Google API scope(s) to request. Can be specified multiple times.')
@click.option('--client-creds', type=click.Path(exists=True), required=True,
              help='Path to client_secrets.json file for OAuth.')
@click.option('--output', '-o', type=click.Path(), required=True,
              help='Path where the token should be saved.')
def create_token(scopes, client_creds, output):
    """Create an OAuth token for specified scopes.

    This is a standalone auth utility that does NOT affect gwsa configuration.
    Use it to create tokens for other projects or specific scope combinations.

    Example:
        gwsa access token --scope https://www.googleapis.com/auth/documents \\
            --client-creds ./credentials.json --output ./my_token.json
    """
    scope_list = list(scopes)
    output_path = os.path.abspath(output)

    if not create_token_module.create_token_for_scopes(client_creds, output_path, scope_list):
        logger.error("Failed to create token. Please check logs for details.")
        sys.exit(1)

    click.echo(f"\nToken successfully created at: {output_path}")
    click.echo(f"Scopes: {', '.join(scope_list)}")


# Check-access command
@click.command()
@click.option('--token-file', type=click.Path(exists=True),
              help='Path to token file to test.')
@click.option('--application-default', is_flag=True,
              help='Use Application Default Credentials (gcloud auth application-default login).')
def check_access(token_file, application_default):
    """
    Test OAuth token validity and API access with a deep check.
    This command runs a full diagnostic, including live API calls.
    """
    try:
        # Use SDK get_credentials (aliased as get_active_credentials in check_access_module)
        creds, source = get_credentials(use_adc=application_default)
        # Get detailed status with deep check (live API calls)
        report = setup_local._get_detailed_status_data(creds, source, deep_check=True)
        report["status"] = "CONFIGURED"
        report["mode"] = "adc" if application_default else "token"

        # Determine if ready based on credentials being valid/refreshable
        is_ready = report.get("creds_valid", False) or report.get("creds_refreshable", False)

        setup_local._display_status_report(report, is_ready=is_ready)

        if not is_ready:
            sys.exit(1)

    except Exception as e:
        click.echo(f"✗ Failed to load credentials or run checks: {e}")
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


# Access group
@click.group()
def access():
    """Authentication utilities (standalone, does not affect gwsa config)."""
    pass


# Add commands to groups using add_command()
gwsa.add_command(setup, name='setup')
gwsa.add_command(config_module, name='config')
gwsa.add_command(profiles_module, name='profiles')
gwsa.add_command(access)
gwsa.add_command(mail)
gwsa.add_command(sheets_module, name='sheets')

access.add_command(create_token, name='token')
access.add_command(check_access, name='check')

mail.add_command(search)
mail.add_command(read_command, name='read')
mail.add_command(label_command, name='label')


def main():
    """Entry point for the CLI."""
    load_dotenv()
    gwsa()


if __name__ == "__main__":
    main()
