"""Google Drive search operations."""

from typing import Optional

from .service import get_drive_service


def search_drive(
    query: str,
    max_results: int = 25,
    account: Optional[str] = None,
):
    """Searches Google Drive for files matching a query.

    Args:
        query: The query string to use for the search.
               Supports operators like 'name contains', 'fullText contains', 'mimeType=', etc.
        max_results: The maximum number of results to return.
        account: Optional account selector — name or email. Omit to use
            the user's default account.

    Returns:
        A list of file objects matching the search query.
    """
    drive_service = get_drive_service(account=account)
    result = drive_service.files().list(
        q=query,
        pageSize=max_results,
        fields="files(id, name, mimeType, modifiedTime, webViewLink)",
    ).execute()
    return result.get('files', [])
