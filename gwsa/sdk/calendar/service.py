"""Google Calendar service factory for GWSA SDK."""

import logging
from typing import Any, Optional

from googleapiclient.discovery import build

from ..auth import get_credentials

logger = logging.getLogger(__name__)


def get_calendar_service(account: Optional[str] = None) -> Any:
    """Build an authenticated Google Calendar API service for the current user.

    Args:
        account: Optional selector for which of the current user's
            Google accounts to use — either the account ``name`` or
            its Google ``email``. Omit to use the user's default
            account (or sole account when only one is configured).
    """
    creds, source = get_credentials(account=account)
    logger.debug(f"Building Calendar service using credentials from: {source}")
    return build("calendar", "v3", credentials=creds)
