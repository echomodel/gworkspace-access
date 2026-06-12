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
