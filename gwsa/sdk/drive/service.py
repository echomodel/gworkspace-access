"""Google Drive service factory."""

from typing import Optional

from googleapiclient.discovery import build

from ..auth import get_credentials


def get_drive_service(account: Optional[str] = None):
    """Build an authenticated Google Drive API service for the current user.

    Args:
        account: Optional selector — account name or Google email.
            Omit to use the user's default account.
    """
    creds, _ = get_credentials(account=account)
    return build("drive", "v3", credentials=creds)
