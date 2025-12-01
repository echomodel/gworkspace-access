"""Check credential validity and API access.

This is a standalone utility that does NOT affect gwsa configuration.
Use it to verify tokens work before deploying them or to diagnose auth issues.
"""

import os
import logging

logger = logging.getLogger(__name__)


def find_token_file(token_path: str = None, config_token_path: str = None) -> str | None:
    """
    Find token file, checking common locations.

    Args:
        token_path: Explicit path provided by user
        config_token_path: Path from gwsa config (e.g., setup_local.USER_TOKEN_FILE)

    Returns:
        Path to token file, or None if not found
    """
    if token_path and os.path.exists(token_path):
        return token_path

    # Check current directory
    if os.path.exists("user_token.json"):
        return "user_token.json"

    # Check config directory
    if config_token_path and os.path.exists(config_token_path):
        return config_token_path

    return None


def check_credentials(
    token_file: str = None,
    use_adc: bool = False,
    config_token_path: str = None
) -> tuple[object, str]:
    """
    Load and validate credentials from token file or ADC.

    Args:
        token_file: Explicit path to token file
        use_adc: If True, use Application Default Credentials
        config_token_path: Fallback path from gwsa config

    Returns:
        Tuple of (credentials, source_description)

    Raises:
        Exception if credentials cannot be loaded
    """
    import google.auth
    from google.oauth2.credentials import Credentials

    if use_adc:
        creds, project = google.auth.default()
        source = "Application Default Credentials"
        if project:
            source += f" (project: {project})"
        return creds, source

    # Find token file
    found_path = find_token_file(token_file, config_token_path)

    if found_path:
        creds = Credentials.from_authorized_user_file(found_path)
        return creds, f"Token file: {os.path.abspath(found_path)}"

    # Fall back to ADC
    creds, project = google.auth.default()
    source = "Application Default Credentials (fallback - no token file found)"
    if project:
        source = f"Application Default Credentials (fallback, project: {project})"
    return creds, source


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

    try:
        gmail = build("gmail", "v1", credentials=creds)
        results = gmail.users().labels().list(userId="me").execute()
        labels = results.get("labels", [])
        return {"success": True, "label_count": len(labels)}
    except Exception as e:
        return {"success": False, "error": str(e)}


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

    try:
        drive = build("drive", "v3", credentials=creds)
        drive.files().list(pageSize=1).execute()
        return {"success": True}
    except Exception as e:
        return {"success": False, "error": str(e)}


# Map of supported API names to test functions
SUPPORTED_APIS = {
    "gmail": test_gmail_access,
    "docs": test_docs_access,
    "sheets": test_sheets_access,
    "drive": test_drive_access,
}


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
