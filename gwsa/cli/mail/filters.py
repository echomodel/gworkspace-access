"""``gwsa mail filters`` — Gmail filters (``users.settings.filters``).

Thin Click wrappers over ``gwsa.sdk.mail.filters``.
"""

import json
import sys

import click

from gwsa.sdk import mail as sdk_mail
from gwsa.sdk.mail.filters import SIZE_COMPARISONS


def _fail(e: Exception) -> None:
    click.echo(f"Error: {e}", err=True)
    sys.exit(1)


@click.group()
def filters():
    """Gmail filters: rules Gmail applies to mail as it arrives.

    A filter never changes mail already in the mailbox. There is no
    update: to change a filter, create the replacement, then delete the
    old one by id.
    """
    pass


@filters.command("list")
def filters_list():
    """List every filter with its id, criteria, action, and a summary line."""
    try:
        click.echo(json.dumps(sdk_mail.list_filters(), indent=2, ensure_ascii=False))
    except Exception as e:
        _fail(e)


@filters.command("get")
@click.argument("filter_id")
def filters_get(filter_id):
    """Show one filter by id."""
    try:
        click.echo(json.dumps(sdk_mail.get_filter(filter_id), indent=2, ensure_ascii=False))
    except Exception as e:
        _fail(e)


@filters.command("create")
@click.option("--from", "from_address", default=None,
              help="Sender to match: address, display name, or @domain.")
@click.option("--to", "to_address", default=None, help="Recipient to match.")
@click.option("--subject", default=None, help="Subject phrase to match.")
@click.option("--query", default=None, help="Gmail search query that must match.")
@click.option("--negated-query", default=None,
              help="Gmail search query that must not match.")
@click.option("--has-attachment", is_flag=True, default=False,
              help="Match only mail with attachments.")
@click.option("--size", type=int, default=None,
              help="Message size threshold in bytes (needs --size-comparison).")
@click.option("--size-comparison", type=click.Choice(SIZE_COMPARISONS), default=None,
              help="How the message size compares to --size.")
@click.option("--add", "add_labels", multiple=True,
              help="Label name to add (repeatable). Created if missing. "
                   "STARRED, IMPORTANT, TRASH, SPAM are system labels.")
@click.option("--remove", "remove_labels", multiple=True,
              help="Label name to remove (repeatable). INBOX archives, "
                   "UNREAD marks read.")
@click.option("--forward", default=None,
              help="Forward to this address (must already be verified in Gmail).")
def filters_create(from_address, to_address, subject, query, negated_query,
                   has_attachment, size, size_comparison, add_labels,
                   remove_labels, forward):
    """Create a filter. Refuses a duplicate of an existing filter's criteria.

    Examples:

        gwsa mail filters create --from jira@example.com --remove INBOX
        gwsa mail filters create --query "list:deals" --remove INBOX --remove UNREAD
        gwsa mail filters create --from boss@example.com --add STARRED
    """
    try:
        created = sdk_mail.create_filter(
            from_address=from_address,
            to_address=to_address,
            subject=subject,
            query=query,
            negated_query=negated_query,
            has_attachment=has_attachment or None,
            size=size,
            size_comparison=size_comparison,
            add_labels=list(add_labels) or None,
            remove_labels=list(remove_labels) or None,
            forward=forward,
        )
        click.echo(json.dumps(created, indent=2, ensure_ascii=False))
    except Exception as e:
        _fail(e)


@filters.command("delete")
@click.argument("filter_id")
def filters_delete(filter_id):
    """Delete one filter by id (from 'filters list')."""
    try:
        click.echo(json.dumps(sdk_mail.delete_filter(filter_id), indent=2))
    except Exception as e:
        _fail(e)
