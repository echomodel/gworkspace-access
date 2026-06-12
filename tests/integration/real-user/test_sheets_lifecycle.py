"""Integration tests for the Sheets SDK + MCP tools.

Self-contained: each test creates its own scratch spreadsheet,
exercises the lifecycle, and trashes it afterwards. No reliance on
pre-existing test data.

Covers the SDK functions:
- ``sheets.create_spreadsheet`` (including create-into-folder)
- ``sheets.append_rows`` / ``sheets.update_values``
- ``sheets.read_values`` / ``sheets.read_tail``
- ``sheets.get_spreadsheet``

And the MCP wrappers ``sheets_create`` / ``sheets_append`` /
``sheets_read_tail`` end-to-end.
"""

from __future__ import annotations

import asyncio
import time

import pytest

from gwsa.mcp.tools.sheets import (
    sheets_append,
    sheets_create,
    sheets_read_tail,
)
from gwsa.sdk import drive, sheets


def _unique_name(prefix: str) -> str:
    return f"{prefix}-{int(time.time() * 1000)}"


def _safe_trash(file_id: str) -> None:
    """Best-effort cleanup. Never raises — used in finally blocks."""
    if not file_id:
        return
    try:
        drive.delete_file(file_id=file_id)
    except Exception:
        pass


HEADER = ["Date", "Energy", "Notes"]
ROWS = [
    ["2026-06-01", 3, "first"],
    ["2026-06-02", 4, "second"],
    ["2026-06-03", 2, "third"],
    ["2026-06-04", 5, "fourth"],
]


@pytest.mark.integration
def test_spreadsheet_lifecycle_sdk():
    """Create → append → update → read → tail → metadata, via the SDK."""
    title = _unique_name("gwsa-it-sheets")
    created = sheets.create_spreadsheet(title=title, sheet_title="Log")
    ss_id = created.get("id")
    assert ss_id, f"create_spreadsheet returned no id: {created}"
    try:
        assert created["sheets"] == ["Log"]

        # Header + data rows via append.
        sheets.append_rows(ss_id, [HEADER], range_name="Log!A1")
        result = sheets.append_rows(ss_id, ROWS, range_name="Log!A1")
        assert result["updated_rows"] == len(ROWS)

        # Tail: last 2 rows, with correct row numbers.
        tail = sheets.read_tail(ss_id, n=2, sheet="Log")
        assert tail["header"] == HEADER
        assert len(tail["values"]) == 2
        assert tail["values"][-1][0] == "2026-06-04"
        assert tail["end_row"] == 1 + len(ROWS)
        assert tail["start_row"] == tail["end_row"] - 1
        assert tail["has_more"] is True

        # Cursor pagination: page the remaining older rows.
        page2 = sheets.read_tail(
            ss_id, n=2, sheet="Log",
            before_row=tail["start_row"], include_header=False,
        )
        assert page2["header"] is None
        assert [r[0] for r in page2["values"]] == [
            "2026-06-01", "2026-06-02",
        ]
        assert page2["has_more"] is False

        # Targeted update of the last row using the tail row number.
        row = tail["end_row"]
        sheets.update_values(
            ss_id, f"Log!C{row}", [["updated"]],
        )
        read_back = sheets.read_values(ss_id, f"Log!A{row}:C{row}")
        assert read_back["values"][0][2] == "updated"

        # Metadata reports the tab.
        meta = sheets.get_spreadsheet(ss_id)
        assert meta["title"] == title
        assert any(s["title"] == "Log" for s in meta["sheets"])
    finally:
        _safe_trash(ss_id)


@pytest.mark.integration
def test_create_into_folder_and_mcp_roundtrip():
    """MCP wrappers: create into a folder, append, tail-read."""
    folder_name = _unique_name("gwsa-it-sheets-folder")
    folder = drive.create_folder(name=folder_name)
    folder_id = folder.get("id")
    assert folder_id, f"create_folder returned no id: {folder}"
    ss_id = None
    try:
        created = asyncio.run(sheets_create(
            title=_unique_name("gwsa-it-energy"),
            folder_id=folder_id,
            sheet_title="Log",
        ))
        assert "error" not in created, created
        ss_id = created["id"]

        # Verify it actually landed in the folder.
        meta = drive.get_metadata(file_id=ss_id)
        assert folder_id in meta.get("parents", []), meta

        appended = asyncio.run(sheets_append(
            ss_id, [HEADER] + ROWS, range_name="Log!A1",
        ))
        assert "error" not in appended, appended

        tail = asyncio.run(sheets_read_tail(ss_id, n=3, sheet="Log"))
        assert "error" not in tail, tail
        assert len(tail["values"]) == 3
        assert tail["values"][-1][0] == "2026-06-04"
    finally:
        _safe_trash(ss_id)
        _safe_trash(folder_id)
