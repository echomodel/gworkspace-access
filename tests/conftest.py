"""
Test configuration and fixtures for gwsa integration tests.

This module provides:
- CLI installation verification
- Shared fixtures for test data and utilities
- Session-level setup/teardown
- Configuration loading from tests/config.yaml
"""

import sys
import pytest
import subprocess
import json
import os
import yaml
from datetime import datetime, timedelta
from typing import Dict, Any, List


# Load test configuration
def load_test_config() -> Dict[str, Any]:
    """Load test configuration from tests/config.yaml"""
    config_path = os.path.join(
        os.path.dirname(__file__),
        "config.yaml"
    )
    with open(config_path, 'r') as f:
        return yaml.safe_load(f)


TEST_CONFIG = load_test_config()


@pytest.fixture(scope="session", autouse=True)
def verify_cli_installed():
    """
    Verify that gwsa CLI is properly installed from the current codebase.

    This fixture:
    1. Runs 'python -m gwsa_cli --help' to verify current code is being tested
    2. Ensures the test environment uses the latest code, not a cached/installed version
    3. Exits with error if CLI is not available

    This is autouse=True so it runs before any tests execute.
    """
    try:
        result = subprocess.run(
            [sys.executable, "-m", "gwsa_cli", "--help"],
            capture_output=True,
            text=True,
            timeout=5,
            cwd=os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        )

        if result.returncode != 0:
            pytest.fail(
                f"gwsa CLI not properly installed. "
                f"Ensure 'pip install -e .' has been run in the project root.\n"
                f"Error: {result.stderr}"
            )

        if "Gmail Workspace Assistant" not in result.stdout:
            pytest.fail(
                "gwsa CLI found but output unexpected. "
                "This may indicate an outdated installed version. "
                "Run 'pip install -e .' to use the current codebase."
            )

    except FileNotFoundError:
        pytest.fail(
            "Python 3 not found in PATH. "
            "Ensure Python 3 is installed and available as 'python3'."
        )
    except subprocess.TimeoutExpired:
        pytest.fail("CLI help command timed out. Check for hanging processes.")
    except Exception as e:
        pytest.fail(f"Unexpected error verifying CLI installation: {e}")


@pytest.fixture(scope="session")
def today_minus_60_days() -> str:
    """
    Calculate the date N days ago (configurable) in YYYY-MM-DD format.

    Uses the days_range from tests/config.yaml.

    Returns:
        str: Date string in format 'YYYY-MM-DD'
    """
    days_range = TEST_CONFIG.get('search', {}).get('days_range', 60)
    date_n_days_ago = datetime.now() - timedelta(days=days_range)
    return date_n_days_ago.strftime("%Y-%m-%d")


@pytest.fixture(scope="session")
def cli_runner():
    """
    Factory fixture that executes CLI commands via subprocess.

    Returns:
        Callable: Function that takes command args and returns parsed result

    The returned function signature:
        cli_runner(command_args: List[str]) -> Dict[str, Any]

    Returns dict with:
        - returncode: int (0 for success)
        - stdout: str (raw output)
        - stderr: str (error output)
        - json: dict or list (parsed JSON if stdout is valid JSON, None otherwise)

    Usage:
        result = cli_runner(["mail", "search", "query"])
        messages = result["json"]  # Pre-parsed JSON
        assert result["returncode"] == 0
    """
    project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

    def run_command(command_args: List[str]) -> Dict[str, Any]:
        """Execute a gwsa CLI command and return parsed result."""
        try:
            result = subprocess.run(
                [sys.executable, "-m", "gwsa_cli"] + command_args,
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
                        if line.strip() and not line[0].isdigit()  # Skip timestamp logs
                    ]
                    json_str = "\n".join(json_lines)
                    json_data = json.loads(json_str)
                except json.JSONDecodeError:
                    # Output is not JSON, that's okay
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
def test_email_id(cli_runner, today_minus_60_days):
    """
    Fixture that provides a message ID from test data.

    This fixture:
    1. Searches for emails matching the query in tests/config.yaml
    2. Extracts the first message ID for use in other tests
    3. Fails with a clear message if insufficient test data exists
    4. Caches the result for the entire test session

    Returns:
        str: Gmail message ID to use in subsequent tests

    Requires:
        - Emails matching the search query in tests/config.yaml
        - 'gwsa setup' to have been run previously

    Used by:
        - test_mail_modify.py (for label apply/remove tests)
        - test_mail_read.py (for message reading tests)
    """
    base_query = TEST_CONFIG.get('search', {}).get('query', '')
    search_query = f'{base_query} after:{today_minus_60_days}'
    result = cli_runner(["mail", "search", search_query])

    # Verify search succeeded
    if result["returncode"] != 0:
        pytest.fail(
            f"Failed to search for test emails.\n"
            f"Error: {result['stderr']}\n"
            f"Make sure 'gwsa setup' has been run."
        )

    # Verify we got JSON results
    if result["json"] is None:
        pytest.fail(
            f"Invalid JSON response from search: {result['stdout']}"
        )

    # Verify we have test data
    min_results = TEST_CONFIG.get('test_data', {}).get('min_results', 2)
    if not isinstance(result["json"], list) or len(result["json"]) < min_results:
        search_query_config = TEST_CONFIG.get('search', {}).get('query', 'not configured')
        pytest.fail(
            f"Insufficient test data found in mailbox.\n"
            f"Expected at least {min_results} emails matching search criteria.\n"
            f"Search query: {search_query_config}\n"
            f"Update tests/config.yaml with a search query that matches your test data."
        )

    # Extract message ID
    message_id = result["json"][0]["id"]

    return message_id


# Session-level marker definitions
def pytest_configure(config):
    """Register custom pytest markers."""
    config.addinivalue_line(
        "markers", "integration: mark test as an integration test"
    )
    config.addinivalue_line(
        "markers", "order(N): order test execution (requires pytest-ordering)"
    )
