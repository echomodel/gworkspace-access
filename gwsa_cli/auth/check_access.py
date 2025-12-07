"""Check credential validity and API access.

This is a standalone utility that does NOT affect gwsa configuration.
Use it to verify tokens work before deploying them or to diagnose auth issues.
"""

import os
import logging
from .. import config

REQUIRED_SCOPES = {
    "https://www.googleapis.com/auth/gmail.modify",
    "https://www.googleapis.com/auth/drive",
    "https://www.googleapis.com/auth/documents",
    "https://www.googleapis.com/auth/spreadsheets",
}

logger = logging.getLogger(__name__)


def find_token_file(token_path: str = None, config_token_path: str = None) -> str | None:
    """
    Find token file, checking common locations.

    Args:
        token_path: Explicit path provided by user (highest priority)
        config_token_path: Path from gwsa config (e.g., setup_local.USER_TOKEN_FILE)

    Returns:
        Path to token file, or None if not found

    Search order:
    1. Explicit token_path (user-provided via --token-file flag)
    2. Config directory path (when auth.mode is 'token')
    3. Current directory (fallback for standalone usage)
    """
    # Explicit user-provided path takes highest priority
    if token_path and os.path.exists(token_path):
        return token_path

    # Config directory path takes priority over current directory
    # This ensures `gwsa setup --client-creds` uses the right token after setup
    if config_token_path and os.path.exists(config_token_path):
        return config_token_path

    # Fallback: check current directory (for standalone token usage)
    if os.path.exists("user_token.json"):
        return "user_token.json"

    return None


def get_active_credentials(
    token_file: str = None, # Allow explicit override for `access check --token-file`
    use_adc: bool = False,    # Allow explicit override for `access check --application-default`
    config_token_path: str = None
) -> tuple[object, str]:
    """
    Load credentials strictly based on the configured auth mode or explicit flags.
    No fallback behavior.
    """
    import google.auth
    from google.oauth2.credentials import Credentials

    # Explicit flags for `gwsa access check` take highest precedence
    if use_adc:
        creds, project = google.auth.default()
        source = "Application Default Credentials (from flag)"
        if project:
            source += f" (project: {project})"
        return creds, source

    if token_file:
        found_path = find_token_file(token_file)
        if found_path:
            creds = Credentials.from_authorized_user_file(found_path)
            return creds, f"Token file: {os.path.abspath(found_path)}"
        else:
            raise FileNotFoundError(f"Specified token file not found: {token_file}")

    # If no flags, use the mode from config.yaml
    auth_mode = config.get_config_value("auth.mode")

    if auth_mode == 'adc':
        creds, project = google.auth.default()
        source = "Application Default Credentials (from config)"
        if project:
            source += f" (project: {project})"
        return creds, source
    
    elif auth_mode == 'token':
        # Use the standard config path if not explicitly provided
        from gwsa_cli.mail import USER_TOKEN_FILE
        effective_token_path = config_token_path or USER_TOKEN_FILE
        found_path = find_token_file(config_token_path=effective_token_path)
        if found_path:
            creds = Credentials.from_authorized_user_file(found_path)
            return creds, f"Token file: {os.path.abspath(found_path)}"
        else:
            raise FileNotFoundError(f"Token file not found at expected path: {effective_token_path}")
    
    else: # No config or unknown mode
        # This will be caught by the higher-level status check, but raise for safety
        raise ValueError("No valid auth.mode configured and no credentials specified.")


def test_refresh(creds) -> bool:
    """
    Test that credentials can be refreshed.

    Returns:
        True if refresh succeeded

    Raises:
        Exception if refresh fails
    """
    from google.auth.transport.requests import Request
    creds.refresh(Request())
    return True


def test_gmail_access(creds) -> dict:
    """
    Test Gmail API access by listing labels.

    Returns:
        Dict with 'success' bool and 'label_count' or 'error'
    """
    from googleapiclient.discovery import build

    # Suppress expected HTTP error warnings
    api_logger = logging.getLogger('googleapiclient.http')
    old_level = api_logger.level
    api_logger.setLevel(logging.ERROR)

    try:
        gmail = build("gmail", "v1", credentials=creds)
        results = gmail.users().labels().list(userId="me").execute()
        labels = results.get("labels", [])
        return {"success": True, "label_count": len(labels)}
    except Exception as e:
        return {"success": False, "error": str(e)}
    finally:
        api_logger.setLevel(old_level)


def test_docs_access(creds) -> dict:
    """
    Test Google Docs API access by attempting to get a non-existent document.

    We expect a 404 (not found), which proves we have API access.
    A 403 would indicate insufficient permissions.

    Returns:
        Dict with 'success' bool and optional 'error'
    """
    from googleapiclient.discovery import build
    from googleapiclient.errors import HttpError

    # Suppress expected HTTP error warnings
    api_logger = logging.getLogger('googleapiclient.http')
    old_level = api_logger.level
    api_logger.setLevel(logging.ERROR)

    try:
        docs = build("docs", "v1", credentials=creds)
        # Try to get a document that doesn't exist - we expect 404, not 403
        docs.documents().get(documentId="nonexistent_doc_id_for_test").execute()
        return {"success": True}  # Unlikely to reach here
    except HttpError as e:
        if e.resp.status == 404:
            # 404 means we have access but doc doesn't exist - that's success
            return {"success": True}
        elif e.resp.status == 403:
            return {"success": False, "error": "insufficient permissions"}
        else:
            return {"success": False, "error": str(e)}
    except Exception as e:
        return {"success": False, "error": str(e)}
    finally:
        api_logger.setLevel(old_level)


def test_sheets_access(creds) -> dict:
    """
    Test Google Sheets API access by attempting to get a non-existent spreadsheet.

    We expect a 404 (not found), which proves we have API access.
    A 403 would indicate insufficient permissions.

    Returns:
        Dict with 'success' bool and optional 'error'
    """
    from googleapiclient.discovery import build
    from googleapiclient.errors import HttpError

    # Suppress expected HTTP error warnings
    api_logger = logging.getLogger('googleapiclient.http')
    old_level = api_logger.level
    api_logger.setLevel(logging.ERROR)

    try:
        sheets = build("sheets", "v4", credentials=creds)
        # Try to get a spreadsheet that doesn't exist - we expect 404, not 403
        sheets.spreadsheets().get(spreadsheetId="nonexistent_sheet_id_for_test").execute()
        return {"success": True}  # Unlikely to reach here
    except HttpError as e:
        if e.resp.status == 404:
            # 404 means we have access but sheet doesn't exist - that's success
            return {"success": True}
        elif e.resp.status == 403:
            return {"success": False, "error": "insufficient permissions"}
        else:
            return {"success": False, "error": str(e)}
    except Exception as e:
        return {"success": False, "error": str(e)}
    finally:
        api_logger.setLevel(old_level)


def test_drive_access(creds) -> dict:
    """
    Test Google Drive API access by listing files (limit 1).

    Returns:
        Dict with 'success' bool and optional 'error'
    """
    from googleapiclient.discovery import build

    # Suppress expected HTTP error warnings
    api_logger = logging.getLogger('googleapiclient.http')
    old_level = api_logger.level
    api_logger.setLevel(logging.ERROR)

    try:
        drive = build("drive", "v3", credentials=creds)
        drive.files().list(pageSize=1).execute()
        return {"success": True}
    except Exception as e:
        return {"success": False, "error": str(e)}
    finally:
        api_logger.setLevel(old_level)


# Map of supported API names to test functions
# Keys match FEATURE_SCOPES for consistency when testing by feature name
SUPPORTED_APIS = {
    "mail": test_gmail_access,
    "docs": test_docs_access,
    "sheets": test_sheets_access,
    "drive": test_drive_access,
}

# Define scopes required for each major feature
FEATURE_SCOPES = {
    "mail": {"https://www.googleapis.com/auth/gmail.modify"},
    "sheets": {"https://www.googleapis.com/auth/spreadsheets"},
    "docs": {"https://www.googleapis.com/auth/documents"},
    "drive": {"https://www.googleapis.com/auth/drive"},
}

def get_feature_status(granted_scopes: set[str]) -> dict[str, bool]:
    """
    Determines if each major gwsa feature is supported by the granted scopes.

    Returns:
        A dictionary where keys are feature names (e.g., "mail") and values are
        booleans indicating if all required scopes for that feature are granted.
    """
    status = {}
    for feature, required_scopes in FEATURE_SCOPES.items():
        status[feature] = required_scopes.issubset(granted_scopes)
    return status

def test_apis(creds, only: list[str] = None) -> dict:
    """
    Test specified APIs (or all if none specified) and return results.

    Args:
        creds: Google credentials object
        only: List of API names to test (lowercase). If None, tests all.

    Returns:
        Dict mapping API name to result dict
    """
    apis_to_test = only if only else list(SUPPORTED_APIS.keys())

    results = {}
    for api_name in apis_to_test:
        test_fn = SUPPORTED_APIS.get(api_name.lower())
        if test_fn:
            results[api_name] = test_fn(creds)

    return results


def validate_api_names(names: list[str]) -> list[str]:
    """
    Validate that all API names are recognized.

    Args:
        names: List of API names to validate

    Returns:
        List of unrecognized names (empty if all valid)
    """
    return [n for n in names if n.lower() not in SUPPORTED_APIS]


def get_token_scopes(creds) -> list[str]:
    """
    Use Google's tokeninfo endpoint to get the scopes for a given credential.

    Returns:
        A list of scope strings.

    Raises:
        Exception on network error or if token is invalid.
    """
    import urllib.request
    import json
    from google.auth.transport.requests import Request

    if not creds.valid and creds.refresh_token:
        creds.refresh(Request())

    access_token = creds.token
    if not access_token:
        raise ValueError("Credentials object has no access token.")

    url = f"https://www.googleapis.com/oauth2/v3/tokeninfo?access_token={access_token}"
    
    with urllib.request.urlopen(url) as response:
        if response.status == 200:
            data = json.loads(response.read().decode())
            return data.get("scope", "").split(" ")
        else:
            raise ConnectionError(f"Tokeninfo endpoint failed with status {response.status}: {response.read().decode()}")
