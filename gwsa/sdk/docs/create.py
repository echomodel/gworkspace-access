"""Google Docs creation operations."""

from typing import Optional

from .service import get_docs_service
from ..drive.service import get_drive_service


def create_document(
    title: str,
    body_text: Optional[str] = None,
    folder_id: Optional[str] = None,
) -> dict:
    """
    Create a new Google Doc.

    Args:
        title: The title for the new document
        body_text: Optional initial body text to insert
        folder_id: Optional folder ID to create the doc in (default: My Drive root)

    Returns:
        Dict with document info:
            - id: Document ID
            - title: Document title
            - url: URL to open the document
    """
    docs_service = get_docs_service()

    # Create the document
    doc = docs_service.documents().create(body={"title": title}).execute()
    doc_id = doc.get("documentId")

    # Move to folder if specified
    if folder_id:
        drive_service = get_drive_service()
        # Get current parents, then move to new folder
        file = drive_service.files().get(
            fileId=doc_id,
            fields="parents",
            supportsAllDrives=True,
        ).execute()
        previous_parents = ",".join(file.get("parents", []))
        drive_service.files().update(
            fileId=doc_id,
            addParents=folder_id,
            removeParents=previous_parents,
            supportsAllDrives=True,
            fields="id, parents",
        ).execute()

    # Insert initial body text if provided
    if body_text:
        requests = [
            {
                "insertText": {
                    "location": {"index": 1},
                    "text": body_text
                }
            }
        ]
        docs_service.documents().batchUpdate(
            documentId=doc_id,
            body={"requests": requests}
        ).execute()

    return {
        "id": doc_id,
        "title": title,
        "url": f"https://docs.google.com/document/d/{doc_id}/edit"
    }
