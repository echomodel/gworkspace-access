"""Unit tests for Google Sheets tools (SDK + MCP wrappers).

Sociable tests: real SDK code paths, fake Sheets/Drive services
injected at the service-factory boundary. No mcp-app server, no
network.

The fakes record the request parameters the SDK sends so tests can
assert the API contract (value input options, append semantics, the
tail-read range arithmetic) rather than implementation details.
"""

from __future__ import annotations

import pytest

from gwsa.mcp.tools import sheets as sheets_tools


class FakeExecute:
    def __init__(self, result):
        self._result = result

    def execute(self):
        return self._result


class FakeValues:
    """Fake ``service.spreadsheets().values()`` collection."""

    def __init__(self, store):
        self._store = store

    def get(self, spreadsheetId, range, valueRenderOption=None,
            majorDimension=None):
        self._store.setdefault("value_gets", []).append({
            "spreadsheetId": spreadsheetId,
            "range": range,
            "valueRenderOption": valueRenderOption,
            "majorDimension": majorDimension,
        })
        data = self._store.get("ranges", {}).get(range)
        if data is None:
            data = {"range": range, "values": []}
        return FakeExecute(data)

    def update(self, spreadsheetId, range, valueInputOption, body):
        self._store["update"] = {
            "spreadsheetId": spreadsheetId,
            "range": range,
            "valueInputOption": valueInputOption,
            "body": body,
        }
        rows = body.get("values", [])
        return FakeExecute({
            "updatedRange": range,
            "updatedRows": len(rows),
            "updatedColumns": max((len(r) for r in rows), default=0),
            "updatedCells": sum(len(r) for r in rows),
        })

    def append(self, spreadsheetId, range, valueInputOption,
               insertDataOption, body):
        self._store["append"] = {
            "spreadsheetId": spreadsheetId,
            "range": range,
            "valueInputOption": valueInputOption,
            "insertDataOption": insertDataOption,
            "body": body,
        }
        rows = body.get("values", [])
        return FakeExecute({
            "updates": {
                "updatedRange": f"Log!A5:C{4 + len(rows)}",
                "updatedRows": len(rows),
                "updatedCells": sum(len(r) for r in rows),
            }
        })


class FakeSpreadsheets:
    def __init__(self, store):
        self._store = store

    def create(self, body, fields=None):
        self._store["create"] = {"body": body, "fields": fields}
        sheets_props = body.get("sheets") or [
            {"properties": {"title": "Sheet1"}}
        ]
        return FakeExecute({
            "spreadsheetId": "ss-new",
            "properties": {"title": body["properties"]["title"]},
            "sheets": sheets_props,
        })

    def get(self, spreadsheetId, fields=None):
        self._store["metadata_get"] = {
            "spreadsheetId": spreadsheetId, "fields": fields,
        }
        return FakeExecute(self._store.get("metadata", {
            "spreadsheetId": spreadsheetId,
            "properties": {"title": "A Sheet"},
            "sheets": [{"properties": {
                "sheetId": 0, "title": "Sheet1",
                "gridProperties": {"rowCount": 1000, "columnCount": 26},
            }}],
        }))

    def values(self):
        return FakeValues(self._store)


class FakeSheetsService:
    def __init__(self, store):
        self._store = store

    def spreadsheets(self):
        return FakeSpreadsheets(self._store)


class FakeDriveFiles:
    def __init__(self, store):
        self._store = store

    def get(self, fileId, fields=None, supportsAllDrives=None):
        self._store["drive_get"] = {"fileId": fileId, "fields": fields}
        return FakeExecute({"parents": ["root-folder"]})

    def update(self, fileId, addParents=None, removeParents=None,
               supportsAllDrives=None, fields=None):
        self._store["drive_update"] = {
            "fileId": fileId,
            "addParents": addParents,
            "removeParents": removeParents,
        }
        return FakeExecute({"id": fileId, "parents": [addParents]})

    def list(self, q=None, pageSize=None, pageToken=None, fields=None,
             orderBy=None):
        self._store["drive_list"] = {"q": q, "pageSize": pageSize}
        return FakeExecute(self._store.get("drive_list_data", {"files": []}))


class FakeDriveService:
    def __init__(self, store):
        self._store = store

    def files(self):
        return FakeDriveFiles(self._store)


@pytest.fixture
def patch_sheets_service(monkeypatch):
    store: dict = {}

    def fake_sheets_factory(account=None):
        return FakeSheetsService(store)

    def fake_drive_factory(account=None):
        return FakeDriveService(store)

    monkeypatch.setattr(
        "gwsa.sdk.sheets.create.get_sheets_service", fake_sheets_factory
    )
    monkeypatch.setattr(
        "gwsa.sdk.sheets.create.get_drive_service", fake_drive_factory
    )
    monkeypatch.setattr(
        "gwsa.sdk.sheets.read.get_sheets_service", fake_sheets_factory
    )
    monkeypatch.setattr(
        "gwsa.sdk.sheets.update.get_sheets_service", fake_sheets_factory
    )
    monkeypatch.setattr(
        "gwsa.sdk.sheets.list.get_drive_service", fake_drive_factory
    )
    return store


# ---------------------------------------------------------------------------
# create
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_create_returns_id_title_url(patch_sheets_service):
    store = patch_sheets_service
    result = await sheets_tools.sheets_create(title="Daily Energy Log")
    assert result["id"] == "ss-new"
    assert result["title"] == "Daily Energy Log"
    assert result["url"].endswith("/d/ss-new/edit")
    assert result["sheets"] == ["Sheet1"]
    # No folder given → no Drive move.
    assert "drive_update" not in store


@pytest.mark.asyncio
async def test_create_in_folder_moves_via_drive(patch_sheets_service):
    store = patch_sheets_service
    await sheets_tools.sheets_create(
        title="Daily Energy Log", folder_id="folder-123"
    )
    assert store["drive_update"]["fileId"] == "ss-new"
    assert store["drive_update"]["addParents"] == "folder-123"
    assert store["drive_update"]["removeParents"] == "root-folder"


@pytest.mark.asyncio
async def test_create_with_sheet_title_names_first_tab(patch_sheets_service):
    store = patch_sheets_service
    result = await sheets_tools.sheets_create(
        title="Daily Energy Log", sheet_title="Log"
    )
    body = store["create"]["body"]
    assert body["sheets"][0]["properties"]["title"] == "Log"
    assert result["sheets"] == ["Log"]


# ---------------------------------------------------------------------------
# read / metadata
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_read_returns_values(patch_sheets_service):
    store = patch_sheets_service
    store["ranges"] = {
        "Log!A1:B2": {
            "range": "Log!A1:B2",
            "values": [["Date", "Energy"], ["2026-06-12", "4"]],
        }
    }
    result = await sheets_tools.sheets_read("ss-1", "Log!A1:B2")
    assert result["values"][1] == ["2026-06-12", "4"]


@pytest.mark.asyncio
async def test_read_empty_range_returns_empty_values(patch_sheets_service):
    result = await sheets_tools.sheets_read("ss-1", "Log!Z100:Z200")
    assert result["values"] == []


@pytest.mark.asyncio
async def test_get_metadata_normalizes_tabs(patch_sheets_service):
    result = await sheets_tools.sheets_get_metadata("ss-1")
    assert result["id"] == "ss-1"
    assert result["sheets"][0]["title"] == "Sheet1"
    assert result["sheets"][0]["row_count"] == 1000
    assert result["url"].endswith("/d/ss-1/edit")


# ---------------------------------------------------------------------------
# update / append
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_update_defaults_to_user_entered(patch_sheets_service):
    store = patch_sheets_service
    result = await sheets_tools.sheets_update(
        "ss-1", "Log!A2:C2", [["2026-06-12", "07:10", 4]]
    )
    assert store["update"]["valueInputOption"] == "USER_ENTERED"
    assert result["updated_rows"] == 1
    assert result["updated_cells"] == 3


@pytest.mark.asyncio
async def test_update_raw_passthrough(patch_sheets_service):
    store = patch_sheets_service
    await sheets_tools.sheets_update(
        "ss-1", "Log!A2", [["raw text"]], value_input_option="RAW"
    )
    assert store["update"]["valueInputOption"] == "RAW"


@pytest.mark.asyncio
async def test_append_uses_insert_rows(patch_sheets_service):
    store = patch_sheets_service
    result = await sheets_tools.sheets_append(
        "ss-1", [["2026-06-12", "07:10", 4]], range_name="Log!A1"
    )
    assert store["append"]["insertDataOption"] == "INSERT_ROWS"
    assert store["append"]["range"] == "Log!A1"
    assert result["updated_rows"] == 1
    assert result["updated_range"].startswith("Log!")


# ---------------------------------------------------------------------------
# read_tail — the range arithmetic is the point
# ---------------------------------------------------------------------------


def _tail_store(store, n_data_rows, sheet=None):
    """Populate fake ranges for a log with a header + N data rows.

    Serves every bounded sub-range read ("{start}:{end}") so cursor
    pagination walks can read any slice of the synthetic log.
    """
    prefix = f"'{sheet}'!" if sheet else ""
    dates = [f"2026-06-{d:02d}" for d in range(1, n_data_rows + 1)]
    store["ranges"] = {
        f"{prefix}A:A": {"values": [["Date"] + dates]},
        f"{prefix}1:1": {"values": [["Date", "Energy"]]},
    }
    last_row = n_data_rows + 1
    for start in range(2, last_row + 1):
        for end in range(start, last_row + 1):
            rng = f"{prefix}{start}:{end}"
            store["ranges"][rng] = {
                "values": [
                    [dates[r - 2], str(r)] for r in range(start, end + 1)
                ]
            }


@pytest.mark.asyncio
async def test_read_tail_returns_last_n_with_row_numbers(
    patch_sheets_service,
):
    store = patch_sheets_service
    _tail_store(store, n_data_rows=30)  # header row 1, data rows 2..31
    result = await sheets_tools.sheets_read_tail("ss-1", n=7)
    assert result["header"] == ["Date", "Energy"]
    assert len(result["values"]) == 7
    assert result["start_row"] == 25
    assert result["end_row"] == 31
    assert result["has_more"] is True
    # Efficiency contract: the data read was bounded, not the whole sheet.
    data_reads = [
        g for g in store["value_gets"] if g["range"] not in ("A:A", "1:1")
    ]
    assert data_reads == [
        {
            "spreadsheetId": "ss-1",
            "range": "25:31",
            "valueRenderOption": "FORMATTED_VALUE",
            "majorDimension": None,
        }
    ]


@pytest.mark.asyncio
async def test_read_tail_n_larger_than_data(patch_sheets_service):
    store = patch_sheets_service
    _tail_store(store, n_data_rows=3)  # data rows 2..4
    result = await sheets_tools.sheets_read_tail("ss-1", n=10)
    assert len(result["values"]) == 3
    assert result["start_row"] == 2
    assert result["end_row"] == 4
    assert result["has_more"] is False


@pytest.mark.asyncio
async def test_read_tail_empty_sheet(patch_sheets_service):
    store = patch_sheets_service
    store["ranges"] = {"A:A": {"values": []}}
    result = await sheets_tools.sheets_read_tail("ss-1", n=5)
    assert result["values"] == []
    assert result["start_row"] is None
    assert result["end_row"] is None
    assert result["has_more"] is False


@pytest.mark.asyncio
async def test_read_tail_header_only(patch_sheets_service):
    store = patch_sheets_service
    store["ranges"] = {
        "A:A": {"values": [["Date"]]},
        "1:1": {"values": [["Date", "Energy"]]},
    }
    result = await sheets_tools.sheets_read_tail("ss-1", n=5)
    assert result["header"] == ["Date", "Energy"]
    assert result["values"] == []
    assert result["has_more"] is False


@pytest.mark.asyncio
async def test_read_tail_targets_named_tab(patch_sheets_service):
    store = patch_sheets_service
    _tail_store(store, n_data_rows=5, sheet="Log")
    result = await sheets_tools.sheets_read_tail("ss-1", n=2, sheet="Log")
    assert result["end_row"] == 6
    probe = store["value_gets"][0]
    assert probe["range"] == "'Log'!A:A"
    assert probe["majorDimension"] == "COLUMNS"


# ---------------------------------------------------------------------------
# read_tail — cursor pagination (before_row)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_cursor_page_is_single_bounded_read(patch_sheets_service):
    """A before_row page skips the extent probe and header fetch."""
    store = patch_sheets_service
    _tail_store(store, n_data_rows=30)  # data rows 2..31
    result = await sheets_tools.sheets_read_tail(
        "ss-1", n=7, before_row=25, include_header=False,
    )
    assert result["header"] is None
    assert result["start_row"] == 18
    assert result["end_row"] == 24
    assert result["has_more"] is True
    # Exactly ONE API call, and it was bounded.
    assert [g["range"] for g in store["value_gets"]] == ["18:24"]


@pytest.mark.asyncio
async def test_cursor_walk_terminates_at_first_data_row(
    patch_sheets_service,
):
    """Paging newest→oldest covers all rows exactly once and stops."""
    store = patch_sheets_service
    _tail_store(store, n_data_rows=10)  # data rows 2..11
    seen_ranges = []
    page = await sheets_tools.sheets_read_tail("ss-1", n=4)
    seen_ranges.append((page["start_row"], page["end_row"]))
    while page["has_more"]:
        page = await sheets_tools.sheets_read_tail(
            "ss-1", n=4, before_row=page["start_row"],
            include_header=False,
        )
        seen_ranges.append((page["start_row"], page["end_row"]))
    # 10 data rows in pages of 4: (8,11), (4,7), (2,3) — no overlap,
    # no gap, never pages into the header row.
    assert seen_ranges == [(8, 11), (4, 7), (2, 3)]


@pytest.mark.asyncio
async def test_cursor_at_first_data_row_returns_empty(
    patch_sheets_service,
):
    store = patch_sheets_service
    _tail_store(store, n_data_rows=5)
    result = await sheets_tools.sheets_read_tail(
        "ss-1", n=4, before_row=2, include_header=False,
    )
    assert result["values"] == []
    assert result["start_row"] is None
    assert result["has_more"] is False
    # No reads at all — the bounds alone prove there's nothing left.
    assert store.get("value_gets", []) == []


@pytest.mark.asyncio
async def test_headerless_sheet_pages_to_row_one(patch_sheets_service):
    store = patch_sheets_service
    store["ranges"] = {
        "1:3": {"values": [["a"], ["b"], ["c"]]},
    }
    result = await sheets_tools.sheets_read_tail(
        "ss-1", n=5, before_row=4, has_header=False,
    )
    assert result["header"] is None
    assert result["start_row"] == 1
    assert result["end_row"] == 3
    assert result["has_more"] is False


# ---------------------------------------------------------------------------
# list
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_filters_spreadsheet_mimetype(patch_sheets_service):
    store = patch_sheets_service
    store["drive_list_data"] = {
        "files": [{
            "id": "ss-9", "name": "Daily Energy Log",
            "modifiedTime": "2026-06-12T00:00:00Z",
            "createdTime": "2026-06-12T00:00:00Z",
            "owners": [{"emailAddress": "me@example.com"}],
        }]
    }
    result = await sheets_tools.sheets_list(query="Energy")
    assert "spreadsheet" in store["drive_list"]["q"]
    assert "Energy" in store["drive_list"]["q"]
    assert result["spreadsheets"][0]["id"] == "ss-9"
    assert result["spreadsheets"][0]["url"].endswith("/d/ss-9/edit")
