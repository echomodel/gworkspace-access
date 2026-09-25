"""Google Sheets structural operations — batchUpdate, tabs, rows, metadata.

``batch_update`` is a faithful pass-through to ``spreadsheets.batchUpdate``
(the primitive behind every structural change: tabs, rows/columns,
formatting, developer metadata). The remaining functions are thin
convenience wrappers that build the common requests for callers.

Row numbers are **1-based** throughout, matching A1 notation and the row
numbers returned by :func:`gwsa.sdk.sheets.read_tail`. The API's 0-based,
end-exclusive ``dimensionRange`` indices are an internal detail.
"""

from __future__ import annotations

from typing import Optional, Union

from .service import get_sheets_service

#: batchUpdate request types rejected unless ``allow_destructive=True``.
DESTRUCTIVE_REQUESTS = frozenset({"deleteSheet"})

#: Valid developer-metadata visibilities.
METADATA_VISIBILITIES = ("DOCUMENT", "PROJECT")


class DestructiveRequestError(ValueError):
    """A batch contains a destructive request and was not explicitly allowed."""


class SheetNotFoundError(ValueError):
    """No sheet (tab) with the given title exists in the spreadsheet."""


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def column_to_index(column: Union[str, int]) -> int:
    """Convert a column letter ("A", "AB") or 1-based number to a 0-based index."""
    if isinstance(column, int):
        if column < 1:
            raise ValueError(f"Column number must be >= 1, got {column}")
        return column - 1
    letters = column.strip().upper()
    if not letters or not letters.isalpha():
        raise ValueError(f"Invalid column: {column!r}")
    index = 0
    for ch in letters:
        index = index * 26 + (ord(ch) - ord("A") + 1)
    return index - 1


def index_to_column(index: int) -> str:
    """Convert a 0-based column index to its letter ("A", "AB")."""
    n = index + 1
    letters = ""
    while n:
        n, rem = divmod(n - 1, 26)
        letters = chr(ord("A") + rem) + letters
    return letters


def _quote_title(title: str) -> str:
    return "'" + title.replace("'", "''") + "'"


def _sheet_inventory(service, spreadsheet_id: str) -> list[dict]:
    spreadsheet = service.spreadsheets().get(
        spreadsheetId=spreadsheet_id,
        fields="sheets(properties(sheetId,title,index))",
    ).execute()
    return [s.get("properties", {}) for s in spreadsheet.get("sheets", [])]


def _resolve_sheet_id(service, spreadsheet_id: str, sheet: Optional[str]) -> int:
    """Map a tab title to its numeric sheetId (first tab when ``sheet`` is None)."""
    props = _sheet_inventory(service, spreadsheet_id)
    if not props:
        raise SheetNotFoundError("Spreadsheet has no sheets.")
    if sheet is None:
        first = min(props, key=lambda p: p.get("index", 0))
        return first.get("sheetId", 0)
    for p in props:
        if p.get("title") == sheet:
            return p.get("sheetId", 0)
    titles = ", ".join(repr(p.get("title")) for p in props)
    raise SheetNotFoundError(f"No sheet titled {sheet!r}. Available: {titles}")


def _row_range(sheet_id: int, start_row: int, count: int) -> dict:
    if start_row < 1:
        raise ValueError(f"start_row must be >= 1 (1-based), got {start_row}")
    if count < 1:
        raise ValueError(f"count must be >= 1, got {count}")
    return {
        "sheetId": sheet_id,
        "dimension": "ROWS",
        "startIndex": start_row - 1,
        "endIndex": start_row - 1 + count,
    }


def _execute_batch(service, spreadsheet_id: str, requests: list) -> dict:
    return service.spreadsheets().batchUpdate(
        spreadsheetId=spreadsheet_id,
        body={"requests": requests},
    ).execute()


# ---------------------------------------------------------------------------
# batchUpdate pass-through
# ---------------------------------------------------------------------------


def batch_update(
    spreadsheet_id: str,
    requests: list,
    allow_destructive: bool = False,
    include_spreadsheet_in_response: bool = False,
    account: Optional[str] = None,
) -> dict:
    """Apply a raw ``spreadsheets.batchUpdate`` to a spreadsheet.

    Faithful pass-through: the requests are sent as-is and the raw API
    response is returned. The batch is atomic — if any request is invalid,
    none are applied.

    Args:
        spreadsheet_id: Spreadsheet ID.
        requests: List of Sheets API request objects (``addSheet``,
            ``updateSheetProperties``, ``insertDimension``,
            ``deleteDimension``, ``repeatCell``,
            ``createDeveloperMetadata``, etc.).
        allow_destructive: Must be True for a batch containing a request
            type in :data:`DESTRUCTIVE_REQUESTS` (``deleteSheet``).
            Otherwise the batch is rejected before any API call.
        include_spreadsheet_in_response: Ask the API to return the
            updated spreadsheet resource (``updatedSpreadsheet``).
        account: Optional account selector — name or email. Omit to use
            the user's default account.

    Returns:
        The batchUpdate response (``spreadsheetId``, ``replies`` — one per
        request, in order — and ``updatedSpreadsheet`` when requested).

    Raises:
        ValueError: ``requests`` is not a non-empty list of objects.
        DestructiveRequestError: a destructive request was not allowed.
    """
    if not isinstance(requests, list) or not requests:
        raise ValueError("requests must be a non-empty list of request objects.")
    if not all(isinstance(r, dict) for r in requests):
        raise ValueError("Each request must be an object (dict).")

    if not allow_destructive:
        blocked = sorted({
            kind for r in requests for kind in r if kind in DESTRUCTIVE_REQUESTS
        })
        if blocked:
            raise DestructiveRequestError(
                f"Batch contains destructive request(s): {', '.join(blocked)}. "
                "Pass allow_destructive=True to apply it."
            )

    service = get_sheets_service(account=account)
    body: dict = {"requests": requests}
    if include_spreadsheet_in_response:
        body["includeSpreadsheetInResponse"] = True
    return service.spreadsheets().batchUpdate(
        spreadsheetId=spreadsheet_id, body=body
    ).execute()


# ---------------------------------------------------------------------------
# tabs
# ---------------------------------------------------------------------------


def add_tab(
    spreadsheet_id: str,
    title: str,
    index: Optional[int] = None,
    row_count: Optional[int] = None,
    column_count: Optional[int] = None,
    account: Optional[str] = None,
) -> dict:
    """Add a sheet (tab) to an existing spreadsheet.

    Args:
        spreadsheet_id: Spreadsheet ID.
        title: Title of the new tab. Must be unique in the spreadsheet.
        index: Optional 0-based position among the tabs (default: last).
        row_count / column_count: Optional initial grid size (API default
            1000 x 26).
        account: Optional account selector — name or email.

    Returns:
        Dict with ``sheet_id``, ``title``, ``index``, ``row_count``, and
        ``column_count`` of the new tab.
    """
    properties: dict = {"title": title}
    if index is not None:
        properties["index"] = index
    grid: dict = {}
    if row_count is not None:
        grid["rowCount"] = row_count
    if column_count is not None:
        grid["columnCount"] = column_count
    if grid:
        properties["gridProperties"] = grid

    service = get_sheets_service(account=account)
    result = _execute_batch(
        service, spreadsheet_id, [{"addSheet": {"properties": properties}}]
    )
    props = (
        result.get("replies", [{}])[0].get("addSheet", {}).get("properties", {})
    )
    grid_out = props.get("gridProperties", {})
    return {
        "sheet_id": props.get("sheetId"),
        "title": props.get("title", title),
        "index": props.get("index"),
        "row_count": grid_out.get("rowCount"),
        "column_count": grid_out.get("columnCount"),
    }


# ---------------------------------------------------------------------------
# rows
# ---------------------------------------------------------------------------


def insert_rows(
    spreadsheet_id: str,
    start_row: int,
    count: int = 1,
    sheet: Optional[str] = None,
    inherit_from_before: bool = False,
    account: Optional[str] = None,
) -> dict:
    """Insert empty rows, shifting existing rows down.

    Args:
        spreadsheet_id: Spreadsheet ID.
        start_row: 1-based row number the first new row will occupy. The
            row currently at ``start_row`` (and everything below) moves
            down by ``count``.
        count: Number of rows to insert (default 1).
        sheet: Optional tab title. Defaults to the first tab.
        inherit_from_before: Copy formatting from the row above instead of
            the row below (default False). Cannot be True when
            ``start_row`` is 1.
        account: Optional account selector — name or email.

    Returns:
        Dict with ``sheet_id``, ``start_row``, ``end_row`` (1-based,
        inclusive — the new empty rows), and ``count``.
    """
    if inherit_from_before and start_row == 1:
        raise ValueError("inherit_from_before cannot be True when start_row is 1.")
    service = get_sheets_service(account=account)
    sheet_id = _resolve_sheet_id(service, spreadsheet_id, sheet)
    _execute_batch(service, spreadsheet_id, [{
        "insertDimension": {
            "range": _row_range(sheet_id, start_row, count),
            "inheritFromBefore": inherit_from_before,
        }
    }])
    return {
        "sheet_id": sheet_id,
        "start_row": start_row,
        "end_row": start_row + count - 1,
        "count": count,
    }


def delete_rows(
    spreadsheet_id: str,
    start_row: int,
    count: int = 1,
    sheet: Optional[str] = None,
    account: Optional[str] = None,
) -> dict:
    """Delete rows, shifting the rows below up.

    Args:
        spreadsheet_id: Spreadsheet ID.
        start_row: 1-based number of the first row to delete.
        count: Number of rows to delete (default 1) — rows
            ``start_row`` .. ``start_row + count - 1``.
        sheet: Optional tab title. Defaults to the first tab.
        account: Optional account selector — name or email.

    Returns:
        Dict with ``sheet_id``, ``start_row``, ``end_row`` (1-based,
        inclusive — the rows removed), and ``count``.
    """
    service = get_sheets_service(account=account)
    sheet_id = _resolve_sheet_id(service, spreadsheet_id, sheet)
    _execute_batch(service, spreadsheet_id, [{
        "deleteDimension": {"range": _row_range(sheet_id, start_row, count)}
    }])
    return {
        "sheet_id": sheet_id,
        "start_row": start_row,
        "end_row": start_row + count - 1,
        "count": count,
    }


# ---------------------------------------------------------------------------
# developer metadata
# ---------------------------------------------------------------------------


def _normalize_metadata(md: dict, titles: dict[int, str]) -> dict:
    """Flatten a DeveloperMetadata resource into a caller-friendly dict."""
    location = md.get("location", {})
    location_type = location.get("locationType")
    dim = location.get("dimensionRange")
    sheet_id = dim.get("sheetId") if dim else location.get("sheetId")
    sheet_title = titles.get(sheet_id) if sheet_id is not None else None

    a1 = None
    row = end_row = column = None
    if sheet_title is not None:
        prefix = _quote_title(sheet_title)
        if dim and dim.get("dimension") == "ROWS":
            row = dim.get("startIndex", 0) + 1
            end_row = dim.get("endIndex", row)
            a1 = f"{prefix}!{row}:{end_row}"
        elif dim and dim.get("dimension") == "COLUMNS":
            start = index_to_column(dim.get("startIndex", 0))
            end = index_to_column(dim.get("endIndex", 1) - 1)
            column = start
            a1 = f"{prefix}!{start}:{end}"
        else:
            a1 = prefix

    return {
        "metadata_id": md.get("metadataId"),
        "key": md.get("metadataKey"),
        "value": md.get("metadataValue"),
        "visibility": md.get("visibility"),
        "location_type": location_type,
        "sheet_id": sheet_id,
        "sheet_title": sheet_title,
        "row": row,
        "end_row": end_row,
        "column": column,
        "range": a1,
    }


def set_metadata(
    spreadsheet_id: str,
    key: str,
    value: Optional[str] = None,
    sheet: Optional[str] = None,
    row: Optional[int] = None,
    column: Optional[Union[str, int]] = None,
    visibility: str = "DOCUMENT",
    account: Optional[str] = None,
) -> dict:
    """Attach developer metadata (a key/value tag) to a spreadsheet location.

    The tag makes a location discoverable by key/value via
    :func:`find_by_metadata` instead of by title or position. Row and
    column tags move with their row/column when rows or columns are
    inserted or deleted around them.

    Location:
        - no ``sheet``, ``row``, or ``column`` → the whole spreadsheet
        - ``sheet`` only → that tab
        - ``row`` → that row of ``sheet`` (default: first tab)
        - ``column`` → that column of ``sheet`` (default: first tab)

    Args:
        spreadsheet_id: Spreadsheet ID.
        key: Metadata key (e.g. ``"role"``).
        value: Optional metadata value (e.g. ``"inventory"``).
        sheet: Optional tab title.
        row: Optional 1-based row number.
        column: Optional column letter (``"C"``) or 1-based number.
        visibility: ``"DOCUMENT"`` (default — visible to any client with
            access to the file) or ``"PROJECT"`` (visible only to the
            Cloud project that created it).
        account: Optional account selector — name or email.

    Returns:
        The created metadata, normalized — see :func:`find_by_metadata`.
    """
    if row is not None and column is not None:
        raise ValueError("Pass at most one of row or column.")
    if visibility not in METADATA_VISIBILITIES:
        raise ValueError(
            f"visibility must be one of {METADATA_VISIBILITIES}, got {visibility!r}"
        )

    service = get_sheets_service(account=account)
    inventory = _sheet_inventory(service, spreadsheet_id)
    titles = {p.get("sheetId"): p.get("title") for p in inventory}

    if sheet is None and row is None and column is None:
        location: dict = {"spreadsheet": True}
    else:
        sheet_id = _resolve_sheet_id(service, spreadsheet_id, sheet)
        if row is not None:
            location = {"dimensionRange": _row_range(sheet_id, row, 1)}
        elif column is not None:
            idx = column_to_index(column)
            location = {"dimensionRange": {
                "sheetId": sheet_id,
                "dimension": "COLUMNS",
                "startIndex": idx,
                "endIndex": idx + 1,
            }}
        else:
            location = {"sheetId": sheet_id}

    metadata: dict = {
        "metadataKey": key,
        "location": location,
        "visibility": visibility,
    }
    if value is not None:
        metadata["metadataValue"] = value

    result = _execute_batch(service, spreadsheet_id, [
        {"createDeveloperMetadata": {"developerMetadata": metadata}}
    ])
    created = (
        result.get("replies", [{}])[0]
        .get("createDeveloperMetadata", {})
        .get("developerMetadata", metadata)
    )
    return _normalize_metadata(created, titles)


def find_by_metadata(
    spreadsheet_id: str,
    key: Optional[str] = None,
    value: Optional[str] = None,
    account: Optional[str] = None,
) -> dict:
    """Find developer metadata in a spreadsheet by key and/or value.

    Args:
        spreadsheet_id: Spreadsheet ID.
        key: Optional metadata key to match.
        value: Optional metadata value to match. At least one of ``key``
            or ``value`` is required.
        account: Optional account selector — name or email.

    Returns:
        Dict with ``matches`` — a list of dicts, each with:
            - metadata_id, key, value, visibility
            - location_type: SPREADSHEET, SHEET, ROW, or COLUMN
            - sheet_id / sheet_title: the tab (None for spreadsheet-level)
            - row / end_row: 1-based rows for ROW locations, else None
            - column: column letter for COLUMN locations, else None
            - range: A1 notation of the location (e.g. ``'Log'!5:5``),
              or None for spreadsheet-level metadata
    """
    if key is None and value is None:
        raise ValueError("Pass at least one of key or value.")
    lookup: dict = {}
    if key is not None:
        lookup["metadataKey"] = key
    if value is not None:
        lookup["metadataValue"] = value

    service = get_sheets_service(account=account)
    result = service.spreadsheets().developerMetadata().search(
        spreadsheetId=spreadsheet_id,
        body={"dataFilters": [{"developerMetadataLookup": lookup}]},
    ).execute()
    matched = result.get("matchedDeveloperMetadata", [])
    if not matched:
        return {"matches": []}

    titles = {
        p.get("sheetId"): p.get("title")
        for p in _sheet_inventory(service, spreadsheet_id)
    }
    return {
        "matches": [
            _normalize_metadata(m.get("developerMetadata", {}), titles)
            for m in matched
        ]
    }
