"""Google Calendar event operations.

Create, read, update, and delete calendar events. The availability
(Free/Busy) of an event maps to the Calendar API ``transparency``
field — ``transparent`` means the event shows as **Free**, ``opaque``
means **Busy**.

All-day events default to **Free** (mirroring the Google Calendar web
UI), while timed events keep the Calendar API default of **Busy**
unless the caller specifies otherwise. The normalized ``transparency``
and ``availability`` are always echoed back in the result so callers
can verify what was set — the raw API omits ``transparency`` when it
is the ``opaque`` default, which otherwise makes "did it work?"
ambiguous.
"""

from typing import Optional

from .service import get_calendar_service

# Free/Busy ⇄ Calendar API transparency mapping.
_AVAILABILITY_TO_TRANSPARENCY = {
    "free": "transparent",
    "busy": "opaque",
}
_TRANSPARENCY_TO_AVAILABILITY = {
    "transparent": "free",
    "opaque": "busy",
}


def _availability_to_transparency(availability: Optional[str]) -> Optional[str]:
    """Map an ``availability`` value to a Calendar ``transparency`` value.

    Returns None when ``availability`` is None (caller wants the API
    default). Raises ValueError for any value other than free/busy.
    """
    if availability is None:
        return None
    key = availability.strip().lower()
    if key not in _AVAILABILITY_TO_TRANSPARENCY:
        raise ValueError(
            f"availability must be 'free' or 'busy', got {availability!r}"
        )
    return _AVAILABILITY_TO_TRANSPARENCY[key]


def _resolve_transparency(
    availability: Optional[str], all_day: bool
) -> Optional[str]:
    """Decide the ``transparency`` to send for a create/update.

    - Explicit ``availability`` always wins.
    - All-day events with no explicit availability default to Free
      (``transparent``), mirroring the Google Calendar UI.
    - Timed events with no explicit availability are left unset so the
      Calendar API default (Busy / ``opaque``) applies.
    """
    explicit = _availability_to_transparency(availability)
    if explicit is not None:
        return explicit
    if all_day:
        return "transparent"
    return None


def _event_time(value: str, all_day: bool, time_zone: Optional[str]) -> dict:
    """Build a Calendar event start/end time object.

    All-day events use a ``date`` (YYYY-MM-DD); timed events use a
    ``dateTime`` (RFC3339) with an optional ``timeZone``.
    """
    if all_day:
        return {"date": value}
    obj = {"dateTime": value}
    if time_zone:
        obj["timeZone"] = time_zone
    return obj


def _normalize(event: dict) -> dict:
    """Summarize a raw Calendar event with normalized availability.

    The Calendar API omits ``transparency`` when it is the default
    ``opaque``. We surface an explicit normalized value plus the
    Free/Busy ``availability`` alias so callers never have to infer it.
    """
    transparency = event.get("transparency", "opaque")
    return {
        "id": event.get("id"),
        "summary": event.get("summary"),
        "description": event.get("description"),
        "start": event.get("start"),
        "end": event.get("end"),
        "status": event.get("status"),
        "html_link": event.get("htmlLink"),
        "transparency": transparency,
        "availability": _TRANSPARENCY_TO_AVAILABILITY.get(
            transparency, "busy"
        ),
    }


def create_event(
    summary: str,
    start: str,
    end: str,
    *,
    calendar_id: str = "primary",
    description: Optional[str] = None,
    all_day: bool = False,
    availability: Optional[str] = None,
    time_zone: Optional[str] = None,
    account: Optional[str] = None,
) -> dict:
    """Create a Google Calendar event.

    Args:
        summary: Event title.
        start: Start time. RFC3339 datetime (e.g.
            ``"2026-06-01T09:00:00-05:00"``) for timed events, or a
            ``YYYY-MM-DD`` date for all-day events.
        end: End time, same format as ``start``. For all-day events the
            Calendar API treats the end date as exclusive.
        calendar_id: Target calendar (default ``"primary"``).
        description: Optional event description.
        all_day: Whether this is an all-day event (uses ``date`` rather
            than ``dateTime``).
        availability: ``"free"`` or ``"busy"``. Omit to use the default:
            all-day events default to Free, timed events to Busy.
        time_zone: IANA time zone for timed events (e.g.
            ``"America/Chicago"``). Ignored for all-day events.
        account: Optional account selector (name or email).

    Returns:
        Normalized event dict including the resulting ``transparency``
        and ``availability``.
    """
    service = get_calendar_service(account=account)
    body = {
        "summary": summary,
        "start": _event_time(start, all_day, time_zone),
        "end": _event_time(end, all_day, time_zone),
    }
    if description is not None:
        body["description"] = description
    transparency = _resolve_transparency(availability, all_day)
    if transparency is not None:
        body["transparency"] = transparency

    event = (
        service.events()
        .insert(calendarId=calendar_id, body=body)
        .execute()
    )
    return _normalize(event)


def update_event(
    event_id: str,
    *,
    calendar_id: str = "primary",
    summary: Optional[str] = None,
    description: Optional[str] = None,
    start: Optional[str] = None,
    end: Optional[str] = None,
    all_day: bool = False,
    availability: Optional[str] = None,
    time_zone: Optional[str] = None,
    account: Optional[str] = None,
) -> dict:
    """Update fields on an existing Google Calendar event (partial patch).

    Only the fields you pass are changed. To flip an event between Free
    and Busy, pass ``availability``. Note that ``availability`` defaults
    are NOT applied on update — if you omit it, the event's current
    transparency is left untouched (an update must not silently change
    Free/Busy on the user's existing event).

    Args:
        event_id: The event ID to update.
        calendar_id: Calendar the event lives on (default ``"primary"``).
        summary: New title, if changing.
        description: New description, if changing.
        start: New start time, if changing.
        end: New end time, if changing.
        all_day: Whether the provided ``start``/``end`` are all-day
            dates. Only relevant when ``start``/``end`` are passed.
        availability: ``"free"`` or ``"busy"`` to change Free/Busy.
            Omit to leave the event's current transparency unchanged.
        time_zone: IANA time zone for timed ``start``/``end``.
        account: Optional account selector (name or email).

    Returns:
        Normalized event dict including the resulting ``transparency``
        and ``availability``.
    """
    service = get_calendar_service(account=account)
    body: dict = {}
    if summary is not None:
        body["summary"] = summary
    if description is not None:
        body["description"] = description
    if start is not None:
        body["start"] = _event_time(start, all_day, time_zone)
    if end is not None:
        body["end"] = _event_time(end, all_day, time_zone)
    # On update we only set transparency when explicitly requested —
    # no all-day default, so we never silently change an existing
    # event's Free/Busy state.
    transparency = _availability_to_transparency(availability)
    if transparency is not None:
        body["transparency"] = transparency

    event = (
        service.events()
        .patch(calendarId=calendar_id, eventId=event_id, body=body)
        .execute()
    )
    return _normalize(event)


def get_event(
    event_id: str,
    *,
    calendar_id: str = "primary",
    account: Optional[str] = None,
) -> dict:
    """Read a single Google Calendar event.

    Args:
        event_id: The event ID.
        calendar_id: Calendar the event lives on (default ``"primary"``).
        account: Optional account selector (name or email).

    Returns:
        Normalized event dict including ``transparency`` and
        ``availability``.
    """
    service = get_calendar_service(account=account)
    event = (
        service.events()
        .get(calendarId=calendar_id, eventId=event_id)
        .execute()
    )
    return _normalize(event)


def delete_event(
    event_id: str,
    *,
    calendar_id: str = "primary",
    account: Optional[str] = None,
) -> dict:
    """Delete a Google Calendar event.

    Args:
        event_id: The event ID to delete.
        calendar_id: Calendar the event lives on (default ``"primary"``).
        account: Optional account selector (name or email).

    Returns:
        Dict with ``deleted`` (True), ``event_id``, and ``calendar_id``.
    """
    service = get_calendar_service(account=account)
    service.events().delete(
        calendarId=calendar_id, eventId=event_id
    ).execute()
    return {
        "deleted": True,
        "event_id": event_id,
        "calendar_id": calendar_id,
    }
