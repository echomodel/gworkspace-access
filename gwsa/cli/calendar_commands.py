"""CLI commands for Google Calendar operations."""

import json
import click

from gwsa.sdk import calendar as sdk_calendar
from .decorators import require_scopes


@click.group()
def calendar():
    """Commands for interacting with Google Calendar."""
    pass


@calendar.command("calendars")
@require_scopes("calendar-read")
def list_calendars():
    """List the user's calendars."""
    try:
        result = sdk_calendar.list_calendars()
        click.echo(json.dumps(result, indent=2))
    except Exception as e:
        raise click.ClickException(f"An error occurred: {e}")


@calendar.command("events")
@click.option("--calendar-id", default="primary", help="Calendar to read.")
@click.option("--time-min", default=None, help="RFC3339 lower bound (inclusive).")
@click.option("--time-max", default=None, help="RFC3339 upper bound (exclusive).")
@click.option("--query", "-q", default=None, help="Free-text search.")
@click.option("--max-results", type=int, default=50, help="Maximum events to return.")
@require_scopes("calendar-read")
def list_events(calendar_id, time_min, time_max, query, max_results):
    """List events on a calendar."""
    try:
        result = sdk_calendar.list_events(
            calendar_id=calendar_id,
            time_min=time_min,
            time_max=time_max,
            query=query,
            max_results=max_results,
        )
        click.echo(json.dumps(result, indent=2))
    except Exception as e:
        raise click.ClickException(f"An error occurred: {e}")


@calendar.command("create")
@click.argument("summary")
@click.argument("start")
@click.argument("end")
@click.option("--calendar-id", default="primary", help="Target calendar.")
@click.option("--description", default=None, help="Event description.")
@click.option("--all-day", is_flag=True, help="Create an all-day event.")
@click.option(
    "--availability",
    type=click.Choice(["free", "busy"]),
    default=None,
    help="Free/Busy. Default: all-day=free, timed=busy.",
)
@click.option("--time-zone", default=None, help="IANA time zone for timed events.")
@require_scopes("calendar")
def create_event(
    summary, start, end, calendar_id, description, all_day,
    availability, time_zone,
):
    """Create an event (START/END are RFC3339 datetimes or YYYY-MM-DD dates)."""
    try:
        result = sdk_calendar.create_event(
            summary,
            start,
            end,
            calendar_id=calendar_id,
            description=description,
            all_day=all_day,
            availability=availability,
            time_zone=time_zone,
        )
        click.echo(json.dumps(result, indent=2))
    except Exception as e:
        raise click.ClickException(f"An error occurred: {e}")


@calendar.command("update")
@click.argument("event_id")
@click.option("--calendar-id", default="primary", help="Calendar the event lives on.")
@click.option("--summary", default=None, help="New title.")
@click.option("--description", default=None, help="New description.")
@click.option("--start", default=None, help="New start time.")
@click.option("--end", default=None, help="New end time.")
@click.option("--all-day", is_flag=True, help="Provided start/end are all-day dates.")
@click.option(
    "--availability",
    type=click.Choice(["free", "busy"]),
    default=None,
    help="Change Free/Busy. Omit to leave unchanged.",
)
@click.option("--time-zone", default=None, help="IANA time zone for timed start/end.")
@require_scopes("calendar")
def update_event(
    event_id, calendar_id, summary, description, start, end,
    all_day, availability, time_zone,
):
    """Update fields on a calendar event."""
    try:
        result = sdk_calendar.update_event(
            event_id,
            calendar_id=calendar_id,
            summary=summary,
            description=description,
            start=start,
            end=end,
            all_day=all_day,
            availability=availability,
            time_zone=time_zone,
        )
        click.echo(json.dumps(result, indent=2))
    except Exception as e:
        raise click.ClickException(f"An error occurred: {e}")


@calendar.command("delete")
@click.argument("event_id")
@click.option("--calendar-id", default="primary", help="Calendar the event lives on.")
@require_scopes("calendar")
def delete_event(event_id, calendar_id):
    """Delete a calendar event."""
    try:
        result = sdk_calendar.delete_event(event_id, calendar_id=calendar_id)
        click.echo(json.dumps(result, indent=2))
    except Exception as e:
        raise click.ClickException(f"An error occurred: {e}")


if __name__ == "__main__":
    calendar()
