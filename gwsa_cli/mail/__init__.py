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


def _get_gmail_service():
    """
    Authenticates and returns a Gmail API service object.
    Assumes user_token.json is present and valid.
    """
    creds = None
    if not os.path.exists(USER_TOKEN_FILE):
        logger.error(f"Error: User credentials file '{USER_TOKEN_FILE}' not found.")
        logger.error("Please run 'gwsa setup' to set up your credentials first.")
        raise FileNotFoundError(f"User credentials file '{USER_TOKEN_FILE}' not found. Run 'gwsa setup'.")

    logger.debug(f"Attempting to load user credentials from {USER_TOKEN_FILE}.")
    try:
        creds = Credentials.from_authorized_user_file(USER_TOKEN_FILE, SCOPES)
        logger.debug("User credentials loaded.")
    except Exception as e:
        logger.error(f"Failed to load user credentials from {USER_TOKEN_FILE}: {e}")
        logger.error("Your user token might be corrupted or invalid. Please run 'gwsa setup' to re-authenticate.")
        raise
    
    # Check if credentials need refreshing. If they do, refresh and save.
    if creds and creds.expired and creds.refresh_token:
        logger.debug("User credentials expired, attempting to refresh token.")
        try:
            creds.refresh(Request())
            logger.debug("User token refreshed successfully.")
            # Save the refreshed credentials for the next run
            with open(USER_TOKEN_FILE, "w") as token:
                token.write(creds.to_json())
            logger.debug(f"Refreshed user credentials saved to {USER_TOKEN_FILE}.")
        except Exception as e:
            logger.error(f"Failed to refresh user token: {e}")
            logger.error("Your refresh token might be invalid. Please run 'gwsa setup' to re-authenticate.")
            raise
    elif not creds.valid:
        logger.error("User credentials are not valid. Please run 'gwsa setup' to re-authenticate.")
        raise Exception("Invalid user credentials.")
    else:
        logger.debug("User credentials are valid.")

    return build("gmail", "v1", credentials=creds)

