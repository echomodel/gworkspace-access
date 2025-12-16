"""CLI commands for interacting with Gmail threads."""

import click
import json
from gwsa.sdk.mail.read import get_thread
from gwsa.cli.decorators import require_scopes

@click.group()
def threads():
    """Commands for interacting with Gmail threads."""
    pass

@threads.command()
@click.argument('thread_id')
@require_scopes('mail-read')
def get(thread_id: str):
    """
    Retrieve a full Gmail thread, including all its messages.
    """
    try:
        thread = get_thread(thread_id=thread_id)
        click.echo(json.dumps(thread, indent=2))
    except Exception as e:
        click.echo(f"Error getting thread: {e}", err=True)