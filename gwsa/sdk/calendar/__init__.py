"""Google Calendar SDK - calendar and event operations."""

from .service import get_calendar_service
from .events import (
    create_event,
    update_event,
    get_event,
    delete_event,
)
from .list import list_calendars, list_events

__all__ = [
    "get_calendar_service",
    "create_event",
    "update_event",
    "get_event",
    "delete_event",
    "list_calendars",
    "list_events",
]
