"""Google Docs listing operations."""

from typing import Optional, List, Dict, Any

from googleapiclient.discovery import build

from ..auth import get_credentials


def get_drive_service():
    """Build and return a Google Drive API service object."""
    creds, _ = get_credentials()
    return build("drive", "v3", credentials=creds)


def list_documents(
    max_results: int = 25,
    query: Optional[str] = None,
    page_token: Optional[str] = None
) -> dict:
    """
    List Google Docs accessible to the current user.

    Args:
        max_results: Maximum number of documents to return (default 25)
        query: Optional search query to filter documents
        page_token: Token for pagination

    Returns:
        Dict with:
            - documents: List of document info dicts
            - next_page_token: Token for next page (if more results)
    """
    service = get_drive_service()

    # Build the query - always filter for Google Docs
    q = "mimeType='application/vnd.google-apps.document'"
    if query:
        q += f" and (name contains '{query}' or fullText contains '{query}')"

    results = service.files().list(
        q=q,
        pageSize=max_results,
        pageToken=page_token,
        fields="nextPageToken, files(id, name, modifiedTime, createdTime, owners)",
        orderBy="modifiedTime desc"
    ).execute()

    documents = []
    for file in results.get("files", []):
        owners = file.get("owners", [])
        owner_email = owners[0].get("emailAddress") if owners else None

        documents.append({
            "id": file.get("id"),
            "title": file.get("name"),
            "url": f"https://docs.google.com/document/d/{file.get('id')}/edit",
            "modified_time": file.get("modifiedTime"),
            "created_time": file.get("createdTime"),
            "owner": owner_email
        })

    return {
        "documents": documents,
        "next_page_token": results.get("nextPageToken")
    }
