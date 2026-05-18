"""Gmail service factory for GWSA SDK."""

import logging
from typing import Any

from googleapiclient.discovery import build

from ..auth import get_credentials

logger = logging.getLogger(__name__)


def get_gmail_service() -> Any:
    """Build an authenticated Gmail API service for the current user."""
    creds, source = get_credentials()
    logger.debug(f"Building Gmail service using credentials from: {source}")
    return build("gmail", "v1", credentials=creds)
