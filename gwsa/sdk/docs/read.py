"""Google Docs reading operations."""

from googleapiclient.errors import HttpError

from typing import List, Dict, Any, Optional

from .service import get_docs_service
from .validators import validate_doc_id
from ..drive.service import get_drive_service


def get_document(doc_id: str, account: Optional[str] = None) -> dict:
    """Get a document's full structure after verifying it is a Google Doc.

    Args:
        doc_id: The Google Doc ID
        account: Optional account selector — name or email. Omit to use
            the user's default account.

    Returns:
        The full document object from the API including documentId,
        title, body (with content array), revisionId.

    Raises:
        ValueError: If the document ID is not for a Google Doc.
        LocalPathError: If the ID looks like a local file path.
        InvalidDocIdError: If the ID is malformed.
    """
    validate_doc_id(doc_id)

    drive_service = get_drive_service(account=account)
    try:
        file_metadata = drive_service.files().get(fileId=doc_id, fields='mimeType').execute()
        mime_type = file_metadata.get('mimeType')

        if mime_type != 'application/vnd.google-apps.document':
            raise ValueError(
                f"File with ID '{doc_id}' is not a Google Doc (MIME type: {mime_type}). "
                f"Use the 'drive_download' tool for non-native formats like PDFs or images."
            )
    except HttpError:
        pass

    service = get_docs_service(account=account)
    return service.documents().get(documentId=doc_id, includeTabsContent=True).execute()


def get_document_text(doc_id: str, account: Optional[str] = None) -> str:
    """Get the plain text content of a document.

    Args:
        doc_id: The Google Doc ID
        account: Optional account selector — name or email. Omit to use
            the user's default account.
    """
    doc = get_document(doc_id, account=account)
    return extract_text_from_document(doc)


def get_document_content(doc_id: str, account: Optional[str] = None) -> dict:
    """Get document metadata and content.

    Args:
        doc_id: The Google Doc ID
        account: Optional account selector — name or email. Omit to use
            the user's default account.

    Returns:
        Dict with id, title, url, text, revision_id.
    """
    doc = get_document(doc_id, account=account)

    return {
        "id": doc.get("documentId"),
        "title": doc.get("title"),
        "url": f"https://docs.google.com/document/d/{doc.get('documentId')}/edit",
        "text": extract_text_from_document(doc),
        "revision_id": doc.get("revisionId"),
    }


def extract_text_from_document(doc: dict) -> str:
    """
    Extract plain text from a document structure, supporting both tabbed and non-tabbed documents.

    Args:
        doc: The document object from the API

    Returns:
        Plain text content
    """
    if "tabs" in doc:
        return extract_text_from_tabs(doc["tabs"])
    return extract_text_from_body(doc.get("body", {}))


def extract_text_from_tabs(tabs: list) -> str:
    """Recursively extract text from a list of tabs and their child tabs."""
    text_parts = []
    for tab in tabs:
        if "documentTab" in tab:
            doc_tab = tab["documentTab"]
            if "body" in doc_tab:
                text_parts.append(extract_text_from_body(doc_tab["body"]))
        if "childTabs" in tab:
            text_parts.append(extract_text_from_tabs(tab["childTabs"]))
    return "".join(text_parts)


def extract_text_from_body(body: dict) -> str:
    """Extract text from a single document or tab body."""
    content = body.get("content", [])
    text_parts = []

    for element in content:
        if "paragraph" in element:
            paragraph = element["paragraph"]
            para_text = extract_paragraph_text(paragraph)
            text_parts.append(para_text)
        elif "table" in element:
            # Extract text from table cells
            table = element["table"]
            for row in table.get("tableRows", []):
                for cell in row.get("tableCells", []):
                    for cell_content in cell.get("content", []):
                        if "paragraph" in cell_content:
                            para_text = extract_paragraph_text(cell_content["paragraph"])
                            text_parts.append(para_text)

    return "".join(text_parts)


def extract_paragraph_text(paragraph: dict) -> str:
    """
    Extract text from a paragraph element.

    Args:
        paragraph: A paragraph element from the document

    Returns:
        Plain text content of the paragraph
    """
    text = ""
    for element in paragraph.get("elements", []):
        text_run = element.get("textRun")
        if text_run:
            text += text_run.get("content", "")
    return text
