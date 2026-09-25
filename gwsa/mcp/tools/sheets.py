"""Google Sheets MCP tools.

Plain async functions delegating to ``gwsa.sdk.sheets``.

Every tool accepts an optional ``account`` parameter: pass either
the account ``name`` (e.g. ``"work"``) or its Google ``email`` (e.g.
``"alice@example.com"``) to operate as a specific account on the
current user's profile. Omit to use the user's ``default_account``
(or the sole account if only one is configured). Use the
``list_google_accounts`` tool to discover available account names
and emails.
"""

from __future__ import annotations

import logging
from typing import Any, Optional

from googleapiclient.errors import HttpError

from gwsa.sdk import sheets

logger = logging.getLogger(__name__)


def _permission_envelope(e: HttpError) -> dict[str, Any]:
    return {
        "error": "The caller does not have permission.",
        "details": str(e),
        "hint": (
            "The chosen gwsa account may not have access to this "
            "spreadsheet. Try a different account via the 'account' "
            "parameter (see 'list_google_accounts'), or re-acquire "
            "the token if it has expired."
        ),
    }


async def sheets_list(
    max_results: int = 25,
    query: Optional[str] = None,
    account: Optional[str] = None,
) -> dict[str, Any]:
    """List Google Sheets spreadsheets the chosen account can access.

    Args:
        max_results: Maximum number of spreadsheets to return (default 25).
        query: Optional search query to filter spreadsheets by title or
            content.
        account: Optional account selector (name or email). Omit to
            use the user's default account.

    Returns:
        Dict with a list of spreadsheets (id, title, url, timestamps).
    """
    try:
        return sheets.list_spreadsheets(
            max_results=max_results, query=query, account=account
        )
    except Exception as e:
        logger.error(f"Error listing spreadsheets: {e}")
        return {"error": str(e)}


async def sheets_create(
    title: str,
    folder_id: Optional[str] = None,
    sheet_title: Optional[str] = None,
    account: Optional[str] = None,
) -> dict[str, Any]:
    """Create a new Google Sheets spreadsheet.

    Args:
        title: Title for the new spreadsheet (the Drive file name).
        folder_id: Optional Drive folder ID to create the spreadsheet
            in (defaults to My Drive root). Use ``drive_find_folder``
            to resolve a folder path to its ID.
        sheet_title: Optional title for the first sheet (tab).
        account: Optional account selector (name or email). Omit to
            create in the user's default account.

    Returns:
        Dict with spreadsheet ``id``, ``title``, ``url``, and
        ``sheets`` (tab titles).
    """
    try:
        return sheets.create_spreadsheet(
            title=title,
            folder_id=folder_id,
            sheet_title=sheet_title,
            account=account,
        )
    except Exception as e:
        logger.error(f"Error creating spreadsheet: {e}")
        return {"error": str(e)}


async def sheets_get_metadata(
    spreadsheet_id: str,
    account: Optional[str] = None,
) -> dict[str, Any]:
    """Get spreadsheet metadata — title, URL, and sheet (tab) inventory.

    Args:
        spreadsheet_id: Spreadsheet ID.
        account: Optional account selector (name or email). Omit to
            use the user's default account.

    Returns:
        Dict with ``id``, ``title``, ``url``, and ``sheets`` — one
        entry per tab with ``sheet_id``, ``title``, ``row_count``,
        and ``column_count``.
    """
    try:
        return sheets.get_spreadsheet(spreadsheet_id, account=account)
    except HttpError as e:
        if e.resp.status == 403:
            logger.error(f"Permission error reading spreadsheet: {e}")
            return _permission_envelope(e)
        raise
    except Exception as e:
        logger.error(f"Error reading spreadsheet metadata: {e}")
        return {"error": str(e)}


async def sheets_read(
    spreadsheet_id: str,
    range_name: str,
    value_render_option: str = "FORMATTED_VALUE",
    account: Optional[str] = None,
) -> dict[str, Any]:
    """Read cell values from a spreadsheet range.

    Args:
        spreadsheet_id: Spreadsheet ID.
        range_name: A1-notation range, e.g. "Sheet1!A1:D10" or "A:D".
            A bare sheet (tab) name reads that whole tab.
        value_render_option: "FORMATTED_VALUE" (default),
            "UNFORMATTED_VALUE", or "FORMULA".
        account: Optional account selector (name or email). Omit to
            use the user's default account.

    Returns:
        Dict with ``range`` (as read) and ``values`` — a list of rows,
        each a list of cell values. Empty when the range has no data.
    """
    try:
        return sheets.read_values(
            spreadsheet_id,
            range_name,
            value_render_option=value_render_option,
            account=account,
        )
    except HttpError as e:
        if e.resp.status == 403:
            logger.error(f"Permission error reading sheet values: {e}")
            return _permission_envelope(e)
        raise
    except Exception as e:
        logger.error(f"Error reading sheet values: {e}")
        return {"error": str(e)}


async def sheets_read_tail(
    spreadsheet_id: str,
    n: int = 10,
    sheet: Optional[str] = None,
    before_row: Optional[int] = None,
    anchor_column: str = "A",
    has_header: bool = True,
    include_header: bool = True,
    value_render_option: str = "FORMATTED_VALUE",
    account: Optional[str] = None,
) -> dict[str, Any]:
    """Read the last N data rows of a sheet, or page backwards through
    older rows, without loading the whole sheet.

    Efficient for append-style logs: the first call probes the anchor
    column to find the data extent, then reads exactly the trailing
    rows. Cursor pages (``before_row`` set) are a single bounded read.

    Cursor pagination (newest → oldest): call without ``before_row``
    for the newest page; while ``has_more`` is true, call again with
    ``before_row`` set to the previous response's ``start_row`` (and
    ``include_header`` false). N counts rows (entries), not calendar
    days. Rows come back in sheet order; entirely empty rows are
    ``[]`` — skip them.

    Returned row numbers also let a caller update a specific recent
    row afterwards via ``sheets_update`` (e.g. range "Log!A{row}:L{row}").

    Args:
        spreadsheet_id: Spreadsheet ID.
        n: Number of data rows to return (default 10).
        sheet: Optional sheet (tab) title. Defaults to the first tab.
        before_row: Cursor — return the N rows immediately above this
            1-based row number (exclusive). Pass the previous page's
            ``start_row``. Omit for the newest page.
        anchor_column: Column whose filled extent defines the last
            data row (default "A"). Must be filled on every data row.
        has_header: Whether row 1 is a header row (default True);
            keeps pagination from paging into the header.
        include_header: Also return the header row (default True).
            Pass False on cursor pages to skip the redundant fetch.
        value_render_option: "FORMATTED_VALUE" (default),
            "UNFORMATTED_VALUE", or "FORMULA".
        account: Optional account selector (name or email). Omit to
            use the user's default account.

    Returns:
        Dict with ``header``, ``values`` (up to N data rows),
        ``start_row`` / ``end_row`` (1-based row numbers of the
        returned slice; ``start_row`` is the next-page cursor), and
        ``has_more`` (older rows exist above ``start_row``).
    """
    try:
        return sheets.read_tail(
            spreadsheet_id,
            n=n,
            sheet=sheet,
            before_row=before_row,
            anchor_column=anchor_column,
            has_header=has_header,
            include_header=include_header,
            value_render_option=value_render_option,
            account=account,
        )
    except HttpError as e:
        if e.resp.status == 403:
            logger.error(f"Permission error reading sheet tail: {e}")
            return _permission_envelope(e)
        raise
    except Exception as e:
        logger.error(f"Error reading sheet tail: {e}")
        return {"error": str(e)}


async def sheets_update(
    spreadsheet_id: str,
    range_name: str,
    values: list,
    value_input_option: str = "USER_ENTERED",
    account: Optional[str] = None,
) -> dict[str, Any]:
    """Overwrite cell values in a spreadsheet range.

    Args:
        spreadsheet_id: Spreadsheet ID.
        range_name: A1-notation range to write, e.g. "Sheet1!A2:D2".
        values: List of rows, each a list of cell values. A single
            cell is ``[["value"]]``.
        value_input_option: "USER_ENTERED" (default — values parsed
            as if typed in the UI: dates, times, numbers, formulas)
            or "RAW" (stored verbatim as strings).
        account: Optional account selector (name or email). Omit to
            use the user's default account.

    Returns:
        Dict with ``updated_range``, ``updated_rows``,
        ``updated_columns``, and ``updated_cells``.
    """
    try:
        return sheets.update_values(
            spreadsheet_id,
            range_name,
            values,
            value_input_option=value_input_option,
            account=account,
        )
    except HttpError as e:
        if e.resp.status == 403:
            logger.error(f"Permission error updating sheet values: {e}")
            return _permission_envelope(e)
        raise
    except Exception as e:
        logger.error(f"Error updating sheet values: {e}")
        return {"error": str(e)}


async def sheets_append(
    spreadsheet_id: str,
    values: list,
    range_name: str = "A1",
    value_input_option: str = "USER_ENTERED",
    account: Optional[str] = None,
) -> dict[str, Any]:
    """Append rows after the last row of data in a sheet.

    The Sheets API locates the table containing ``range_name`` and
    appends after its last data row — pass a tab-qualified anchor
    (e.g. "Log!A1") to target a specific tab.

    Args:
        spreadsheet_id: Spreadsheet ID.
        values: List of rows to append, each a list of cell values.
            A single row is ``[["2026-06-12", "07:15", 5]]``.
        range_name: A1-notation anchor locating the table to append
            to (default "A1" — the first tab's data table).
        value_input_option: "USER_ENTERED" (default) or "RAW" — see
            ``sheets_update``.
        account: Optional account selector (name or email). Omit to
            use the user's default account.

    Returns:
        Dict with ``updated_range`` (where the rows landed),
        ``updated_rows``, and ``updated_cells``.
    """
    try:
        return sheets.append_rows(
            spreadsheet_id,
            values,
            range_name=range_name,
            value_input_option=value_input_option,
            account=account,
        )
    except HttpError as e:
        if e.resp.status == 403:
            logger.error(f"Permission error appending sheet rows: {e}")
            return _permission_envelope(e)
        raise
    except Exception as e:
        logger.error(f"Error appending sheet rows: {e}")
        return {"error": str(e)}


def _structure_error(action: str, e: Exception) -> dict[str, Any]:
    """Shared error handling for the structural (batchUpdate-backed) tools."""
    if isinstance(e, HttpError) and e.resp.status == 403:
        logger.error(f"Permission error {action}: {e}")
        return _permission_envelope(e)
    logger.error(f"Error {action}: {e}")
    return {"error": str(e)}


async def sheets_batch_update(
    spreadsheet_id: str,
    requests: list,
    allow_destructive: bool = False,
    include_spreadsheet_in_response: bool = False,
    account: Optional[str] = None,
) -> dict[str, Any]:
    """Apply a raw Sheets API ``spreadsheets.batchUpdate`` — the full
    structural-editing primitive.

    Use this for anything the other sheets tools don't cover: rename,
    reorder, hide, or delete tabs; insert/delete/move rows or columns;
    formatting (``repeatCell``, ``updateBorders``); freezing header
    rows; data validation; protected ranges; developer metadata. For
    cell *values*, use ``sheets_update`` / ``sheets_append`` instead.

    The batch is **atomic**: if any request is invalid, none are
    applied. Requests run in order, and later requests see the effects
    of earlier ones.

    Destructive gate: a batch containing ``deleteSheet`` is rejected
    unless ``allow_destructive`` is true.

    Tabs are addressed by numeric ``sheetId`` (not title) inside
    requests — get it from ``sheets_get_metadata``. Row/column
    ``startIndex``/``endIndex`` are **0-based, end-exclusive** (row 5 in
    the UI is ``startIndex: 4, endIndex: 5``).

    Common requests::

        {"addSheet": {"properties": {"title": "Archive"}}}
        {"updateSheetProperties": {"properties": {"sheetId": 123,
            "title": "New name"}, "fields": "title"}}
        {"updateSheetProperties": {"properties": {"sheetId": 0,
            "gridProperties": {"frozenRowCount": 1}},
            "fields": "gridProperties.frozenRowCount"}}
        {"deleteDimension": {"range": {"sheetId": 0,
            "dimension": "ROWS", "startIndex": 4, "endIndex": 5}}}
        {"repeatCell": {"range": {"sheetId": 0, "startRowIndex": 0,
            "endRowIndex": 1}, "cell": {"userEnteredFormat":
            {"textFormat": {"bold": true}}},
            "fields": "userEnteredFormat.textFormat.bold"}}
        {"deleteSheet": {"sheetId": 123}}   # needs allow_destructive

    Args:
        spreadsheet_id: Spreadsheet ID.
        requests: List of Sheets API request objects, applied in order.
        allow_destructive: Must be true to apply a batch containing
            ``deleteSheet``.
        include_spreadsheet_in_response: Also return the updated
            spreadsheet resource as ``updatedSpreadsheet``.
        account: Optional account selector (name or email). Omit to
            use the user's default account.

    Returns:
        The raw API response: ``spreadsheetId``, ``replies`` (one entry
        per request, in order — e.g. ``addSheet.properties.sheetId`` for
        a new tab; ``{}`` for requests with no reply), and
        ``updatedSpreadsheet`` when requested. On failure, ``error``.
    """
    try:
        return sheets.batch_update(
            spreadsheet_id,
            requests,
            allow_destructive=allow_destructive,
            include_spreadsheet_in_response=include_spreadsheet_in_response,
            account=account,
        )
    except Exception as e:
        return _structure_error("applying sheets batchUpdate", e)


async def sheets_add_tab(
    spreadsheet_id: str,
    title: str,
    index: Optional[int] = None,
    row_count: Optional[int] = None,
    column_count: Optional[int] = None,
    account: Optional[str] = None,
) -> dict[str, Any]:
    """Add a sheet (tab) to an existing spreadsheet.

    Args:
        spreadsheet_id: Spreadsheet ID.
        title: Title of the new tab (must be unique in the spreadsheet).
        index: Optional 0-based position among the tabs (default: last).
        row_count: Optional initial row count (API default 1000).
        column_count: Optional initial column count (API default 26).
        account: Optional account selector (name or email). Omit to
            use the user's default account.

    Returns:
        Dict with the new tab's ``sheet_id``, ``title``, ``index``,
        ``row_count``, and ``column_count``.
    """
    try:
        return sheets.add_tab(
            spreadsheet_id,
            title,
            index=index,
            row_count=row_count,
            column_count=column_count,
            account=account,
        )
    except Exception as e:
        return _structure_error("adding sheet tab", e)


async def sheets_insert_rows(
    spreadsheet_id: str,
    start_row: int,
    count: int = 1,
    sheet: Optional[str] = None,
    inherit_from_before: bool = False,
    account: Optional[str] = None,
) -> dict[str, Any]:
    """Insert empty rows into a tab, shifting existing rows down.

    Row numbers are 1-based, as shown in the Sheets UI and returned by
    ``sheets_read_tail``. Fill the new rows afterwards with
    ``sheets_update``.

    Args:
        spreadsheet_id: Spreadsheet ID.
        start_row: Row number the first new row will occupy; the row
            currently there (and everything below) moves down.
        count: Number of rows to insert (default 1).
        sheet: Optional tab title. Defaults to the first tab.
        inherit_from_before: Copy formatting from the row above instead
            of the row below (default false). Not allowed at row 1.
        account: Optional account selector (name or email). Omit to
            use the user's default account.

    Returns:
        Dict with ``sheet_id``, ``start_row`` / ``end_row`` (the new
        empty rows, inclusive), and ``count``.
    """
    try:
        return sheets.insert_rows(
            spreadsheet_id,
            start_row,
            count=count,
            sheet=sheet,
            inherit_from_before=inherit_from_before,
            account=account,
        )
    except Exception as e:
        return _structure_error("inserting sheet rows", e)


async def sheets_delete_rows(
    spreadsheet_id: str,
    start_row: int,
    count: int = 1,
    sheet: Optional[str] = None,
    account: Optional[str] = None,
) -> dict[str, Any]:
    """Delete rows from a tab, shifting the rows below up.

    One call regardless of sheet size — no need to rewrite the rows
    below. Row numbers are 1-based, as shown in the Sheets UI and
    returned by ``sheets_read_tail``. Row numbers below the deleted
    range shift up by ``count`` afterwards.

    Args:
        spreadsheet_id: Spreadsheet ID.
        start_row: Number of the first row to delete.
        count: Number of rows to delete (default 1) — rows
            ``start_row`` through ``start_row + count - 1``.
        sheet: Optional tab title. Defaults to the first tab.
        account: Optional account selector (name or email). Omit to
            use the user's default account.

    Returns:
        Dict with ``sheet_id``, ``start_row`` / ``end_row`` (the rows
        removed, inclusive), and ``count``.
    """
    try:
        return sheets.delete_rows(
            spreadsheet_id,
            start_row,
            count=count,
            sheet=sheet,
            account=account,
        )
    except Exception as e:
        return _structure_error("deleting sheet rows", e)


async def sheets_set_metadata(
    spreadsheet_id: str,
    key: str,
    value: Optional[str] = None,
    sheet: Optional[str] = None,
    row: Optional[int] = None,
    column: Optional[str] = None,
    visibility: str = "DOCUMENT",
    account: Optional[str] = None,
) -> dict[str, Any]:
    """Tag a spreadsheet, tab, row, or column with developer metadata
    (a key/value pair) so it can be found later with
    ``sheets_find_by_metadata`` instead of by title or position.

    A tab tagged e.g. ``role=inventory`` stays discoverable even if the
    user renames it; row/column tags move with their row/column as rows
    are inserted or deleted around them. Tags are invisible in the
    Sheets UI.

    Location (pick by which arguments you pass):
        - none of ``sheet``/``row``/``column`` → the whole spreadsheet
        - ``sheet`` only → that tab
        - ``row`` → that row (of ``sheet``, default first tab)
        - ``column`` → that column (of ``sheet``, default first tab)

    Args:
        spreadsheet_id: Spreadsheet ID.
        key: Metadata key, e.g. ``"role"``.
        value: Optional metadata value, e.g. ``"inventory"``.
        sheet: Optional tab title.
        row: Optional 1-based row number.
        column: Optional column letter, e.g. ``"C"``.
        visibility: ``"DOCUMENT"`` (default — discoverable by any client
            with access to the file) or ``"PROJECT"`` (only the Cloud
            project that created it can see it).
        account: Optional account selector (name or email). Omit to
            use the user's default account.

    Returns:
        The created tag: ``metadata_id``, ``key``, ``value``,
        ``visibility``, ``location_type``, ``sheet_id``,
        ``sheet_title``, ``row``, ``end_row``, ``column``, ``range``.
    """
    try:
        return sheets.set_metadata(
            spreadsheet_id,
            key,
            value=value,
            sheet=sheet,
            row=row,
            column=column,
            visibility=visibility,
            account=account,
        )
    except Exception as e:
        return _structure_error("setting sheet metadata", e)


async def sheets_find_by_metadata(
    spreadsheet_id: str,
    key: Optional[str] = None,
    value: Optional[str] = None,
    account: Optional[str] = None,
) -> dict[str, Any]:
    """Find tabs, rows, or columns tagged with developer metadata
    (see ``sheets_set_metadata``).

    Typical use: locate a data-store tab by role rather than by title —
    ``key="role", value="inventory"`` → the match's ``sheet_title`` is
    the tab's current name, usable in ``sheets_read`` / ``sheets_append``
    ranges.

    Args:
        spreadsheet_id: Spreadsheet ID.
        key: Metadata key to match.
        value: Metadata value to match. At least one of ``key`` or
            ``value`` is required.
        account: Optional account selector (name or email). Omit to
            use the user's default account.

    Returns:
        Dict with ``matches`` — each with ``metadata_id``, ``key``,
        ``value``, ``visibility``, ``location_type`` (SPREADSHEET,
        SHEET, ROW, or COLUMN), ``sheet_id``, ``sheet_title``, ``row`` /
        ``end_row`` (1-based, ROW tags), ``column`` (letter, COLUMN
        tags), and ``range`` (A1 notation, e.g. ``'Log'!5:5``). Empty
        list when nothing matches.
    """
    try:
        return sheets.find_by_metadata(
            spreadsheet_id, key=key, value=value, account=account
        )
    except Exception as e:
        return _structure_error("finding sheet metadata", e)
