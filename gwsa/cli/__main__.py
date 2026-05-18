"""gwsa CLI — domain-only Google Workspace operations.

Profile, account, token, and OAuth-client management live exclusively
in ``gwsa-admin`` (see docs/CLOUD-MULTI-USER.md §6.3). This CLI only
talks to Google APIs; credentials are resolved by the SDK from the
mcp-app ``current_user`` ContextVar, which this entry point sets
once at startup from the local user store (see ``_bootstrap_user``).
"""

import asyncio
import json
import logging
import os
import sys

import click
from dotenv import load_dotenv

from gwsa import __version__, app
from gwsa.sdk import mail as sdk_mail

from .chat import chat as chat_module
from .docs_commands import docs as docs_module
from .drive_commands import drive_group as drive_module
from .mail.threads import threads as threads_module
from .sheets_commands import sheets as sheets_module


if not logging.root.handlers:
    LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()
    logging.basicConfig(level=getattr(logging, LOG_LEVEL),
                        format='%(asctime)s - %(levelname)s - %(message)s')
logging.getLogger('googleapiclient.discovery').setLevel(logging.WARNING)
logging.getLogger('googleapiclient.discovery_cache').setLevel(logging.WARNING)
logging.getLogger('google_auth_oauthlib.flow').setLevel(logging.WARNING)
logger = logging.getLogger(__name__)


def _bootstrap_user(user_email: str | None) -> None:
    """Load a user record from the local store and pin ``current_user``.

    The gwsa CLI is single-user-at-a-time — every command runs in
    exactly one user's identity. mcp-app's HTTP middleware does this
    for hosted requests; for the CLI we do it once here, before any
    Click subcommand runs.

    Args:
        user_email: Explicit ``--user`` selector. If ``None``, the
            store's sole user is used; if the store has multiple
            users with no selector, exit with a clear error.
    """
    from mcp_app.bridge import DataStoreAuthAdapter
    from mcp_app.context import current_user, hydrate_profile

    store = app._build_store()
    adapter = DataStoreAuthAdapter(store)

    if user_email is None:
        users = store.list_users()
        if not users:
            raise click.ClickException(
                "No users in the local store. Register one with: "
                "gwsa-admin accounts add <name> --email <you@example.com> --token=..."
            )
        if len(users) > 1:
            raise click.ClickException(
                f"Multiple users in store ({', '.join(users)}). "
                f"Disambiguate with: gwsa --user <email> ..."
            )
        user_email = users[0]

    user_record = asyncio.run(adapter.get_full(user_email))
    if user_record is None:
        raise click.ClickException(
            f"User '{user_email}' not found in local store. "
            f"Register with: gwsa-admin accounts add ..."
        )
    user_record.profile = hydrate_profile(user_record.profile)
    current_user.set(user_record)


@click.group()
@click.version_option(__version__, prog_name="gwsa")
@click.option("--user", "user_email", default=None, metavar="EMAIL",
              help="Operate as this user (required when multiple users exist locally).")
def gwsa(user_email):
    """gwsa CLI — Google Workspace domain operations.

    Profile and credential management lives in ``gwsa-admin`` (e.g.,
    ``gwsa-admin accounts add``, ``gwsa-admin acquire-token``).
    """
    _bootstrap_user(user_email)


@click.group()
def mail():
    """Operations related to Gmail."""
    pass


@mail.command("search")
@click.argument('query')
@click.option('--page-token', default=None,
              help='Token for fetching the next page of results.')
@click.option('--max-results', type=int, default=25,
              help='Maximum number of results to return.')
@click.option('--format', type=click.Choice(['full', 'metadata']), default='full',
              help='Format of the response. "full" includes message details, '
                   '"metadata" omits the message body.')
def mail_search(query, page_token, max_results, format):
    """Search emails. QUERY is a Gmail search expression."""
    try:
        result = sdk_mail.search(query, max_results=max_results, page_token=page_token)
        click.echo(json.dumps(result, indent=2, default=str))
    except Exception as e:
        logger.critical(f"Mail search failed: {e}", exc_info=True)
        sys.exit(1)


@mail.command("read")
@click.argument('message_id')
def mail_read(message_id):
    """Read a single Gmail message by ID."""
    try:
        message = sdk_mail.get_message(message_id, format='full')
        click.echo(json.dumps(message, indent=2, default=str))
    except Exception as e:
        logger.critical(f"Mail read failed for {message_id}: {e}", exc_info=True)
        sys.exit(1)


@mail.command("label")
@click.argument('message_id')
@click.argument('label_name')
@click.option('--remove', is_flag=True,
              help='Remove the label instead of adding it.')
def mail_label(message_id, label_name, remove):
    """Add or remove a label on a message."""
    try:
        if remove:
            updated = sdk_mail.remove_label(message_id, label_name)
        else:
            updated = sdk_mail.add_label(message_id, label_name)
        click.echo(json.dumps(updated, indent=2))
    except Exception as e:
        logger.critical(f"Mail label failed for {message_id}: {e}", exc_info=True)
        sys.exit(1)


gwsa.add_command(mail)
gwsa.add_command(sheets_module, name='sheets')
gwsa.add_command(docs_module, name='docs')
gwsa.add_command(drive_module, name='drive')
gwsa.add_command(chat_module, name='chat')

mail.add_command(threads_module, name='threads')


def main():
    """Entry point for the CLI."""
    load_dotenv()
    gwsa()


if __name__ == '__main__':
    main()
