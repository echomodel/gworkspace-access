"""Google Sheets listing operations."""

from typing import Optional

from ..drive.service import get_drive_service


def list_spreadsheets(
    max_results: int = 25,
    query: Optional[str] = None,
    page_token: Optional[str] = None,
    account: Optional[str] = None,
) -> dict:
    """
    List Google Sheets spreadsheets accessible to the current user.

    Args:
        max_results: Maximum number of spreadsheets to return (default 25)
        query: Optional search query to filter spreadsheets
        page_token: Token for pagination
        account: Optional account selector — name or email. Omit to use
            the user's default account.

    Returns:
        Dict with:
            - spreadsheets: List of spreadsheet info dicts
            - next_page_token: Token for next page (if more results)
    """
    service = get_drive_service(account=account)

    q = "mimeType='application/vnd.google-apps.spreadsheet'"
    if query:
        q += f" and (name contains '{query}' or fullText contains '{query}')"

    results = service.files().list(
        q=q,
        pageSize=max_results,
        pageToken=page_token,
        fields="nextPageToken, files(id, name, modifiedTime, createdTime, owners)",
        orderBy="modifiedTime desc"
    ).execute()

    spreadsheets = []
    for file in results.get("files", []):
        owners = file.get("owners", [])
        owner_email = owners[0].get("emailAddress") if owners else None

        spreadsheets.append({
            "id": file.get("id"),
            "title": file.get("name"),
            "url": f"https://docs.google.com/spreadsheets/d/{file.get('id')}/edit",
            "modified_time": file.get("modifiedTime"),
            "created_time": file.get("createdTime"),
            "owner": owner_email,
        })

    return {
        "spreadsheets": spreadsheets,
        "next_page_token": results.get("nextPageToken"),
    }
