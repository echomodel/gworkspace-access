"""Google Sheets write operations — update and append."""

from typing import Optional

from .service import get_sheets_service


def update_values(
    spreadsheet_id: str,
    range_name: str,
    values: list,
    value_input_option: str = "USER_ENTERED",
    account: Optional[str] = None,
) -> dict:
    """
    Overwrite cell values in a spreadsheet range.

    Args:
        spreadsheet_id: Spreadsheet ID
        range_name: A1-notation range to write, e.g. "Sheet1!A2:D2"
        values: List of rows, each a list of cell values. A single
            cell is ``[["value"]]``.
        value_input_option: "USER_ENTERED" (default — values parsed as
            if typed in the UI: dates, times, numbers, formulas) or
            "RAW" (stored verbatim as strings).
        account: Optional account selector — name or email. Omit to use
            the user's default account.

    Returns:
        Dict with:
            - updated_range: The range actually written (A1 notation)
            - updated_rows / updated_columns / updated_cells: Counts
    """
    service = get_sheets_service(account=account)

    result = service.spreadsheets().values().update(
        spreadsheetId=spreadsheet_id,
        range=range_name,
        valueInputOption=value_input_option,
        body={"values": values},
    ).execute()

    return {
        "updated_range": result.get("updatedRange"),
        "updated_rows": result.get("updatedRows", 0),
        "updated_columns": result.get("updatedColumns", 0),
        "updated_cells": result.get("updatedCells", 0),
    }


def append_rows(
    spreadsheet_id: str,
    values: list,
    range_name: str = "A1",
    value_input_option: str = "USER_ENTERED",
    account: Optional[str] = None,
) -> dict:
    """
    Append rows after the last row of data in a sheet.

    The Sheets API locates the table containing ``range_name`` and
    appends after its last data row — pass a sheet-qualified anchor
    (e.g. "Log!A1") to target a specific tab.

    Args:
        spreadsheet_id: Spreadsheet ID
        values: List of rows to append, each a list of cell values.
        range_name: A1-notation anchor locating the table to append to
            (default "A1" — the first sheet's data table).
        value_input_option: "USER_ENTERED" (default) or "RAW" — see
            :func:`update_values`.
        account: Optional account selector — name or email. Omit to use
            the user's default account.

    Returns:
        Dict with:
            - updated_range: The range the rows landed in (A1 notation)
            - updated_rows / updated_cells: Counts
    """
    service = get_sheets_service(account=account)

    result = service.spreadsheets().values().append(
        spreadsheetId=spreadsheet_id,
        range=range_name,
        valueInputOption=value_input_option,
        insertDataOption="INSERT_ROWS",
        body={"values": values},
    ).execute()

    updates = result.get("updates", {})
    return {
        "updated_range": updates.get("updatedRange"),
        "updated_rows": updates.get("updatedRows", 0),
        "updated_cells": updates.get("updatedCells", 0),
    }
