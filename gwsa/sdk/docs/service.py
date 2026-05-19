"""Google Docs service factory."""

from typing import Optional

from googleapiclient.discovery import build

from ..auth import get_credentials


def get_docs_service(account: Optional[str] = None):
    """Build an authenticated Google Docs API service for the current user.

    Args:
        account: Optional selector — account name or Google email.
            Omit to use the user's default account.
    """
    creds, _ = get_credentials(account=account)
    return build("docs", "v1", credentials=creds)
