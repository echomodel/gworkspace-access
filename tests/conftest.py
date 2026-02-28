"""
Test configuration and fixtures for gwsa integration tests.

This module provides:
- Profile-based test configuration from tests/test-config.yaml
- Profile status validation before tests run
- Graceful skipping when test prerequisites aren't met
- CLI runner fixture for integration tests

The test config maps gwsa profile names to test settings (search queries,
labels, etc.). Tests requiring specific emails are skipped if the active
gwsa profile isn't configured in test-config.yaml.
"""

import sys
import pytest
import subprocess
import json
import os
import yaml
from datetime import datetime, timedelta
from typing import Dict, Any, List, Optional
from pathlib import Path


# Path to test configuration file
TEST_CONFIG_FILE = Path(__file__).parent / "test-config.yaml"

# Example search query for documentation
EXAMPLE_SEARCH_QUERY = 'subject:"Your Daily Digest" from:"USPS Informed Delivery"'


def load_test_config() -> Dict[str, Any]:
    """Load test configuration from tests/test-config.yaml."""
    if not TEST_CONFIG_FILE.exists():
        return {"profiles": {}}

    with open(TEST_CONFIG_FILE, 'r') as f:
        config = yaml.safe_load(f) or {}

    return config


def get_active_gwsa_profile() -> Optional[str]:
    """Get the currently active gwsa profile name."""
    try:
        from gwsa.sdk.profiles import get_active_profile_name
        return get_active_profile_name()
    except Exception:
        return None


def get_test_settings_for_profile(profile_name: str) -> Optional[Dict[str, Any]]:
    """
    Get test settings for a specific gwsa profile.

    Returns None if the profile isn't configured in test-config.yaml.
    """
    config = load_test_config()
    profiles = config.get("profiles", {})
    return profiles.get(profile_name)


def check_profile_status() -> Dict[str, Any]:
    """
    Check if gwsa has a valid, working profile configured.

    Uses the same status check as 'gwsa setup' with no args.

    Returns:
        Dict with status info including:
            - ready: bool indicating if profile is usable
            - status: "CONFIGURED", "NOT_CONFIGURED", or "ERROR"
            - user_email: authenticated email (if available)
            - error: error message (if any)
    """
    try:
        from gwsa.cli.setup_local import _get_status_report
        report = _get_status_report(deep_check=False)

        ready = (
            report.get("status") == "CONFIGURED"
            and (report.get("creds_valid", False) or report.get("creds_refreshable", False))
            and not report.get("scope_validation_error")
        )

        return {
            "ready": ready,
            "status": report.get("status", "UNKNOWN"),
            "user_email": report.get("user_email"),
            "mode": report.get("mode"),
            "profile": report.get("profile"),
            "feature_status": report.get("feature_status", {}),
            "error": report.get("error_details") or report.get("scope_validation_error"),
        }
    except Exception as e:
        return {
            "ready": False,
            "status": "ERROR",
            "error": str(e),
        }


def print_test_config_instructions(profile_name: str):
    """Print instructions for configuring test settings for a profile."""
    print("\n" + "=" * 70)
    print("GWSA INTEGRATION TEST CONFIGURATION REQUIRED")
    print("=" * 70)
    print(f"\nActive gwsa profile: {profile_name}")
    print(f"No test settings found for this profile in: {TEST_CONFIG_FILE}")
    print("\nTo enable tests requiring specific emails, add this profile to")
    print("test-config.yaml with a search query for routine, low-risk emails:\n")
    print("  profiles:")
    print(f"    {profile_name}:")
    print(f"      search_query: '{EXAMPLE_SEARCH_QUERY}'")
    print("      test_label: \"Test\"")
    print("      min_results: 2")
    print("      days_range: 60")
    print("\n" + "=" * 70 + "\n")


def print_profile_error(status: Dict[str, Any]):
    """Print error message for profile issues."""
    print("\n" + "=" * 70)
    print("GWSA PROFILE NOT READY")
    print("=" * 70)
    print(f"\nStatus: {status.get('status', 'UNKNOWN')}")
    if status.get('error'):
        print(f"Error: {status.get('error')}")
    print("\nRun 'gwsa setup' to configure authentication before running tests.")
    print("=" * 70 + "\n")


# Track if we've already printed instructions this session
_config_instructions_printed = False
_profile_error_printed = False


@pytest.fixture(scope="session", autouse=True)
def validate_test_environment():
    """
    Validate that the test environment is properly configured.

    This fixture runs once at the start of the test session and:
    1. Checks that gwsa has a valid profile configured
    2. Verifies the CLI is installed and working

    Prints helpful instructions if configuration is missing.
    """
    global _profile_error_printed

    # Check profile status
    status = check_profile_status()
    if not status["ready"]:
        if not _profile_error_printed:
            print_profile_error(status)
            _profile_error_printed = True
        pytest.exit("gwsa profile not configured. Run 'gwsa setup' first.", returncode=1)

    # Verify CLI is installed
    project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    try:
        result = subprocess.run(
            [sys.executable, "-m", "gwsa.cli", "--help"],
            capture_output=True,
            text=True,
            timeout=5,
            cwd=project_root
        )
        if result.returncode != 0:
            pytest.exit(
                f"gwsa CLI not properly installed. Run 'pip install -e .' first.\n"
                f"Error: {result.stderr}",
                returncode=1
            )
    except Exception as e:
        pytest.exit(f"Failed to verify CLI installation: {e}", returncode=1)

    # Print profile info
    print(f"\n✓ Profile: {status.get('profile')} ({status.get('mode')} mode)")
    print(f"✓ User: {status.get('user_email')}")

    # Check if test config exists for this profile
    profile_name = status.get('profile')
    test_settings = get_test_settings_for_profile(profile_name)
    if test_settings:
        print(f"✓ Test config: found settings for '{profile_name}'")
    else:
        print(f"⚠ Test config: no settings for '{profile_name}' (some tests will skip)")

    yield


@pytest.fixture(scope="session")
def active_profile_name() -> str:
    """Get the active gwsa profile name."""
    return get_active_gwsa_profile()


@pytest.fixture(scope="session")
def test_config(active_profile_name) -> Optional[Dict[str, Any]]:
    """
    Get test configuration for the active gwsa profile.

    Returns None if the profile isn't configured in test-config.yaml.
    """
    return get_test_settings_for_profile(active_profile_name)


@pytest.fixture(scope="session")
def require_test_config(active_profile_name, test_config):
    """
    Fixture that skips tests if no test config exists for the active profile.

    Use this fixture in tests that require profile-specific settings.
    Prints setup instructions on first skip.
    """
    global _config_instructions_printed

    if test_config is None:
        if not _config_instructions_printed:
            print_test_config_instructions(active_profile_name)
            _config_instructions_printed = True
        pytest.skip(f"No test config for profile '{active_profile_name}'")

    return test_config


@pytest.fixture(scope="session")
def search_query(require_test_config) -> str:
    """Get the search query for the active profile's test config."""
    query = require_test_config.get("search_query")
    if not query:
        pytest.skip("No search_query configured for this profile")
    return query


@pytest.fixture(scope="session")
def test_label(require_test_config) -> str:
    """Get the test label for the active profile's test config."""
    return require_test_config.get("test_label", "Test")


@pytest.fixture(scope="session")
def min_results(require_test_config) -> int:
    """Get the minimum expected results for the active profile."""
    return require_test_config.get("min_results", 2)


@pytest.fixture(scope="session")
def days_range(require_test_config) -> int:
    """Get the days range for the active profile."""
    return require_test_config.get("days_range", 60)


@pytest.fixture(scope="session")
def today_minus_n_days(days_range) -> str:
    """
    Calculate the date N days ago in YYYY-MM-DD format.

    Uses days_range from the active profile's test config.
    """
    date_n_days_ago = datetime.now() - timedelta(days=days_range)
    return date_n_days_ago.strftime("%Y-%m-%d")


# Backward compatibility alias
@pytest.fixture(scope="session")
def today_minus_60_days(require_test_config) -> str:
    """Calculate date based on profile's days_range (backward compat alias)."""
    dr = require_test_config.get("days_range", 60)
    date_n_days_ago = datetime.now() - timedelta(days=dr)
    return date_n_days_ago.strftime("%Y-%m-%d")


@pytest.fixture(scope="session")
def cli_runner():
    """
    Factory fixture that executes CLI commands via subprocess.

    Returns:
        Callable that takes command args and returns parsed result dict:
            - returncode: int (0 for success)
            - stdout: str (raw output)
            - stderr: str (error output)
            - json: dict/list (parsed JSON if valid, None otherwise)

    Usage:
        result = cli_runner(["mail", "search", "query"])
        messages = result["json"]
        assert result["returncode"] == 0
    """
    project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

    def run_command(command_args: List[str]) -> Dict[str, Any]:
        """Execute a gwsa CLI command and return parsed result."""
        try:
            result = subprocess.run(
                [sys.executable, "-m", "gwsa.cli"] + command_args,
                capture_output=True,
                text=True,
                timeout=30,
                cwd=project_root
            )

            # Try to parse JSON from stdout
            json_data = None
            if result.stdout.strip():
                try:
                    # Filter out log lines (starting with timestamps)
                    json_lines = [
                        line for line in result.stdout.split("\n")
                        if line.strip() and not line[0].isdigit()
                    ]
                    json_str = "\n".join(json_lines)
                    json_data = json.loads(json_str)
                except json.JSONDecodeError:
                    json_data = None

            return {
                "returncode": result.returncode,
                "stdout": result.stdout,
                "stderr": result.stderr,
                "json": json_data
            }

        except subprocess.TimeoutExpired:
            return {
                "returncode": 124,
                "stdout": "",
                "stderr": "Command timed out",
                "json": None
            }
        except Exception as e:
            return {
                "returncode": -1,
                "stdout": "",
                "stderr": str(e),
                "json": None
            }

    return run_command


@pytest.fixture(scope="session")
def test_email_id(cli_runner, search_query, today_minus_n_days, min_results):
    """
    Fixture that provides a message ID from test emails.

    This fixture:
    1. Requires test config for the active profile
    2. Searches for emails matching the profile's search query
    3. Returns the first message ID for use in other tests
    4. Caches the result for the entire test session

    Returns:
        str: Gmail message ID to use in subsequent tests
    """
    full_query = f'{search_query} after:{today_minus_n_days}'
    result = cli_runner(["mail", "search", full_query])

    if result["returncode"] != 0:
        pytest.fail(
            f"Failed to search for test emails.\n"
            f"Query: {full_query}\n"
            f"Error: {result['stderr']}"
        )

    if result["json"] is None:
        pytest.fail(f"Invalid JSON response from search: {result['stdout']}")

    if not isinstance(result["json"], list) or len(result["json"]) < min_results:
        pytest.fail(
            f"Insufficient test data found.\n"
            f"Expected at least {min_results} emails matching:\n"
            f"  {search_query}\n"
            f"Found: {len(result['json']) if result['json'] else 0}\n"
            f"Adjust search_query in test-config.yaml for this profile."
        )

    return result["json"][0]["id"]


# Session-level marker definitions
def pytest_configure(config):
    """Register custom pytest markers."""
    config.addinivalue_line(
        "markers", "integration: mark test as an integration test"
    )
    config.addinivalue_line(
        "markers", "requires_email: mark test as requiring test emails to be configured"
    )
