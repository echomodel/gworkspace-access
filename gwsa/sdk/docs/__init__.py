"""Google Docs SDK module.

Provides functions for creating, reading, updating, and listing Google Docs.
"""

from .service import get_docs_service
from .create import create_document
from .read import get_document, get_document_text, get_document_content
from .update import insert_text, replace_text, append_text, batch_update
from .list import list_documents

__all__ = [
    "get_docs_service",
    "create_document",
    "get_document",
    "get_document_text",
    "get_document_content",
    "insert_text",
    "replace_text",
    "append_text",
    "batch_update",
    "list_documents",
]
