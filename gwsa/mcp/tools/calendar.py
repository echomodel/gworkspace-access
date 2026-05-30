"""Google Calendar MCP tools.

Plain async functions; mcp-app discovers them automatically. Each
tool delegates to ``gwsa.sdk.calendar`` — the SDK is the single point
of credential resolution and Google API access.

Every tool accepts an optional ``account`` parameter: pass either
the account ``name`` (e.g. ``"work"``) or its Google ``email`` (e.g.
``"alice@example.com"``) to operate as a specific account on the
current user's profile. Omit to use the user's ``default_account``
(or the sole account if only one is configured).

Event availability (Free/Busy) maps to the Calendar API
``transparency`` field. All-day events default to **Free**; timed
events default to **Busy**. The resulting ``transparency`` and
``availability`` are always echoed back so callers can confirm what
was set.
"""

from __future__ import annotations

import logging
from typing import Any, Optional

from gwsa.sdk import calendar

logger = logging.getLogger(__name__)


async def list_calendars(
    account: Optional[str] = None,
) -> dict[str, Any]:
    """List the calendars on the user's calendar list.

    Args:
        account: Optional account selector (name or email). Omit to
            use the user's default account.

    Returns:
        Dict with ``calendars`` (each ``{id, summary, primary,
        access_role}``) and ``count``.
    """
    try:
        return calendar.list_calendars(account=account)
    except Exception as e:
        logger.error(f"Error listing calendars: {e}")
        return {"error": str(e)}


async def list_events(
    calendar_id: str = "primary",
    time_min: Optional[str] = None,
    time_max: Optional[str] = None,
    query: Optional[str] = None,
    max_results: int = 50,
    account: Optional[str] = None,
) -> dict[str, Any]:
    """List calendar events within an optional time window.

    Args:
        calendar_id: Calendar to read (default ``"primary"``).
        time_min: RFC3339 lower bound (inclusive), e.g.
            ``"2026-06-01T00:00:00Z"``.
        time_max: RFC3339 upper bound (exclusive).
        query: Free-text search over event fields.
        max_results: Maximum number of events to return.
        account: Optional account selector (name or email).

    Returns:
        Dict with ``events`` (each normalized, including
        ``availability``) and ``count``.
    """
    try:
        return calendar.list_events(
            calendar_id=calendar_id,
            time_min=time_min,
            time_max=time_max,
            query=query,
            max_results=max_results,
            account=account,
        )
    except Exception as e:
        logger.error(f"Error listing events: {e}")
        return {"error": str(e)}


async def create_event(
    summary: str,
    start: str,
    end: str,
    calendar_id: str = "primary",
    description: Optional[str] = None,
    all_day: bool = False,
    availability: Optional[str] = None,
    time_zone: Optional[str] = None,
    account: Optional[str] = None,
) -> dict[str, Any]:
    """Create a calendar event.

    Args:
        summary: Event title.
        start: Start time. RFC3339 datetime (e.g.
            ``"2026-06-01T09:00:00-05:00"``) for timed events, or a
            ``YYYY-MM-DD`` date for all-day events.
        end: End time, same format as ``start``. For all-day events the
            end date is exclusive.
        calendar_id: Target calendar (default ``"primary"``).
        description: Optional event description.
        all_day: Whether this is an all-day event.
        availability: ``"free"`` or ``"busy"``. Omit to use the default
            — all-day events default to **Free**, timed events to
            **Busy**.
        time_zone: IANA time zone for timed events (e.g.
            ``"America/Chicago"``).
        account: Optional account selector (name or email).

    Returns:
        Normalized event dict including the resulting ``transparency``
        and ``availability``.
    """
    try:
        return calendar.create_event(
            summary,
            start,
            end,
            calendar_id=calendar_id,
            description=description,
            all_day=all_day,
            availability=availability,
            time_zone=time_zone,
            account=account,
        )
    except Exception as e:
        logger.error(f"Error creating event: {e}")
        return {"error": str(e)}


async def update_event(
    event_id: str,
    calendar_id: str = "primary",
    summary: Optional[str] = None,
    description: Optional[str] = None,
    start: Optional[str] = None,
    end: Optional[str] = None,
    all_day: bool = False,
    availability: Optional[str] = None,
    time_zone: Optional[str] = None,
    account: Optional[str] = None,
) -> dict[str, Any]:
    """Update fields on an existing calendar event (partial).

    Only the fields you pass are changed. Pass ``availability``
    (``"free"`` or ``"busy"``) to flip the event's Free/Busy state;
    omit it to leave the current transparency unchanged.

    Args:
        event_id: The event ID to update.
        calendar_id: Calendar the event lives on (default ``"primary"``).
        summary: New title, if changing.
        description: New description, if changing.
        start: New start time, if changing.
        end: New end time, if changing.
        all_day: Whether provided ``start``/``end`` are all-day dates.
        availability: ``"free"`` or ``"busy"`` to change Free/Busy.
        time_zone: IANA time zone for timed ``start``/``end``.
        account: Optional account selector (name or email).

    Returns:
        Normalized event dict including the resulting ``transparency``
        and ``availability``.
    """
    try:
        return calendar.update_event(
            event_id,
            calendar_id=calendar_id,
            summary=summary,
            description=description,
            start=start,
            end=end,
            all_day=all_day,
            availability=availability,
            time_zone=time_zone,
            account=account,
        )
    except Exception as e:
        logger.error(f"Error updating event: {e}")
        return {"error": str(e)}


async def delete_event(
    event_id: str,
    calendar_id: str = "primary",
    account: Optional[str] = None,
) -> dict[str, Any]:
    """Delete a calendar event.

    Args:
        event_id: The event ID to delete.
        calendar_id: Calendar the event lives on (default ``"primary"``).
        account: Optional account selector (name or email).

    Returns:
        Dict with ``deleted``, ``event_id``, and ``calendar_id``.
    """
    try:
        return calendar.delete_event(
            event_id, calendar_id=calendar_id, account=account
        )
    except Exception as e:
        logger.error(f"Error deleting event: {e}")
        return {"error": str(e)}
