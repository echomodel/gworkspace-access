"""Gmail service factory for GWSA SDK."""

import logging
from typing import Optional, Any

from googleapiclient.discovery import build

from ..auth import get_credentials

logger = logging.getLogger(__name__)


def get_gmail_service(profile: str = None, use_adc: bool = False) -> Any:
    """
    Get an authenticated Gmail API service object.

    Args:
        profile: Optional profile name to use (defaults to active profile)
        use_adc: Force use of Application Default Credentials

    Returns:
        Gmail API service object

    Raises:
        ValueError: If no profile configured
        Exception: If authentication fails
    """
    creds, source = get_credentials(profile=profile, use_adc=use_adc)
    logger.debug(f"Building Gmail service using credentials from: {source}")
    return build("gmail", "v1", credentials=creds)
