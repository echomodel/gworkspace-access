"""Google Docs service factory."""

from googleapiclient.discovery import build

from ..auth import get_credentials


def get_docs_service():
    """
    Build and return a Google Docs API service object.

    Uses credentials from the active gwsa profile.

    Returns:
        Google Docs API service object
    """
    creds, _ = get_credentials()
    return build("docs", "v1", credentials=creds)
