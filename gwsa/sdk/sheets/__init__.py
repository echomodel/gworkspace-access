"""Google Sheets SDK module.

Provides functions for creating, reading, writing, and listing
Google Sheets spreadsheets, and for structural changes (tabs, rows,
developer metadata) via batchUpdate.
"""

from .service import get_sheets_service
from .create import create_spreadsheet
from .read import read_values, read_tail, get_spreadsheet
from .update import update_values, append_rows
from .list import list_spreadsheets
from .structure import (
    DESTRUCTIVE_REQUESTS,
    DestructiveRequestError,
    SheetNotFoundError,
    batch_update,
    add_tab,
    insert_rows,
    delete_rows,
    set_metadata,
    find_by_metadata,
)

__all__ = [
    "get_sheets_service",
    "create_spreadsheet",
    "read_values",
    "read_tail",
    "get_spreadsheet",
    "update_values",
    "append_rows",
    "list_spreadsheets",
    "DESTRUCTIVE_REQUESTS",
    "DestructiveRequestError",
    "SheetNotFoundError",
    "batch_update",
    "add_tab",
    "insert_rows",
    "delete_rows",
    "set_metadata",
    "find_by_metadata",
]
