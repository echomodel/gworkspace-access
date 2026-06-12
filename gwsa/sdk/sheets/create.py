"""Google Sheets creation operations."""

from typing import Optional

from .service import get_sheets_service
from ..drive.service import get_drive_service


def create_spreadsheet(
    title: str,
    folder_id: Optional[str] = None,
    sheet_title: Optional[str] = None,
    account: Optional[str] = None,
) -> dict:
    """
    Create a new Google Sheets spreadsheet.

    Args:
        title: The title for the new spreadsheet
        folder_id: Optional Drive folder ID to create the spreadsheet in
            (default: My Drive root)
        sheet_title: Optional title for the first sheet (tab). Defaults
            to the API default ("Sheet1").
        account: Optional account selector — name or email. Omit to use
            the user's default account.

    Returns:
        Dict with spreadsheet info:
            - id: Spreadsheet ID
            - title: Spreadsheet title
            - url: URL to open the spreadsheet
            - sheets: List of sheet (tab) titles
    """
    sheets_service = get_sheets_service(account=account)

    body: dict = {"properties": {"title": title}}
    if sheet_title:
        body["sheets"] = [{"properties": {"title": sheet_title}}]

    spreadsheet = sheets_service.spreadsheets().create(
        body=body,
        fields="spreadsheetId,properties/title,sheets/properties/title",
    ).execute()
    spreadsheet_id = spreadsheet.get("spreadsheetId")

    # Move to folder if specified
    if folder_id:
        drive_service = get_drive_service(account=account)
        # Get current parents, then move to new folder
        file = drive_service.files().get(
            fileId=spreadsheet_id,
            fields="parents",
            supportsAllDrives=True,
        ).execute()
        previous_parents = ",".join(file.get("parents", []))
        drive_service.files().update(
            fileId=spreadsheet_id,
            addParents=folder_id,
            removeParents=previous_parents,
            supportsAllDrives=True,
            fields="id, parents",
        ).execute()

    return {
        "id": spreadsheet_id,
        "title": spreadsheet.get("properties", {}).get("title", title),
        "url": f"https://docs.google.com/spreadsheets/d/{spreadsheet_id}/edit",
        "sheets": [
            s.get("properties", {}).get("title")
            for s in spreadsheet.get("sheets", [])
        ],
    }
