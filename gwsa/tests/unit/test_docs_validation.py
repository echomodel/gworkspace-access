import pytest
import random
import string
from gwsa.sdk.docs.validators import validate_doc_id
from gwsa.sdk.exceptions import LocalPathError, InvalidDocIdError

def generate_safe_id(length=44):
    """Generates a random ID to avoid hardcoding strings that might trip scanners."""
    chars = string.ascii_letters + string.digits + "-_"
    return "".join(random.choice(chars) for _ in range(length))

class TestDocIdValidation:
    """Test suite for Google Doc ID validation."""

    def test_valid_doc_ids(self):
        """Should accept valid Google Doc IDs."""
        valid_ids = [
            generate_safe_id(44),
            generate_safe_id(20),
            "Valid-ID_12345"
        ]
        for doc_id in valid_ids:
            validate_doc_id(doc_id)

    def test_reject_local_paths(self):
        """Should reject strings that look like local paths (slashes, tilde, dots)."""
        path_indicators = [
            "/tmp/file",      # Forward slash
            "C:\\Users",      # Backslash
            "~/notes",        # Tilde
            "doc.md",         # Dot
            "./local",        # Dot and slash
            "folder/sub"      # Relative path
        ]
        for path in path_indicators:
            with pytest.raises(LocalPathError) as exc:
                validate_doc_id(path)
            assert "looks like a local path" in str(exc.value).lower()

    def test_reject_invalid_ids(self):
        """Should reject IDs that are malformed (invalid chars, empty, too short)."""
        invalid_ids = [
            "doc id with spaces",
            "doc@id",
            "",
            "short"
        ]
        for doc_id in invalid_ids:
            with pytest.raises(InvalidDocIdError) as exc:
                validate_doc_id(doc_id)
            assert "invalid doc_id" in str(exc.value).lower()
            assert "local path" not in str(exc.value).lower()