import re
from gwsa.sdk.exceptions import LocalPathError, InvalidDocIdError

# Detects strings containing common path/filename indicators: slashes, tilde, or dots.
LOCAL_PATH_REGEX = re.compile(r'[\\/~.]')

# Validates Google Doc IDs: alphanumeric, dashes, and underscores only.
# Length requirement 10-128 characters.
VALID_ID_REGEX = re.compile(r'^[a-zA-Z0-9-_]{10,128}$')

def validate_doc_id(doc_id: str) -> None:
    """
    Validates a Google Doc ID using regex patterns.
    
    Args:
        doc_id: The document ID to check.

    Raises:
        LocalPathError: If the ID contains path indicators.
        InvalidDocIdError: If the ID is malformed or invalid.
    """
    if not isinstance(doc_id, str):
        raise InvalidDocIdError("Invalid doc_id.")

    # 1. Local Path Check
    if LOCAL_PATH_REGEX.search(doc_id):
        raise LocalPathError("Invalid doc_id. This looks like a local path.")

    # 2. Valid ID Check
    if not VALID_ID_REGEX.match(doc_id):
        raise InvalidDocIdError("Invalid doc_id.")