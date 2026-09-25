"""Unit tests for Sheets structural operations (batchUpdate, tabs, rows,
developer metadata) across the SDK, MCP tools, and CLI.

Sociable tests: real SDK / MCP / CLI code paths against a small
*stateful* fake Sheets backend injected at the service-factory
boundary. The fake applies the requests it understands (tabs, row
insert/delete, developer metadata, search) to an in-memory spreadsheet
and records every batchUpdate body, so tests assert both the API
contract sent and the resulting state.
"""

from __future__ import annotations

import copy
import json

import pytest
from click.testing import CliRunner
from googleapiclient.errors import HttpError

from gwsa.cli.sheets_commands import sheets as sheets_cli
from gwsa.mcp.tools import sheets as sheets_tools
from gwsa.sdk import sheets
from gwsa.sdk.sheets.structure import column_to_index, index_to_column


# ---------------------------------------------------------------------------
# stateful fake backend
# ---------------------------------------------------------------------------


class FakeExecute:
    def __init__(self, fn):
        self._fn = fn

    def execute(self):
        return self._fn()


class FakeResp(dict):
    def __init__(self, status):
        super().__init__()
        self.status = status
        self.reason = "fake"


class Backend:
    """In-memory spreadsheet: tabs with row counts, plus developer metadata."""

    def __init__(self):
        self.sheets = [
            {"sheetId": 0, "title": "Sheet1", "index": 0,
             "gridProperties": {"rowCount": 1000, "columnCount": 26}},
        ]
        self.metadata: list[dict] = []
        self.batch_bodies: list[dict] = []
        self.search_bodies: list[dict] = []
        self.get_calls = 0
        self._next_sheet_id = 100
        self._next_md_id = 1
        self.fail_status: int | None = None

    # -- helpers -------------------------------------------------------------

    def _sheet(self, sheet_id):
        for s in self.sheets:
            if s["sheetId"] == sheet_id:
                return s
        raise HttpError(FakeResp(400), b"No grid with id")

    def _maybe_fail(self):
        if self.fail_status:
            raise HttpError(FakeResp(self.fail_status), b"fake failure")

    # -- request application ---------------------------------------------------

    def _apply(self, req: dict) -> dict:
        (kind, body), = req.items()
        if kind == "addSheet":
            props = copy.deepcopy(body.get("properties", {}))
            if any(s["title"] == props["title"] for s in self.sheets):
                raise HttpError(FakeResp(400), b"duplicate title")
            props.setdefault("sheetId", self._next_sheet_id)
            self._next_sheet_id += 1
            props.setdefault("index", len(self.sheets))
            grid = props.setdefault("gridProperties", {})
            grid.setdefault("rowCount", 1000)
            grid.setdefault("columnCount", 26)
            self.sheets.append(props)
            return {"addSheet": {"properties": copy.deepcopy(props)}}
        if kind == "deleteSheet":
            s = self._sheet(body["sheetId"])
            self.sheets.remove(s)
            return {}
        if kind in ("insertDimension", "deleteDimension"):
            rng = body["range"]
            s = self._sheet(rng["sheetId"])
            n = rng["endIndex"] - rng["startIndex"]
            if kind == "insertDimension" and rng["startIndex"] == 0 \
                    and body.get("inheritFromBefore"):
                raise HttpError(FakeResp(400), b"cannot inherit at 0")
            delta = n if kind == "insertDimension" else -n
            s["gridProperties"]["rowCount"] += delta
            # Row-anchored metadata moves with its row, like the real API.
            for md in self.metadata:
                dr = md["location"].get("dimensionRange")
                if dr and dr["sheetId"] == s["sheetId"] \
                        and dr["dimension"] == "ROWS" \
                        and dr["startIndex"] >= rng["startIndex"]:
                    dr["startIndex"] += delta
                    dr["endIndex"] += delta
            return {}
        if kind == "createDeveloperMetadata":
            md = copy.deepcopy(body["developerMetadata"])
            md["metadataId"] = self._next_md_id
            self._next_md_id += 1
            loc = md["location"]
            if loc.get("spreadsheet"):
                loc["locationType"] = "SPREADSHEET"
            elif "sheetId" in loc:
                loc["locationType"] = "SHEET"
            else:
                loc["locationType"] = (
                    "ROW" if loc["dimensionRange"]["dimension"] == "ROWS"
                    else "COLUMN"
                )
            self.metadata.append(md)
            return {"createDeveloperMetadata": {
                "developerMetadata": copy.deepcopy(md)}}
        # Unmodelled requests (formatting, etc.) succeed with no reply.
        return {}

    def batch_update(self, spreadsheetId, body):
        def run():
            self._maybe_fail()
            self.batch_bodies.append(copy.deepcopy(body))
            snapshot = copy.deepcopy((self.sheets, self.metadata))
            try:
                replies = [self._apply(r) for r in body["requests"]]
            except Exception:
                # Atomic: roll back everything on any failure.
                self.sheets, self.metadata = snapshot
                raise
            out = {"spreadsheetId": spreadsheetId, "replies": replies}
            if body.get("includeSpreadsheetInResponse"):
                out["updatedSpreadsheet"] = {
                    "sheets": [{"properties": s} for s in self.sheets]}
            return out
        return FakeExecute(run)

    def get(self, spreadsheetId, fields=None):
        def run():
            self._maybe_fail()
            self.get_calls += 1
            return {"spreadsheetId": spreadsheetId, "sheets": [
                {"properties": copy.deepcopy(s)} for s in self.sheets]}
        return FakeExecute(run)

    def search(self, spreadsheetId, body):
        def run():
            self._maybe_fail()
            self.search_bodies.append(copy.deepcopy(body))
            lookup = body["dataFilters"][0]["developerMetadataLookup"]
            hits = [
                md for md in self.metadata
                if all(md.get(k) == v for k, v in lookup.items())
            ]
            if not hits:
                return {}
            return {"matchedDeveloperMetadata": [
                {"developerMetadata": copy.deepcopy(md)} for md in hits]}
        return FakeExecute(run)


class FakeDevMetadata:
    def __init__(self, backend):
        self._b = backend

    def search(self, spreadsheetId, body):
        return self._b.search(spreadsheetId, body)


class FakeSpreadsheets:
    def __init__(self, backend):
        self._b = backend

    def batchUpdate(self, spreadsheetId, body):
        return self._b.batch_update(spreadsheetId, body)

    def get(self, spreadsheetId, fields=None):
        return self._b.get(spreadsheetId, fields)

    def developerMetadata(self):
        return FakeDevMetadata(self._b)


class FakeService:
    def __init__(self, backend):
        self._b = backend

    def spreadsheets(self):
        return FakeSpreadsheets(self._b)


@pytest.fixture
def backend(monkeypatch):
    b = Backend()
    monkeypatch.setattr(
        "gwsa.sdk.sheets.structure.get_sheets_service",
        lambda account=None: FakeService(b),
    )
    return b


def _add_tab(backend, title):
    return sheets.add_tab("ss-1", title)


# ---------------------------------------------------------------------------
# column helpers
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("col,idx", [
    ("A", 0), ("Z", 25), ("AA", 26), ("AZ", 51), ("BA", 52), ("zz", 701),
    (1, 0), (27, 26),
])
def test_column_to_index(col, idx):
    assert column_to_index(col) == idx


@pytest.mark.parametrize("idx", [0, 25, 26, 51, 52, 701, 702, 18277])
def test_index_to_column_round_trips(idx):
    assert column_to_index(index_to_column(idx)) == idx


@pytest.mark.parametrize("bad", ["", "A1", "1", "-", 0, -3])
def test_column_to_index_rejects_invalid(bad):
    with pytest.raises(ValueError):
        column_to_index(bad)


# ---------------------------------------------------------------------------
# batch_update pass-through
# ---------------------------------------------------------------------------


def test_batch_update_passes_requests_verbatim(backend):
    reqs = [
        {"addSheet": {"properties": {"title": "Archive"}}},
        {"repeatCell": {"range": {"sheetId": 0}, "cell": {},
                        "fields": "userEnteredFormat"}},
    ]
    result = sheets.batch_update("ss-1", reqs)

    assert backend.batch_bodies == [{"requests": reqs}]
    assert result["spreadsheetId"] == "ss-1"
    assert len(result["replies"]) == 2
    assert result["replies"][0]["addSheet"]["properties"]["title"] == "Archive"
    assert result["replies"][1] == {}


def test_batch_update_include_spreadsheet_in_response(backend):
    result = sheets.batch_update(
        "ss-1", [{"addSheet": {"properties": {"title": "X"}}}],
        include_spreadsheet_in_response=True,
    )
    assert backend.batch_bodies[0]["includeSpreadsheetInResponse"] is True
    titles = [s["properties"]["title"]
              for s in result["updatedSpreadsheet"]["sheets"]]
    assert titles == ["Sheet1", "X"]


def test_batch_update_omits_include_flag_by_default(backend):
    sheets.batch_update("ss-1", [{"addSheet": {"properties": {"title": "X"}}}])
    assert "includeSpreadsheetInResponse" not in backend.batch_bodies[0]


def test_batch_update_blocks_delete_sheet_without_flag(backend):
    tab = _add_tab(backend, "Doomed")
    backend.batch_bodies.clear()

    with pytest.raises(sheets.DestructiveRequestError, match="deleteSheet"):
        sheets.batch_update(
            "ss-1", [{"deleteSheet": {"sheetId": tab["sheet_id"]}}])

    # Rejected before any API call; the tab survives.
    assert backend.batch_bodies == []
    assert any(s["title"] == "Doomed" for s in backend.sheets)


def test_batch_update_blocks_delete_sheet_mixed_into_batch(backend):
    tab = _add_tab(backend, "Doomed")
    backend.batch_bodies.clear()
    with pytest.raises(sheets.DestructiveRequestError):
        sheets.batch_update("ss-1", [
            {"addSheet": {"properties": {"title": "Fine"}}},
            {"deleteSheet": {"sheetId": tab["sheet_id"]}},
        ])
    assert backend.batch_bodies == []
    assert not any(s["title"] == "Fine" for s in backend.sheets)


def test_batch_update_allows_delete_sheet_with_flag(backend):
    tab = _add_tab(backend, "Doomed")
    sheets.batch_update(
        "ss-1", [{"deleteSheet": {"sheetId": tab["sheet_id"]}}],
        allow_destructive=True,
    )
    assert [s["title"] for s in backend.sheets] == ["Sheet1"]


def test_delete_dimension_is_not_gated(backend):
    """Row deletion is a normal edit, not behind the destructive gate."""
    sheets.batch_update("ss-1", [{"deleteDimension": {"range": {
        "sheetId": 0, "dimension": "ROWS", "startIndex": 0, "endIndex": 1}}}])
    assert backend.sheets[0]["gridProperties"]["rowCount"] == 999


@pytest.mark.parametrize("bad", [[], {}, None, "x", [1], [{"a": 1}, "b"]])
def test_batch_update_rejects_malformed_requests(backend, bad):
    with pytest.raises(ValueError):
        sheets.batch_update("ss-1", bad)
    assert backend.batch_bodies == []


def test_batch_update_is_atomic_on_api_error(backend):
    """A failing request leaves no partial effects (API contract)."""
    with pytest.raises(HttpError):
        sheets.batch_update("ss-1", [
            {"addSheet": {"properties": {"title": "New"}}},
            {"addSheet": {"properties": {"title": "Sheet1"}}},  # duplicate
        ])
    assert [s["title"] for s in backend.sheets] == ["Sheet1"]


# ---------------------------------------------------------------------------
# add_tab
# ---------------------------------------------------------------------------


def test_add_tab_minimal(backend):
    result = sheets.add_tab("ss-1", "Inventory")
    assert backend.batch_bodies == [{"requests": [
        {"addSheet": {"properties": {"title": "Inventory"}}}]}]
    assert result == {
        "sheet_id": 100, "title": "Inventory", "index": 1,
        "row_count": 1000, "column_count": 26,
    }


def test_add_tab_with_index_and_grid(backend):
    result = sheets.add_tab(
        "ss-1", "Front", index=0, row_count=50, column_count=5)
    props = backend.batch_bodies[0]["requests"][0]["addSheet"]["properties"]
    assert props == {"title": "Front", "index": 0,
                     "gridProperties": {"rowCount": 50, "columnCount": 5}}
    assert (result["index"], result["row_count"], result["column_count"]) \
        == (0, 50, 5)


def test_add_tab_only_row_count(backend):
    sheets.add_tab("ss-1", "T", row_count=10)
    props = backend.batch_bodies[0]["requests"][0]["addSheet"]["properties"]
    assert props["gridProperties"] == {"rowCount": 10}


def test_add_tab_duplicate_title_raises(backend):
    with pytest.raises(HttpError):
        sheets.add_tab("ss-1", "Sheet1")


# ---------------------------------------------------------------------------
# insert_rows / delete_rows
# ---------------------------------------------------------------------------


def test_insert_rows_converts_to_zero_based_range(backend):
    result = sheets.insert_rows("ss-1", start_row=5, count=3)
    req = backend.batch_bodies[0]["requests"][0]["insertDimension"]
    assert req == {
        "range": {"sheetId": 0, "dimension": "ROWS",
                  "startIndex": 4, "endIndex": 7},
        "inheritFromBefore": False,
    }
    assert result == {"sheet_id": 0, "start_row": 5, "end_row": 7, "count": 3}
    assert backend.sheets[0]["gridProperties"]["rowCount"] == 1003


def test_insert_rows_inherit_from_before(backend):
    sheets.insert_rows("ss-1", start_row=2, inherit_from_before=True)
    req = backend.batch_bodies[0]["requests"][0]["insertDimension"]
    assert req["inheritFromBefore"] is True


def test_insert_rows_inherit_from_before_at_row_one_rejected(backend):
    with pytest.raises(ValueError, match="row 1|start_row is 1"):
        sheets.insert_rows("ss-1", start_row=1, inherit_from_before=True)
    assert backend.batch_bodies == []


def test_insert_rows_targets_named_tab(backend):
    tab = _add_tab(backend, "Log")
    backend.batch_bodies.clear()
    result = sheets.insert_rows("ss-1", start_row=2, sheet="Log")
    rng = backend.batch_bodies[0]["requests"][0]["insertDimension"]["range"]
    assert rng["sheetId"] == tab["sheet_id"]
    assert result["sheet_id"] == tab["sheet_id"]


def test_default_sheet_is_first_by_index_not_list_order(backend):
    """With no sheet given, rows target the tab at index 0."""
    front = sheets.add_tab("ss-1", "Front", index=0)
    backend.sheets[0]["index"] = 1  # Sheet1 is now second
    backend.batch_bodies.clear()
    sheets.delete_rows("ss-1", start_row=3)
    rng = backend.batch_bodies[0]["requests"][0]["deleteDimension"]["range"]
    assert rng["sheetId"] == front["sheet_id"]


def test_sheet_id_zero_is_resolved_not_treated_as_missing(backend):
    """sheetId 0 is falsy; make sure it is still used as a real id."""
    _add_tab(backend, "Other")
    backend.batch_bodies.clear()
    sheets.insert_rows("ss-1", start_row=2, sheet="Sheet1")
    rng = backend.batch_bodies[0]["requests"][0]["insertDimension"]["range"]
    assert rng["sheetId"] == 0


def test_delete_rows_converts_to_zero_based_range(backend):
    result = sheets.delete_rows("ss-1", start_row=10, count=2)
    req = backend.batch_bodies[0]["requests"][0]["deleteDimension"]
    assert req == {"range": {"sheetId": 0, "dimension": "ROWS",
                             "startIndex": 9, "endIndex": 11}}
    assert result == {"sheet_id": 0, "start_row": 10, "end_row": 11,
                      "count": 2}
    assert backend.sheets[0]["gridProperties"]["rowCount"] == 998


def test_delete_single_row_default_count(backend):
    result = sheets.delete_rows("ss-1", start_row=1)
    rng = backend.batch_bodies[0]["requests"][0]["deleteDimension"]["range"]
    assert (rng["startIndex"], rng["endIndex"]) == (0, 1)
    assert result["end_row"] == 1


@pytest.mark.parametrize("fn", [sheets.insert_rows, sheets.delete_rows])
@pytest.mark.parametrize("start_row,count", [(0, 1), (-1, 1), (3, 0), (3, -2)])
def test_row_ops_reject_invalid_bounds(backend, fn, start_row, count):
    with pytest.raises(ValueError):
        fn("ss-1", start_row=start_row, count=count)
    assert backend.batch_bodies == []


@pytest.mark.parametrize("fn", [sheets.insert_rows, sheets.delete_rows])
def test_row_ops_unknown_sheet(backend, fn):
    with pytest.raises(sheets.SheetNotFoundError, match="Nope.*Sheet1"):
        fn("ss-1", start_row=2, sheet="Nope")
    assert backend.batch_bodies == []


def test_resolve_sheet_on_empty_spreadsheet(backend):
    backend.sheets.clear()
    with pytest.raises(sheets.SheetNotFoundError):
        sheets.delete_rows("ss-1", start_row=1)


# ---------------------------------------------------------------------------
# set_metadata / find_by_metadata
# ---------------------------------------------------------------------------


def test_set_metadata_spreadsheet_level(backend):
    result = sheets.set_metadata("ss-1", "app", "tracker")
    md = backend.batch_bodies[0]["requests"][0][
        "createDeveloperMetadata"]["developerMetadata"]
    assert md == {"metadataKey": "app", "metadataValue": "tracker",
                  "location": {"spreadsheet": True},
                  "visibility": "DOCUMENT"}
    assert result["location_type"] == "SPREADSHEET"
    assert result["sheet_id"] is None
    assert result["sheet_title"] is None
    assert result["range"] is None
    assert result["metadata_id"] == 1


def test_set_metadata_on_tab(backend):
    tab = _add_tab(backend, "Inventory")
    result = sheets.set_metadata("ss-1", "role", "inventory", sheet="Inventory")
    loc = backend.metadata[0]["location"]
    assert loc["sheetId"] == tab["sheet_id"]
    assert result["location_type"] == "SHEET"
    assert result["sheet_title"] == "Inventory"
    assert result["range"] == "'Inventory'"


def test_set_metadata_on_row(backend):
    result = sheets.set_metadata("ss-1", "row-key", "abc", row=5)
    dr = backend.metadata[0]["location"]["dimensionRange"]
    assert dr == {"sheetId": 0, "dimension": "ROWS",
                  "startIndex": 4, "endIndex": 5}
    assert result["location_type"] == "ROW"
    assert (result["row"], result["end_row"]) == (5, 5)
    assert result["range"] == "'Sheet1'!5:5"


@pytest.mark.parametrize("col,letter,idx", [("C", "C", 2), ("aa", "AA", 26)])
def test_set_metadata_on_column(backend, col, letter, idx):
    result = sheets.set_metadata("ss-1", "col", "amount", column=col)
    dr = backend.metadata[0]["location"]["dimensionRange"]
    assert dr == {"sheetId": 0, "dimension": "COLUMNS",
                  "startIndex": idx, "endIndex": idx + 1}
    assert result["location_type"] == "COLUMN"
    assert result["column"] == letter
    assert result["range"] == f"'Sheet1'!{letter}:{letter}"


def test_set_metadata_key_only_omits_value(backend):
    result = sheets.set_metadata("ss-1", "flag")
    md = backend.batch_bodies[0]["requests"][0][
        "createDeveloperMetadata"]["developerMetadata"]
    assert "metadataValue" not in md
    assert result["value"] is None


def test_set_metadata_project_visibility(backend):
    sheets.set_metadata("ss-1", "k", "v", visibility="PROJECT")
    assert backend.metadata[0]["visibility"] == "PROJECT"


def test_set_metadata_rejects_row_and_column(backend):
    with pytest.raises(ValueError, match="row or column"):
        sheets.set_metadata("ss-1", "k", row=1, column="A")
    assert backend.batch_bodies == []


def test_set_metadata_rejects_bad_visibility(backend):
    with pytest.raises(ValueError, match="visibility"):
        sheets.set_metadata("ss-1", "k", visibility="PUBLIC")
    assert backend.batch_bodies == []


def test_set_metadata_unknown_sheet(backend):
    with pytest.raises(sheets.SheetNotFoundError):
        sheets.set_metadata("ss-1", "k", sheet="Nope")
    assert backend.batch_bodies == []


def test_range_quotes_titles_with_apostrophes(backend):
    _add_tab(backend, "Bob's Log")
    result = sheets.set_metadata("ss-1", "k", sheet="Bob's Log", row=2)
    assert result["range"] == "'Bob''s Log'!2:2"


def test_find_by_key_and_value(backend):
    _add_tab(backend, "Inventory")
    _add_tab(backend, "Orders")
    sheets.set_metadata("ss-1", "role", "inventory", sheet="Inventory")
    sheets.set_metadata("ss-1", "role", "orders", sheet="Orders")

    result = sheets.find_by_metadata("ss-1", key="role", value="inventory")

    assert backend.search_bodies[-1] == {"dataFilters": [
        {"developerMetadataLookup": {
            "metadataKey": "role", "metadataValue": "inventory"}}]}
    assert len(result["matches"]) == 1
    m = result["matches"][0]
    assert (m["key"], m["value"], m["sheet_title"], m["location_type"]) == \
        ("role", "inventory", "Inventory", "SHEET")


def test_find_by_key_only_returns_all(backend):
    _add_tab(backend, "Inventory")
    _add_tab(backend, "Orders")
    sheets.set_metadata("ss-1", "role", "inventory", sheet="Inventory")
    sheets.set_metadata("ss-1", "role", "orders", sheet="Orders")
    result = sheets.find_by_metadata("ss-1", key="role")
    assert backend.search_bodies[-1]["dataFilters"][0][
        "developerMetadataLookup"] == {"metadataKey": "role"}
    assert {m["sheet_title"] for m in result["matches"]} == \
        {"Inventory", "Orders"}


def test_find_by_value_only(backend):
    sheets.set_metadata("ss-1", "role", "x")
    sheets.find_by_metadata("ss-1", value="x")
    assert backend.search_bodies[-1]["dataFilters"][0][
        "developerMetadataLookup"] == {"metadataValue": "x"}


def test_find_no_matches_skips_inventory_read(backend):
    calls_before = backend.get_calls
    result = sheets.find_by_metadata("ss-1", key="missing")
    assert result == {"matches": []}
    assert backend.get_calls == calls_before


def test_find_requires_key_or_value(backend):
    with pytest.raises(ValueError):
        sheets.find_by_metadata("ss-1")
    assert backend.search_bodies == []


def test_tag_survives_tab_rename(backend):
    """The motivating case: lookup by role still works after a rename."""
    tab = _add_tab(backend, "Inventory")
    sheets.set_metadata("ss-1", "role", "inventory", sheet="Inventory")
    sheets.batch_update("ss-1", [{"updateSheetProperties": {
        "properties": {"sheetId": tab["sheet_id"], "title": "Stock"},
        "fields": "title"}}])
    # The fake doesn't model updateSheetProperties; apply the rename.
    for s in backend.sheets:
        if s["sheetId"] == tab["sheet_id"]:
            s["title"] = "Stock"

    m = sheets.find_by_metadata("ss-1", key="role", value="inventory")
    assert m["matches"][0]["sheet_title"] == "Stock"
    assert m["matches"][0]["range"] == "'Stock'"


def test_row_tag_follows_row_after_insert_and_delete(backend):
    sheets.set_metadata("ss-1", "row-key", "abc", row=5)
    sheets.insert_rows("ss-1", start_row=2, count=2)
    assert sheets.find_by_metadata("ss-1", key="row-key")[
        "matches"][0]["row"] == 7
    sheets.delete_rows("ss-1", start_row=1, count=3)
    m = sheets.find_by_metadata("ss-1", key="row-key")["matches"][0]
    assert (m["row"], m["range"]) == (4, "'Sheet1'!4:4")


# ---------------------------------------------------------------------------
# MCP tool wrappers
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_mcp_batch_update_passthrough(backend):
    result = await sheets_tools.sheets_batch_update(
        "ss-1", [{"addSheet": {"properties": {"title": "A"}}}])
    assert result["replies"][0]["addSheet"]["properties"]["title"] == "A"


@pytest.mark.asyncio
async def test_mcp_batch_update_destructive_returns_error(backend):
    result = await sheets_tools.sheets_batch_update(
        "ss-1", [{"deleteSheet": {"sheetId": 0}}])
    assert "error" in result
    assert "allow_destructive" in result["error"]
    assert len(backend.sheets) == 1


@pytest.mark.asyncio
async def test_mcp_batch_update_destructive_allowed(backend):
    tab = _add_tab(backend, "Gone")
    result = await sheets_tools.sheets_batch_update(
        "ss-1", [{"deleteSheet": {"sheetId": tab["sheet_id"]}}],
        allow_destructive=True)
    assert "error" not in result
    assert [s["title"] for s in backend.sheets] == ["Sheet1"]


@pytest.mark.asyncio
async def test_mcp_batch_update_api_400_returns_error(backend):
    result = await sheets_tools.sheets_batch_update(
        "ss-1", [{"addSheet": {"properties": {"title": "Sheet1"}}}])
    assert "error" in result


@pytest.mark.asyncio
async def test_mcp_permission_error_envelope(backend):
    backend.fail_status = 403
    result = await sheets_tools.sheets_add_tab("ss-1", "X")
    assert result["error"] == "The caller does not have permission."
    assert "hint" in result


@pytest.mark.asyncio
async def test_mcp_add_tab(backend):
    result = await sheets_tools.sheets_add_tab(
        "ss-1", "Log", index=0, row_count=10, column_count=4)
    assert result["title"] == "Log"
    assert (result["row_count"], result["column_count"]) == (10, 4)


@pytest.mark.asyncio
async def test_mcp_insert_and_delete_rows(backend):
    ins = await sheets_tools.sheets_insert_rows("ss-1", 3, count=2)
    assert (ins["start_row"], ins["end_row"]) == (3, 4)
    dele = await sheets_tools.sheets_delete_rows("ss-1", 3, count=2)
    assert (dele["start_row"], dele["end_row"]) == (3, 4)
    assert backend.sheets[0]["gridProperties"]["rowCount"] == 1000


@pytest.mark.asyncio
async def test_mcp_row_validation_error(backend):
    result = await sheets_tools.sheets_delete_rows("ss-1", 0)
    assert "error" in result


@pytest.mark.asyncio
async def test_mcp_unknown_sheet_error(backend):
    result = await sheets_tools.sheets_insert_rows("ss-1", 2, sheet="Nope")
    assert "Nope" in result["error"]


@pytest.mark.asyncio
async def test_mcp_set_and_find_metadata(backend):
    await sheets_tools.sheets_add_tab("ss-1", "Inventory")
    created = await sheets_tools.sheets_set_metadata(
        "ss-1", "role", "inventory", sheet="Inventory")
    assert created["visibility"] == "DOCUMENT"
    found = await sheets_tools.sheets_find_by_metadata(
        "ss-1", key="role", value="inventory")
    assert found["matches"][0]["metadata_id"] == created["metadata_id"]
    assert found["matches"][0]["sheet_title"] == "Inventory"


@pytest.mark.asyncio
async def test_mcp_find_without_filters_errors(backend):
    result = await sheets_tools.sheets_find_by_metadata("ss-1")
    assert "error" in result


def test_new_tools_are_discoverable_async_functions():
    import inspect
    for name in ("sheets_batch_update", "sheets_add_tab",
                 "sheets_insert_rows", "sheets_delete_rows",
                 "sheets_set_metadata", "sheets_find_by_metadata"):
        fn = getattr(sheets_tools, name)
        assert inspect.iscoroutinefunction(fn), name
        assert fn.__doc__ and "Args:" in fn.__doc__, name


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _cli(*args):
    return CliRunner().invoke(sheets_cli, list(args))


def test_cli_batch_update(backend):
    r = _cli("batch-update", "ss-1", "-r",
             json.dumps([{"addSheet": {"properties": {"title": "Z"}}}]))
    assert r.exit_code == 0, r.output
    assert json.loads(r.output)["replies"][0]["addSheet"][
        "properties"]["title"] == "Z"


def test_cli_batch_update_destructive_blocked_then_allowed(backend):
    tab = _add_tab(backend, "Gone")
    reqs = json.dumps([{"deleteSheet": {"sheetId": tab["sheet_id"]}}])
    r = _cli("batch-update", "ss-1", "-r", reqs)
    assert r.exit_code != 0
    assert "allow_destructive" in r.output
    assert len(backend.sheets) == 2

    r = _cli("batch-update", "ss-1", "-r", reqs, "--allow-destructive")
    assert r.exit_code == 0, r.output
    assert len(backend.sheets) == 1


@pytest.mark.parametrize("payload", ["not json", '{"a": 1}', "[]"])
def test_cli_batch_update_bad_json(backend, payload):
    r = _cli("batch-update", "ss-1", "-r", payload)
    assert r.exit_code != 0
    assert backend.batch_bodies == []


def test_cli_add_tab(backend):
    r = _cli("add-tab", "ss-1", "Log", "--index", "0", "--rows", "20")
    assert r.exit_code == 0, r.output
    out = json.loads(r.output)
    assert (out["title"], out["index"], out["row_count"]) == ("Log", 0, 20)


def test_cli_insert_and_delete_rows(backend):
    _add_tab(backend, "Log")
    r = _cli("insert-rows", "ss-1", "4", "-c", "2", "--sheet", "Log")
    assert r.exit_code == 0, r.output
    assert "rows 4-5" in r.output
    r = _cli("delete-rows", "ss-1", "4", "--count", "2", "--sheet", "Log")
    assert r.exit_code == 0, r.output
    assert "Deleted 2 row(s): rows 4-5" in r.output


def test_cli_row_errors_are_clean(backend):
    r = _cli("delete-rows", "ss-1", "0")
    assert r.exit_code != 0 and "start_row" in r.output
    r = _cli("insert-rows", "ss-1", "2", "--sheet", "Nope")
    assert r.exit_code != 0 and "Nope" in r.output


def test_cli_set_and_find_metadata(backend):
    _add_tab(backend, "Inventory")
    r = _cli("set-metadata", "ss-1", "role", "inventory", "--sheet", "Inventory")
    assert r.exit_code == 0, r.output
    assert json.loads(r.output)["location_type"] == "SHEET"

    r = _cli("set-metadata", "ss-1", "col", "--column", "B")
    assert r.exit_code == 0, r.output
    assert json.loads(r.output)["range"] == "'Sheet1'!B:B"

    r = _cli("find-metadata", "ss-1", "--key", "role", "--value", "inventory")
    assert r.exit_code == 0, r.output
    assert json.loads(r.output)["matches"][0]["sheet_title"] == "Inventory"


def test_cli_metadata_errors(backend):
    r = _cli("set-metadata", "ss-1", "k", "--row", "1", "--column", "A")
    assert r.exit_code != 0 and "row or column" in r.output
    r = _cli("set-metadata", "ss-1", "k", "--visibility", "PUBLIC")
    assert r.exit_code != 0
    r = _cli("find-metadata", "ss-1")
    assert r.exit_code != 0 and "key or value" in r.output


def test_cli_existing_commands_still_registered():
    """Regression: the new commands don't displace existing ones."""
    for cmd in ("list", "create", "info", "read", "tail", "update-cell",
                "append", "batch-update", "add-tab", "insert-rows",
                "delete-rows", "set-metadata", "find-metadata"):
        assert cmd in sheets_cli.commands, cmd
