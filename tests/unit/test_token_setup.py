"""
Unit tests for the token-based setup flow (_atomic_client_creds_setup).

These tests verify the atomic "stage-then-commit" pattern used in setup_local.py:
1. New credentials are staged to a temp directory first
2. The OAuth browser flow runs against the staged credentials
3. Only on success are both files atomically moved to their final locations
4. On failure, original credentials remain untouched (rollback guarantee)

WHY WE MOCK ONLY run_local_server:
-----------------------------------
We intentionally mock only InstalledAppFlow.run_local_server() rather than the
entire InstalledAppFlow class. This design choice:

1. Exercises more real code: from_client_secrets_file() actually parses our test
   JSON files, validating that our test fixtures have the correct structure.

2. Tests the real integration point: run_local_server() is the precise boundary
   where the code interacts with the browser/user. Everything before it (file
   parsing, flow initialization) and after it (credential serialization) runs
   with real library code.

3. Catches real bugs: If the client_secrets.json structure changes or the library
   changes its parsing, our tests will fail - unlike mocking the whole class which
   would silently pass with invalid test data.

The fake client_secrets.json files work because from_client_secrets_file() only
validates JSON structure locally - no network calls are made until run_local_server().
"""

import json
from pathlib import Path
import pytest
from unittest.mock import MagicMock, patch
from google_auth_oauthlib.flow import InstalledAppFlow
from gwsa.cli.setup_local import _atomic_client_creds_setup


@pytest.fixture
def isolated_config_dir(tmp_path: Path, monkeypatch) -> Path:
    """
    Creates a temporary, isolated config directory and patches module constants.

    This isolation ensures tests don't touch the user's real ~/.config/gworkspace-access
    directory and allows us to verify file operations in a controlled environment.
    """
    config_dir = tmp_path / "test_config"
    config_dir.mkdir()

    # Redirect all file operations to our temp directory
    monkeypatch.setattr("gwsa.cli.setup_local._CONFIG_DIR", str(config_dir))
    monkeypatch.setattr("gwsa.cli.setup_local.CLIENT_SECRETS_FILE", str(config_dir / "client_secrets.json"))
    monkeypatch.setattr("gwsa.cli.setup_local.USER_TOKEN_FILE", str(config_dir / "user_token.json"))

    return config_dir


def _create_valid_client_secrets(path: Path, client_id: str = "test_id") -> dict:
    """
    Creates a valid client_secrets.json file with the required structure.

    The structure matches what Google Cloud Console generates for OAuth 2.0
    Desktop clients. InstalledAppFlow.from_client_secrets_file() parses this
    structure locally without making network calls - it only validates the
    JSON schema.

    Returns the content as a dict for verification purposes.
    """
    content = {
        "installed": {
            "client_id": client_id,
            "project_id": "test-project",
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
            "auth_provider_x509_cert_url": "https://www.googleapis.com/oauth2/v1/certs",
            "client_secret": "test-secret",
            "redirect_uris": ["http://localhost"]
        }
    }
    with open(path, "w") as f:
        json.dump(content, f)
    return content


def test_client_creds_flow_success(isolated_config_dir: Path):
    """
    Verify that providing a new client_secrets.json successfully replaces
    any existing credentials and configures the tool for token mode.

    This tests the "happy path" of the atomic setup:
    1. User has existing (working) credentials
    2. User provides new client_secrets.json
    3. Browser auth succeeds
    4. Both old files are replaced with new ones

    The key guarantee: after success, both files are from the NEW credentials,
    not a mix of old and new.
    """
    # Arrange: Create pre-existing, "original" files in the isolated dir
    # These represent a user's current working configuration
    _create_valid_client_secrets(isolated_config_dir / "client_secrets.json", "original_id")
    original_token = {"token": "original_token"}
    with open(isolated_config_dir / "user_token.json", "w") as f:
        json.dump(original_token, f)

    # Arrange: Create the "new" client secrets file to be passed in
    # This is what the user provides via --client-creds flag
    new_secrets_path = isolated_config_dir / "new_secrets.json"
    _create_valid_client_secrets(new_secrets_path, "new_id")

    # Arrange: Mock only run_local_server (the browser-based login)
    # This simulates successful user authentication in the browser
    mock_creds = MagicMock()
    mock_creds.to_json.return_value = '{"token": "new_dummy_token", "refresh_token": "new_dummy_refresh"}'

    with patch.object(InstalledAppFlow, 'run_local_server', return_value=mock_creds):
        # Action: Run the atomic setup
        success = _atomic_client_creds_setup(str(new_secrets_path), force_new_user=True)

    # Assertion: Setup should succeed
    assert success is True

    # Assertion: client_secrets.json should contain the NEW client ID
    # (proves the file was replaced, not left as original)
    with open(isolated_config_dir / "client_secrets.json", "r") as f:
        final_secrets = json.load(f)
    assert final_secrets["installed"]["client_id"] == "new_id"

    # Assertion: user_token.json should contain the NEW token
    # (proves auth was performed with new credentials and saved)
    with open(isolated_config_dir / "user_token.json", "r") as f:
        final_token = json.load(f)
    assert final_token["token"] == "new_dummy_token"


def test_client_creds_flow_rollback(isolated_config_dir: Path):
    """
    Verify that if the OAuth flow fails, the original credentials are
    left untouched (rollback behavior).

    This tests the critical failure scenario:
    1. User has existing (working) credentials
    2. User provides new client_secrets.json
    3. Browser auth FAILS (user cancels, network error, etc.)
    4. Original credentials must remain intact

    The key guarantee: a failed setup attempt can NEVER corrupt or lose a user's
    existing working configuration. This is why we use the atomic "stage-then-commit"
    pattern - new files are staged to a temp directory, and only moved to final
    locations after complete success.
    """
    # Arrange: Create pre-existing, "original" files in the isolated dir
    # These represent a user's current WORKING configuration that must be protected
    _create_valid_client_secrets(isolated_config_dir / "client_secrets.json", "original_id")
    original_token = {"token": "original_token"}
    with open(isolated_config_dir / "user_token.json", "w") as f:
        json.dump(original_token, f)

    # Arrange: Create the "new" client secrets file to be passed in
    new_secrets_path = isolated_config_dir / "new_secrets.json"
    _create_valid_client_secrets(new_secrets_path, "new_id")

    # Arrange: Mock run_local_server to FAIL
    # This simulates: user closes browser, network timeout, invalid credentials, etc.
    with patch.object(
        InstalledAppFlow,
        'run_local_server',
        side_effect=Exception("User cancelled the OAuth flow")
    ):
        # Action: Attempt the atomic setup (should fail gracefully)
        success = _atomic_client_creds_setup(str(new_secrets_path), force_new_user=True)

    # Assertion: Setup should fail (return False, not raise)
    assert success is False

    # Assertion: client_secrets.json must still have ORIGINAL client ID
    # (proves the atomic pattern protected the original file)
    with open(isolated_config_dir / "client_secrets.json", "r") as f:
        final_secrets = json.load(f)
    assert final_secrets["installed"]["client_id"] == "original_id"

    # Assertion: user_token.json must still have ORIGINAL token
    # (proves both files are protected together, not just one)
    with open(isolated_config_dir / "user_token.json", "r") as f:
        final_token = json.load(f)
    assert final_token["token"] == "original_token"

    # Assertion: No temporary files should be left behind
    # The atomic setup creates a temp directory for staging - it must be cleaned
    # up even on failure (handled by the finally block in _atomic_client_creds_setup)
    files_in_config_dir = list(isolated_config_dir.iterdir())
    expected_files = {"client_secrets.json", "user_token.json", "new_secrets.json"}
    actual_files = {f.name for f in files_in_config_dir}
    assert actual_files == expected_files, f"Unexpected files found: {actual_files - expected_files}"