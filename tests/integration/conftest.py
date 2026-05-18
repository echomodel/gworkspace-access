"""Integration-suite fixtures.

These fire only when ``pytest tests/integration/`` is invoked
explicitly (the default ``pytest`` ignores this directory per
``pyproject.toml``). They bootstrap the mcp-app ``current_user``
ContextVar from the local user store — same pattern as the gwsa
CLI in ``gwsa.cli.__main__`` — so every SDK call resolves
credentials through the same single-user identity for the session.

Per-account test settings live in ``tests/test-config.yaml``, keyed
by account name (as shown by ``gwsa-admin accounts list``).
"""

import asyncio
import json
import os
import subprocess
import sys
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional

import pytest
import yaml


TEST_CONFIG_FILE = Path(__file__).parent.parent / "test-config.yaml"

EXAMPLE_SEARCH_QUERY = 'subject:"Your Daily Digest" from:"USPS Informed Delivery"'


def load_test_config() -> Dict[str, Any]:
    if not TEST_CONFIG_FILE.exists():
        return {"accounts": {}}
    with open(TEST_CONFIG_FILE) as f:
        return yaml.safe_load(f) or {"accounts": {}}


def _bootstrap_current_user() -> Optional[str]:
    """Load the local user into ``current_user`` and return the
    selected account name. Returns None if no usable account.
    """
    from mcp_app.bridge import DataStoreAuthAdapter
    from mcp_app.context import current_user, hydrate_profile

    from gwsa import app

    store = app._build_store()
    users = store.list_users()
    if not users:
        return None
    if len(users) > 1:
        explicit = os.environ.get("GWSA_TEST_USER")
        if not explicit or explicit not in users:
            pytest.exit(
                f"Local store has multiple users ({', '.join(users)}); "
                f"set GWSA_TEST_USER to disambiguate.",
                returncode=1,
            )
        email = explicit
    else:
        email = users[0]

    adapter = DataStoreAuthAdapter(store)
    user_record = asyncio.run(adapter.get_full(email))
    if user_record is None:
        return None
    user_record.profile = hydrate_profile(user_record.profile)
    current_user.set(user_record)

    profile = user_record.profile
    accounts = getattr(profile, "accounts", None) or []
    if not accounts:
        return None
    default_name = getattr(profile, "default_account", None)
    chosen = next(
        (a for a in accounts if a.name == default_name),
        accounts[0],
    )
    return chosen.name


_profile_error_printed = False
_config_instructions_printed = False


@pytest.fixture(scope="session", autouse=True)
def validate_test_environment():
    global _profile_error_printed

    account_name = _bootstrap_current_user()
    if account_name is None:
        if not _profile_error_printed:
            print("\n" + "=" * 70)
            print("GWSA INTEGRATION TESTS — NO USABLE USER CONFIGURED")
            print("=" * 70)
            print("Register a user with:")
            print("  gwsa-admin connect local")
            print("  gwsa-admin accounts add <name> --email <you@example.com> --token=...")
            print("=" * 70 + "\n")
            _profile_error_printed = True
        pytest.exit("gwsa user not configured.", returncode=1)

    project_root = Path(__file__).parent.parent.parent
    try:
        result = subprocess.run(
            [sys.executable, "-m", "gwsa.cli", "--help"],
            capture_output=True,
            text=True,
            timeout=5,
            cwd=project_root,
        )
        if result.returncode != 0:
            pytest.exit(
                f"gwsa CLI not properly installed. Run 'pip install -e .' first.\n"
                f"Error: {result.stderr}",
                returncode=1,
            )
    except Exception as e:
        pytest.exit(f"Failed to verify CLI installation: {e}", returncode=1)

    print(f"\n✓ Active account: {account_name}")

    test_settings = load_test_config().get("accounts", {}).get(account_name)
    if test_settings:
        print(f"✓ Test config: found settings for '{account_name}'")
    else:
        print(f"⚠ Test config: no settings for '{account_name}' (some tests will skip)")

    yield


@pytest.fixture(scope="session")
def active_account_name() -> Optional[str]:
    from mcp_app.context import current_user

    user = current_user.get()
    profile = user.profile
    accounts = getattr(profile, "accounts", None) or []
    if not accounts:
        return None
    default_name = getattr(profile, "default_account", None)
    chosen = next(
        (a for a in accounts if a.name == default_name),
        accounts[0],
    )
    return chosen.name


@pytest.fixture(scope="session")
def test_config(active_account_name) -> Optional[Dict[str, Any]]:
    return load_test_config().get("accounts", {}).get(active_account_name)


@pytest.fixture(scope="session")
def require_test_config(active_account_name, test_config):
    global _config_instructions_printed
    if test_config is None:
        if not _config_instructions_printed:
            print("\n" + "=" * 70)
            print("GWSA INTEGRATION TEST CONFIGURATION REQUIRED")
            print("=" * 70)
            print(f"\nActive account: {active_account_name}")
            print(f"No test settings found in: {TEST_CONFIG_FILE}\n")
            print("Add an entry:")
            print("  accounts:")
            print(f"    {active_account_name}:")
            print(f"      search_query: '{EXAMPLE_SEARCH_QUERY}'")
            print("      test_label: \"Test\"")
            print("      min_results: 2")
            print("      days_range: 60")
            print("=" * 70 + "\n")
            _config_instructions_printed = True
        pytest.skip(f"No test config for account '{active_account_name}'")
    return test_config


@pytest.fixture(scope="session")
def search_query(require_test_config) -> str:
    query = require_test_config.get("search_query")
    if not query:
        pytest.skip("No search_query configured for this account")
    return query


@pytest.fixture(scope="session")
def test_label(require_test_config) -> str:
    return require_test_config.get("test_label", "Test")


@pytest.fixture(scope="session")
def min_results(require_test_config) -> int:
    return require_test_config.get("min_results", 2)


@pytest.fixture(scope="session")
def days_range(require_test_config) -> int:
    return require_test_config.get("days_range", 60)


@pytest.fixture(scope="session")
def today_minus_n_days(days_range) -> str:
    return (datetime.now() - timedelta(days=days_range)).strftime("%Y-%m-%d")


@pytest.fixture(scope="session")
def cli_runner():
    project_root = Path(__file__).parent.parent.parent

    def run_command(command_args: List[str]) -> Dict[str, Any]:
        try:
            result = subprocess.run(
                [sys.executable, "-m", "gwsa.cli", *command_args],
                capture_output=True,
                text=True,
                timeout=30,
                cwd=project_root,
            )
            json_data = None
            if result.stdout.strip():
                try:
                    json_lines = [
                        line for line in result.stdout.split("\n")
                        if line.strip() and not line[0].isdigit()
                    ]
                    json_data = json.loads("\n".join(json_lines))
                except json.JSONDecodeError:
                    json_data = None
            return {
                "returncode": result.returncode,
                "stdout": result.stdout,
                "stderr": result.stderr,
                "json": json_data,
            }
        except subprocess.TimeoutExpired:
            return {"returncode": 124, "stdout": "", "stderr": "Command timed out", "json": None}
        except Exception as e:
            return {"returncode": -1, "stdout": "", "stderr": str(e), "json": None}

    return run_command


@pytest.fixture(scope="session")
def test_email_id(cli_runner, search_query, today_minus_n_days, min_results):
    full_query = f"{search_query} after:{today_minus_n_days}"
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
            f"Expected at least {min_results} emails matching:\n  {search_query}\n"
            f"Found: {len(result['json']) if result['json'] else 0}\n"
            f"Adjust search_query in test-config.yaml for this account."
        )
    return result["json"][0]["id"]
