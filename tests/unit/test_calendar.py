"""Unit tests for Google Calendar tools (SDK + MCP wrappers).

Sociable tests: real SDK code paths, a fake Calendar service injected
at the service-factory boundary. No mcp-app server, no network.

The fake mimics the Calendar API's notable quirk: ``transparency`` is
echoed back only when explicitly set, and omitted when it would be the
default ``opaque``. That is exactly the behavior the normalization in
``gwsa.sdk.calendar.events`` exists to paper over, so the fake must
reproduce it for the tests to be meaningful.
"""

from __future__ import annotations

import pytest

from gwsa.mcp.tools import calendar as calendar_tools


class FakeExecute:
    def __init__(self, result):
        self._result = result

    def execute(self):
        return self._result


class FakeEvents:
    """Fake ``service.events()`` collection that behaves like the API."""

    def __init__(self, store):
        self._store = store

    def _materialize(self, body, event_id):
        # Mirror the real API: reflect the body, assign an id and link,
        # and OMIT transparency when it wasn't set (the API only returns
        # it for the non-default 'transparent').
        event = dict(body)
        event["id"] = event_id
        event["htmlLink"] = f"https://calendar.google.com/event?eid={event_id}"
        event["status"] = "confirmed"
        return event

    def insert(self, calendarId, body):
        self._store["inserted"] = {"calendarId": calendarId, "body": body}
        return FakeExecute(self._materialize(body, "evt-new"))

    def patch(self, calendarId, eventId, body):
        self._store["patched"] = {
            "calendarId": calendarId,
            "eventId": eventId,
            "body": body,
        }
        return FakeExecute(self._materialize(body, eventId))

    def get(self, calendarId, eventId):
        return FakeExecute(self._store.get("get_data", {"id": eventId}))

    def delete(self, calendarId, eventId):
        self._store["deleted"] = {"calendarId": calendarId, "eventId": eventId}
        return FakeExecute(None)

    def list(self, **params):
        self._store["list_params"] = params
        return FakeExecute(self._store.get("list_data", {"items": []}))


class FakeCalendarList:
    def __init__(self, store):
        self._store = store

    def list(self):
        return FakeExecute(self._store.get("calendars_data", {"items": []}))


class FakeCalendarService:
    def __init__(self, store):
        self._store = store

    def events(self):
        return FakeEvents(self._store)

    def calendarList(self):
        return FakeCalendarList(self._store)


@pytest.fixture
def patch_calendar_service(monkeypatch):
    store: dict = {}

    def fake_factory(account=None):
        return FakeCalendarService(store)

    monkeypatch.setattr(
        "gwsa.sdk.calendar.events.get_calendar_service", fake_factory
    )
    monkeypatch.setattr(
        "gwsa.sdk.calendar.list.get_calendar_service", fake_factory
    )
    return store


# ---------------------------------------------------------------------------
# create — Free/Busy (#34)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_create_event_free_sets_transparent(patch_calendar_service):
    store = patch_calendar_service
    result = await calendar_tools.create_event(
        summary="Lunch", start="2026-06-01T12:00:00-05:00",
        end="2026-06-01T13:00:00-05:00", availability="free",
    )
    assert store["inserted"]["body"]["transparency"] == "transparent"
    assert result["transparency"] == "transparent"
    assert result["availability"] == "free"


@pytest.mark.asyncio
async def test_create_event_busy_sets_opaque(patch_calendar_service):
    store = patch_calendar_service
    result = await calendar_tools.create_event(
        summary="Meeting", start="2026-06-01T09:00:00-05:00",
        end="2026-06-01T10:00:00-05:00", availability="busy",
    )
    assert store["inserted"]["body"]["transparency"] == "opaque"
    assert result["availability"] == "busy"


@pytest.mark.asyncio
async def test_create_all_day_defaults_to_free(patch_calendar_service):
    """All-day events default to Free, mirroring the Calendar UI (#34)."""
    store = patch_calendar_service
    result = await calendar_tools.create_event(
        summary="Holiday", start="2026-07-04", end="2026-07-05",
        all_day=True,
    )
    # Sent as a date (all-day) and forced transparent.
    assert store["inserted"]["body"]["start"] == {"date": "2026-07-04"}
    assert store["inserted"]["body"]["transparency"] == "transparent"
    assert result["availability"] == "free"


@pytest.mark.asyncio
async def test_create_timed_defaults_to_busy(patch_calendar_service):
    """Timed events keep the API default (Busy) — no transparency sent."""
    store = patch_calendar_service
    result = await calendar_tools.create_event(
        summary="Call", start="2026-06-01T09:00:00-05:00",
        end="2026-06-01T09:30:00-05:00",
    )
    # No transparency in the request body → API default opaque.
    assert "transparency" not in store["inserted"]["body"]
    # ...but the normalized result still reports Busy explicitly.
    assert result["transparency"] == "opaque"
    assert result["availability"] == "busy"


@pytest.mark.asyncio
async def test_create_invalid_availability_returns_error(patch_calendar_service):
    result = await calendar_tools.create_event(
        summary="X", start="2026-06-01T09:00:00-05:00",
        end="2026-06-01T10:00:00-05:00", availability="maybe",
    )
    assert "error" in result
    assert "free" in result["error"] and "busy" in result["error"]


# ---------------------------------------------------------------------------
# update — flip Free/Busy (#34)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_update_busy_to_free(patch_calendar_service):
    store = patch_calendar_service
    result = await calendar_tools.update_event(
        event_id="evt-1", availability="free",
    )
    assert store["patched"]["eventId"] == "evt-1"
    assert store["patched"]["body"]["transparency"] == "transparent"
    assert result["availability"] == "free"


@pytest.mark.asyncio
async def test_update_free_to_busy(patch_calendar_service):
    store = patch_calendar_service
    result = await calendar_tools.update_event(
        event_id="evt-2", availability="busy",
    )
    assert store["patched"]["body"]["transparency"] == "opaque"
    assert result["availability"] == "busy"


@pytest.mark.asyncio
async def test_update_without_availability_leaves_transparency_untouched(
    patch_calendar_service,
):
    """Update must NOT default Free/Busy — only change what's asked."""
    store = patch_calendar_service
    await calendar_tools.update_event(event_id="evt-3", summary="Renamed")
    assert "transparency" not in store["patched"]["body"]
    assert store["patched"]["body"]["summary"] == "Renamed"


# ---------------------------------------------------------------------------
# list + delete
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_events_normalizes_availability(patch_calendar_service):
    store = patch_calendar_service
    store["list_data"] = {
        "items": [
            {"id": "a", "summary": "Busy one"},  # no transparency → busy
            {"id": "b", "summary": "Free one", "transparency": "transparent"},
        ]
    }
    result = await calendar_tools.list_events(time_min="2026-06-01T00:00:00Z")
    assert result["count"] == 2
    assert result["events"][0]["availability"] == "busy"
    assert result["events"][1]["availability"] == "free"
    # singleEvents + startTime ordering requested
    assert store["list_params"]["singleEvents"] is True
    assert store["list_params"]["orderBy"] == "startTime"


@pytest.mark.asyncio
async def test_list_calendars(patch_calendar_service):
    store = patch_calendar_service
    store["calendars_data"] = {
        "items": [
            {"id": "primary", "summary": "Me", "primary": True,
             "accessRole": "owner"},
        ]
    }
    result = await calendar_tools.list_calendars()
    assert result["count"] == 1
    assert result["calendars"][0]["primary"] is True
    assert result["calendars"][0]["access_role"] == "owner"


@pytest.mark.asyncio
async def test_delete_event(patch_calendar_service):
    store = patch_calendar_service
    result = await calendar_tools.delete_event(event_id="evt-9")
    assert result["deleted"] is True
    assert store["deleted"]["eventId"] == "evt-9"
