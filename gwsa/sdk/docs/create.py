"""Google Docs creation operations."""

from typing import Optional

from .service import get_docs_service


def create_document(title: str, body_text: Optional[str] = None) -> dict:
    """
    Create a new Google Doc.

    Args:
        title: The title for the new document
        body_text: Optional initial body text to insert

    Returns:
        Dict with document info:
            - id: Document ID
            - title: Document title
            - url: URL to open the document
    """
    service = get_docs_service()

    # Create the document
    doc = service.documents().create(body={"title": title}).execute()
    doc_id = doc.get("documentId")

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
        service.documents().batchUpdate(
            documentId=doc_id,
            body={"requests": requests}
        ).execute()

    return {
        "id": doc_id,
        "title": title,
        "url": f"https://docs.google.com/document/d/{doc_id}/edit"
    }
