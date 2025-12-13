"""Google Drive service factory."""

from googleapiclient.discovery import build

from ..auth import get_credentials


def get_drive_service():
    """
    Build and return a Google Drive API service object.

    Uses credentials from the active gwsa profile.

    Returns:
        Google Drive API service object
    """
    creds, _ = get_credentials()
    return build("drive", "v3", credentials=creds)
