"""Google Sheets service factory."""

from typing import Optional

from googleapiclient.discovery import build

from ..auth import get_credentials


def get_sheets_service(account: Optional[str] = None):
    """Build an authenticated Google Sheets API service for the current user.

    Args:
        account: Optional selector — account name or Google email.
            Omit to use the user's default account.
    """
    creds, _ = get_credentials(account=account)
    return build("sheets", "v4", credentials=creds)
