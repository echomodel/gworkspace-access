"""Google Calendar listing operations: calendars and events."""

from typing import Optional

from .events import _normalize
from .service import get_calendar_service


def list_calendars(account: Optional[str] = None) -> dict:
    """List the calendars on the user's calendar list.

    Args:
        account: Optional account selector (name or email).

    Returns:
        Dict with ``calendars`` (list of ``{id, summary, primary,
        access_role}``) and ``count``.
    """
    service = get_calendar_service(account=account)
    result = service.calendarList().list().execute()
    calendars = [
        {
            "id": item.get("id"),
            "summary": item.get("summary"),
            "primary": item.get("primary", False),
            "access_role": item.get("accessRole"),
        }
        for item in result.get("items", [])
    ]
    return {"calendars": calendars, "count": len(calendars)}


def list_events(
    *,
    calendar_id: str = "primary",
    time_min: Optional[str] = None,
    time_max: Optional[str] = None,
    query: Optional[str] = None,
    max_results: int = 50,
    account: Optional[str] = None,
) -> dict:
    """List events on a calendar within an optional time window.

    Args:
        calendar_id: Calendar to read (default ``"primary"``).
        time_min: RFC3339 lower bound (inclusive) for event end times.
        time_max: RFC3339 upper bound (exclusive) for event start times.
        query: Free-text search over event fields.
        max_results: Maximum number of events to return.
        account: Optional account selector (name or email).

    Returns:
        Dict with ``events`` (normalized, including ``availability``)
        and ``count``. Events are returned in start-time order.
    """
    service = get_calendar_service(account=account)
    params = {
        "calendarId": calendar_id,
        "maxResults": max_results,
        "singleEvents": True,
        "orderBy": "startTime",
    }
    if time_min is not None:
        params["timeMin"] = time_min
    if time_max is not None:
        params["timeMax"] = time_max
    if query is not None:
        params["q"] = query

    result = service.events().list(**params).execute()
    events = [_normalize(item) for item in result.get("items", [])]
    return {"events": events, "count": len(events)}
