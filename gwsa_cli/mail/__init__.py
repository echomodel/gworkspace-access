import os
import os.path
import logging

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

logger = logging.getLogger(__name__)

# If modifying these scopes, the user_token.json file will need to be re-generated.
# Run: gwsa setup --new-user
SCOPES = [
    "https://www.googleapis.com/auth/gmail.modify",
    "https://www.googleapis.com/auth/drive.file",  # Upload files to Drive (devws repo user-archive)
]
# Use ~/.config/gworkspace-access for storing credentials
_CONFIG_DIR = os.path.expanduser("~/.config/gworkspace-access")
USER_TOKEN_FILE = os.path.join(_CONFIG_DIR, "user_token.json")
CLIENT_SECRETS_FILE = os.path.join(_CONFIG_DIR, "client_secrets.json")


from ..auth.check_access import get_active_credentials

# ... (rest of imports and constants)

def _get_gmail_service():
    """
    Authenticates using the central credential logic and returns a Gmail API service object.
    """
    try:
        creds, source = get_active_credentials()
        logger.debug(f"Building Gmail service using credentials from: {source}")
        return build("gmail", "v1", credentials=creds)
    except Exception as e:
        logger.error(f"Failed to get active credentials or build Gmail service: {e}")
        raise

