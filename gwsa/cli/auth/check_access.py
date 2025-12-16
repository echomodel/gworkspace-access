"""Check credential validity and API access.

This is a standalone utility that does NOT affect gwsa configuration.
Use it to verify tokens work before deploying them or to diagnose auth issues.
"""

import os
import logging

# Re-export from SDK
from gwsa.sdk.auth import (
    REQUIRED_SCOPES,
    FEATURE_SCOPES,
    IDENTITY_SCOPES,
    get_credentials as get_active_credentials,
    get_token_info,
    get_feature_status,
    refresh_credentials as test_refresh,
)

logger = logging.getLogger(__name__)


def get_token_scopes(creds) -> list:
    """Get the scopes for a given credential."""
    return get_token_info(creds)["scopes"]


# =============================================================================
# CLI-specific API testing functions (not in SDK since they're diagnostic tools)
# =============================================================================

def test_gmail_access(creds) -> dict:
    """Test Gmail API access by listing labels."""
    from googleapiclient.discovery import build

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
    """Test Google Docs API access."""
    from googleapiclient.discovery import build
    from googleapiclient.errors import HttpError

    api_logger = logging.getLogger('googleapiclient.http')
    old_level = api_logger.level
    api_logger.setLevel(logging.ERROR)

    try:
        docs = build("docs", "v1", credentials=creds)
        docs.documents().get(documentId="nonexistent_doc_id_for_test").execute()
        return {"success": True}
    except HttpError as e:
        if e.resp.status == 404:
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
    """Test Google Sheets API access."""
    from googleapiclient.discovery import build
    from googleapiclient.errors import HttpError

    api_logger = logging.getLogger('googleapiclient.http')
    old_level = api_logger.level
    api_logger.setLevel(logging.ERROR)

    try:
        sheets = build("sheets", "v4", credentials=creds)
        sheets.spreadsheets().get(spreadsheetId="nonexistent_sheet_id_for_test").execute()
        return {"success": True}
    except HttpError as e:
        if e.resp.status == 404:
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
    """Test Google Drive API access."""
    from googleapiclient.discovery import build

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


def test_chat_access(creds) -> dict:
    """Test Google Chat API access."""
    from googleapiclient.discovery import build
    from googleapiclient.errors import HttpError

    api_logger = logging.getLogger('googleapiclient.http')
    old_level = api_logger.level
    api_logger.setLevel(logging.ERROR)

    try:
        chat = build("chat", "v1", credentials=creds)
        # Try to list spaces (limit 1) to verify access
        chat.spaces().list(pageSize=1).execute()
        return {"success": True}
    except HttpError as e:
        if e.resp.status == 403:
            return {"success": False, "error": "insufficient permissions"}
        else:
            return {"success": False, "error": str(e)}
    except Exception as e:
        return {"success": False, "error": str(e)}
    finally:
        api_logger.setLevel(old_level)


# Map of supported API names to test functions
SUPPORTED_APIS = {
    "mail": test_gmail_access,
    "docs": test_docs_access,
    "sheets": test_sheets_access,
    "drive": test_drive_access,
    "chat": test_chat_access,
}


def test_apis(creds, only: list = None) -> dict:
    """Test specified APIs (or all if none specified)."""
    apis_to_test = only if only else list(SUPPORTED_APIS.keys())

    results = {}
    for api_name in apis_to_test:
        test_fn = SUPPORTED_APIS.get(api_name.lower())
        if test_fn:
            results[api_name] = test_fn(creds)

    return results


def validate_api_names(names: list) -> list:
    """Validate that all API names are recognized."""
    return [n for n in names if n.lower() not in SUPPORTED_APIS]
