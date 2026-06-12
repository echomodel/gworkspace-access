"""Google Sheets read operations."""

from typing import Optional

from .service import get_sheets_service


def read_values(
    spreadsheet_id: str,
    range_name: str,
    value_render_option: str = "FORMATTED_VALUE",
    account: Optional[str] = None,
) -> dict:
    """
    Read cell values from a spreadsheet range.

    Args:
        spreadsheet_id: Spreadsheet ID
        range_name: A1-notation range, e.g. "Sheet1!A1:D10" or "A:D".
            A bare sheet name reads the whole sheet.
        value_render_option: How values are rendered — "FORMATTED_VALUE"
            (default), "UNFORMATTED_VALUE", or "FORMULA".
        account: Optional account selector — name or email. Omit to use
            the user's default account.

    Returns:
        Dict with:
            - range: The range actually read (A1 notation)
            - values: List of rows, each a list of cell values.
              Empty list when the range has no data.
    """
    service = get_sheets_service(account=account)

    result = service.spreadsheets().values().get(
        spreadsheetId=spreadsheet_id,
        range=range_name,
        valueRenderOption=value_render_option,
    ).execute()

    return {
        "range": result.get("range", range_name),
        "values": result.get("values", []),
    }


def read_tail(
    spreadsheet_id: str,
    n: int = 10,
    sheet: Optional[str] = None,
    before_row: Optional[int] = None,
    anchor_column: str = "A",
    has_header: bool = True,
    include_header: bool = True,
    value_render_option: str = "FORMATTED_VALUE",
    account: Optional[str] = None,
) -> dict:
    """
    Read the last ``n`` data rows of a sheet — or, with ``before_row``,
    page backwards through older rows — without loading the whole
    sheet.

    The Sheets API has no "last N rows" primitive, so the first call
    probes the ``anchor_column`` (cheap — one column of values) to
    find the data extent, then range-reads exactly the last ``n``
    rows. Cursor calls (``before_row`` set) skip the probe entirely —
    the bounds are already known — and cost a single bounded read.
    Payload stays small no matter how large the log grows.

    Cursor pagination (newest → oldest)::

        page = read_tail(ss_id, n=30)                 # newest n rows
        while page["has_more"]:
            page = read_tail(ss_id, n=30,
                             before_row=page["start_row"],
                             include_header=False)

    Rows are returned in sheet order. For append-style logs that is
    insertion order (oldest first within each page). Rows that are
    entirely empty come back as ``[]`` — callers skip them.

    Assumes the anchor column is filled on every data row (true for
    append-style logs where the first column is a date/key).

    Args:
        spreadsheet_id: Spreadsheet ID
        n: Number of trailing data rows to return (default 10)
        sheet: Optional sheet (tab) title. Defaults to the first tab.
        before_row: Cursor — return the ``n`` rows immediately above
            this 1-based row number (exclusive). Pass the previous
            response's ``start_row`` to fetch the next-older page.
            Omit for the newest page.
        anchor_column: Column whose filled extent defines the last data
            row (default "A"). Only consulted when ``before_row`` is
            omitted.
        has_header: Whether row 1 is a header row (default True).
            Determines where data rows start, so pagination never
            pages into the header.
        include_header: Also return the header row as ``header``
            (default True). Pass False on cursor pages to skip the
            redundant fetch. Ignored when ``has_header`` is False.
        value_render_option: How values are rendered — see
            :func:`read_values`.
        account: Optional account selector — name or email. Omit to use
            the user's default account.

    Returns:
        Dict with:
            - header: Header row values (when fetched), else None
            - values: Up to ``n`` data rows, each a list of cell values
            - start_row: 1-based row number of the first returned row
              (the cursor for the next-older page), or None if empty
            - end_row: 1-based row number of the last returned row,
              or None if empty
            - has_more: True when older data rows exist above
              ``start_row``
    """
    service = get_sheets_service(account=account)
    prefix = f"'{sheet}'!" if sheet else ""
    first_data_row = 2 if has_header else 1

    if before_row is not None:
        end_row = before_row - 1
    else:
        probe = service.spreadsheets().values().get(
            spreadsheetId=spreadsheet_id,
            range=f"{prefix}{anchor_column}:{anchor_column}",
            majorDimension="COLUMNS",
        ).execute()
        columns = probe.get("values", [])
        end_row = len(columns[0]) if columns else 0

    header = None
    if has_header and include_header:
        header_result = service.spreadsheets().values().get(
            spreadsheetId=spreadsheet_id,
            range=f"{prefix}1:1",
            valueRenderOption=value_render_option,
        ).execute()
        header_values = header_result.get("values", [])
        header = header_values[0] if header_values else []

    start_row = max(first_data_row, end_row - n + 1)
    values: list = []
    if end_row >= first_data_row:
        result = service.spreadsheets().values().get(
            spreadsheetId=spreadsheet_id,
            range=f"{prefix}{start_row}:{end_row}",
            valueRenderOption=value_render_option,
        ).execute()
        values = result.get("values", [])

    return {
        "header": header,
        "values": values,
        "start_row": start_row if values else None,
        "end_row": end_row if values else None,
        "has_more": bool(values) and start_row > first_data_row,
    }


def get_spreadsheet(
    spreadsheet_id: str,
    account: Optional[str] = None,
) -> dict:
    """
    Get spreadsheet metadata — title, URL, and sheet (tab) inventory.

    Args:
        spreadsheet_id: Spreadsheet ID
        account: Optional account selector — name or email. Omit to use
            the user's default account.

    Returns:
        Dict with:
            - id: Spreadsheet ID
            - title: Spreadsheet title
            - url: URL to open the spreadsheet
            - sheets: List of dicts per sheet (tab):
                - sheet_id: Numeric sheet ID
                - title: Sheet title
                - row_count / column_count: Grid size
    """
    service = get_sheets_service(account=account)

    spreadsheet = service.spreadsheets().get(
        spreadsheetId=spreadsheet_id,
        fields=(
            "spreadsheetId,properties/title,"
            "sheets(properties(sheetId,title,gridProperties))"
        ),
    ).execute()

    sheets = []
    for sheet in spreadsheet.get("sheets", []):
        props = sheet.get("properties", {})
        grid = props.get("gridProperties", {})
        sheets.append({
            "sheet_id": props.get("sheetId"),
            "title": props.get("title"),
            "row_count": grid.get("rowCount"),
            "column_count": grid.get("columnCount"),
        })

    return {
        "id": spreadsheet.get("spreadsheetId"),
        "title": spreadsheet.get("properties", {}).get("title"),
        "url": (
            f"https://docs.google.com/spreadsheets/d/"
            f"{spreadsheet.get('spreadsheetId')}/edit"
        ),
        "sheets": sheets,
    }
