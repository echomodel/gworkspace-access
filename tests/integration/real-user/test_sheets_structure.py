"""Integration tests for Sheets structural operations against the live API.

Self-contained: each test creates its own scratch spreadsheet, exercises
tabs / rows / developer metadata / the batchUpdate gate, and trashes it
afterwards. No reliance on pre-existing test data.

Covers the SDK functions ``sheets.add_tab``, ``insert_rows``,
``delete_rows``, ``set_metadata``, ``find_by_metadata``, and
``batch_update`` (including the destructive gate), plus the MCP
wrappers end-to-end.
"""

from __future__ import annotations

import asyncio
import time

import pytest

from gwsa.mcp.tools.sheets import (
    sheets_add_tab,
    sheets_batch_update,
    sheets_delete_rows,
    sheets_find_by_metadata,
    sheets_insert_rows,
    sheets_set_metadata,
)
from gwsa.sdk import drive, sheets


def _unique_name(prefix: str) -> str:
    return f"{prefix}-{int(time.time() * 1000)}"


def _safe_trash(file_id: str) -> None:
    if not file_id:
        return
    try:
        drive.delete_file(file_id=file_id)
    except Exception:
        pass


def _col_a(ss_id: str, tab: str) -> list:
    values = sheets.read_values(ss_id, f"'{tab}'!A:A")["values"]
    return [r[0] if r else "" for r in values]


@pytest.mark.integration
def test_tabs_rows_and_metadata_sdk():
    created = sheets.create_spreadsheet(
        title=_unique_name("gwsa-it-structure"), sheet_title="Main"
    )
    ss_id = created["id"]
    try:
        # --- add_tab -------------------------------------------------------
        tab = sheets.add_tab(ss_id, "Inventory", row_count=50, column_count=5)
        assert tab["title"] == "Inventory"
        assert isinstance(tab["sheet_id"], int)
        assert (tab["row_count"], tab["column_count"]) == (50, 5)
        titles = [s["title"] for s in sheets.get_spreadsheet(ss_id)["sheets"]]
        assert titles == ["Main", "Inventory"]

        # --- insert_rows / delete_rows shift real data ---------------------
        sheets.append_rows(
            ss_id, [["h"], ["r2"], ["r3"], ["r4"], ["r5"]],
            range_name="'Inventory'!A1",
        )
        ins = sheets.insert_rows(ss_id, start_row=3, count=2, sheet="Inventory")
        assert (ins["start_row"], ins["end_row"]) == (3, 4)
        assert _col_a(ss_id, "Inventory") == ["h", "r2", "", "", "r3", "r4", "r5"]

        dele = sheets.delete_rows(ss_id, start_row=3, count=3, sheet="Inventory")
        assert (dele["start_row"], dele["end_row"]) == (3, 5)
        assert _col_a(ss_id, "Inventory") == ["h", "r2", "r4", "r5"]

        # Default sheet is the first tab: Main is untouched by a delete
        # aimed at Inventory, and a default-target insert grows Main.
        before = {s["title"]: s["row_count"]
                  for s in sheets.get_spreadsheet(ss_id)["sheets"]}
        sheets.insert_rows(ss_id, start_row=1)
        after = {s["title"]: s["row_count"]
                 for s in sheets.get_spreadsheet(ss_id)["sheets"]}
        assert after["Main"] == before["Main"] + 1
        assert after["Inventory"] == before["Inventory"]

        # --- developer metadata: tab tag survives a rename -----------------
        tag = sheets.set_metadata(ss_id, "role", "inventory", sheet="Inventory")
        assert tag["location_type"] == "SHEET"
        assert tag["sheet_id"] == tab["sheet_id"]
        assert tag["visibility"] == "DOCUMENT"

        sheets.batch_update(ss_id, [{"updateSheetProperties": {
            "properties": {"sheetId": tab["sheet_id"], "title": "Stock"},
            "fields": "title",
        }}])
        found = sheets.find_by_metadata(ss_id, key="role", value="inventory")
        assert len(found["matches"]) == 1
        assert found["matches"][0]["sheet_title"] == "Stock"
        assert found["matches"][0]["metadata_id"] == tag["metadata_id"]

        # --- row tag follows its row; column tag reports its letter --------
        row_tag = sheets.set_metadata(ss_id, "entry", "r5", sheet="Stock", row=4)
        assert row_tag["range"] == "'Stock'!4:4"
        sheets.insert_rows(ss_id, start_row=2, sheet="Stock")
        moved = sheets.find_by_metadata(ss_id, key="entry")["matches"][0]
        assert moved["row"] == 5
        assert sheets.read_values(ss_id, "'Stock'!A5")["values"] == [["r5"]]

        col_tag = sheets.set_metadata(ss_id, "field", "sku", sheet="Stock",
                                      column="C")
        assert (col_tag["location_type"], col_tag["column"]) == ("COLUMN", "C")

        whole = sheets.set_metadata(ss_id, "app", "gwsa-it")
        assert whole["location_type"] == "SPREADSHEET"
        assert sheets.find_by_metadata(ss_id, value="gwsa-it")["matches"][0][
            "location_type"] == "SPREADSHEET"

        assert sheets.find_by_metadata(ss_id, key="no-such-key") == {"matches": []}

        # --- destructive gate ----------------------------------------------
        with pytest.raises(sheets.DestructiveRequestError):
            sheets.batch_update(
                ss_id, [{"deleteSheet": {"sheetId": tab["sheet_id"]}}])
        assert len(sheets.get_spreadsheet(ss_id)["sheets"]) == 2

        sheets.batch_update(
            ss_id, [{"deleteSheet": {"sheetId": tab["sheet_id"]}}],
            allow_destructive=True,
        )
        assert [s["title"] for s in sheets.get_spreadsheet(ss_id)["sheets"]] \
            == ["Main"]
    finally:
        _safe_trash(ss_id)


@pytest.mark.integration
def test_batch_update_is_atomic_live():
    """A bad request in a batch leaves the earlier requests unapplied."""
    ss_id = sheets.create_spreadsheet(
        title=_unique_name("gwsa-it-atomic"), sheet_title="Main")["id"]
    try:
        with pytest.raises(Exception):
            sheets.batch_update(ss_id, [
                {"addSheet": {"properties": {"title": "New"}}},
                {"addSheet": {"properties": {"title": "Main"}}},  # duplicate
            ])
        titles = [s["title"] for s in sheets.get_spreadsheet(ss_id)["sheets"]]
        assert titles == ["Main"]
    finally:
        _safe_trash(ss_id)


@pytest.mark.integration
def test_structure_mcp_roundtrip():
    ss_id = sheets.create_spreadsheet(
        title=_unique_name("gwsa-it-structure-mcp"), sheet_title="Main")["id"]
    try:
        tab = asyncio.run(sheets_add_tab(ss_id, "Log"))
        assert "error" not in tab, tab

        tag = asyncio.run(sheets_set_metadata(ss_id, "role", "log", sheet="Log"))
        assert "error" not in tag, tag
        found = asyncio.run(sheets_find_by_metadata(ss_id, key="role", value="log"))
        assert found["matches"][0]["sheet_title"] == "Log"

        ins = asyncio.run(sheets_insert_rows(ss_id, 2, count=3, sheet="Log"))
        assert "error" not in ins, ins
        dele = asyncio.run(sheets_delete_rows(ss_id, 2, count=3, sheet="Log"))
        assert "error" not in dele, dele

        blocked = asyncio.run(sheets_batch_update(
            ss_id, [{"deleteSheet": {"sheetId": tab["sheet_id"]}}]))
        assert "allow_destructive" in blocked.get("error", ""), blocked

        bad = asyncio.run(sheets_batch_update(
            ss_id, [{"addSheet": {"properties": {"title": "Main"}}}]))
        assert "error" in bad

        ok = asyncio.run(sheets_batch_update(
            ss_id, [{"deleteSheet": {"sheetId": tab["sheet_id"]}}],
            allow_destructive=True))
        assert "error" not in ok, ok
        assert ok["spreadsheetId"] == ss_id
    finally:
        _safe_trash(ss_id)
