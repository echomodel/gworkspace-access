"""Tests for ``gwsa-admin accounts ...``.

In-process via ``CliRunner``. Each test isolates HOME / XDG / users path
via ``monkeypatch`` + ``tmp_path``; nothing touches real config.

The full path is exercised: Click parsing → mcp-app store routing →
FilesystemUserDataStore → typed Profile/GoogleAccount roundtrip on disk.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from click.testing import CliRunner

from gwsa import app


GCLOUD_CLIENT_ID = (
    "764086051850-6qr4p6gpi6hn506pt8ejuq83di341hur"
    + ".apps.googleusercontent.com"
)


@pytest.fixture(autouse=True)
def isolate_paths(tmp_path, monkeypatch):
    """Redirect every writable path away from the real filesystem."""
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    monkeypatch.setenv("APP_USERS_PATH", str(tmp_path / "users"))
    for p in [tmp_path / "home", tmp_path / "config",
              tmp_path / "data", tmp_path / "users"]:
        p.mkdir(parents=True, exist_ok=True)


@pytest.fixture
def runner():
    return CliRunner()


@pytest.fixture
def connected(runner):
    """Run ``connect local`` so subcommands know where the store lives."""
    result = runner.invoke(app.admin_cli, ["connect", "local"])
    assert result.exit_code == 0, result.stderr
    return runner


def _token_file(tmp_path: Path, filename: str = "token.json",
                refresh_token: str = "test-refresh",
                client_id: str = "user-owned-client",
                quota_project: str | None = None) -> Path:
    path = tmp_path / filename
    blob = {
        "client_id": client_id,
        "client_secret": "test-secret",
        "refresh_token": refresh_token,
        "token_uri": "https://oauth2.googleapis.com/token",
    }
    if quota_project:
        blob["quota_project_id"] = quota_project
    path.write_text(json.dumps(blob))
    return path


def test_add_first_account_auto_creates_user(connected, tmp_path):
    token_path = _token_file(tmp_path)

    result = connected.invoke(app.admin_cli, [
        "accounts", "add", "personal",
        "--email", "alice@example.com",
        "--token", f"@{token_path}",
    ])

    assert result.exit_code == 0, result.stderr
    assert "auto-created user record for alice@example.com" in result.stdout
    assert "set as default account" in result.stdout

    list_users = connected.invoke(app.admin_cli, ["users", "list"])
    assert "alice@example.com" in list_users.stdout


def test_add_second_account_inherits_existing_user(connected, tmp_path):
    token1 = _token_file(tmp_path, filename="t1.json")
    connected.invoke(app.admin_cli, [
        "accounts", "add", "personal",
        "--email", "alice@example.com",
        "--token", f"@{token1}",
    ])

    token2 = _token_file(tmp_path, filename="t2.json", refresh_token="second-refresh")
    result = connected.invoke(app.admin_cli, [
        "accounts", "add", "work",
        "--email", "alice-work@example.org",
        "--token", f"@{token2}",
    ])

    assert result.exit_code == 0, result.stderr
    assert "Added account 'work'" in result.stdout
    assert "set as default" not in result.stdout


def test_gcloud_issued_token_requires_quota_project(connected, tmp_path):
    token_path = _token_file(tmp_path, client_id=GCLOUD_CLIENT_ID)

    result = connected.invoke(app.admin_cli, [
        "accounts", "add", "personal",
        "--email", "alice@example.com",
        "--token", f"@{token_path}",
    ])

    assert result.exit_code != 0
    assert "gcloud" in result.stderr.lower()
    assert "--quota-project" in result.stderr


def test_gcloud_issued_token_accepts_quota_project_from_blob(connected, tmp_path):
    token_path = _token_file(
        tmp_path,
        client_id=GCLOUD_CLIENT_ID,
        quota_project="example-project",
    )

    result = connected.invoke(app.admin_cli, [
        "accounts", "add", "personal",
        "--email", "alice@example.com",
        "--token", f"@{token_path}",
    ])

    assert result.exit_code == 0, result.stderr
    list_result = connected.invoke(app.admin_cli, ["accounts", "list"])
    assert "quota=example-project" in list_result.stdout
    assert "[gcloud]" in list_result.stdout


def test_quota_project_flag_overrides_blob(connected, tmp_path):
    token_path = _token_file(
        tmp_path,
        client_id=GCLOUD_CLIENT_ID,
        quota_project="blob-project",
    )

    connected.invoke(app.admin_cli, [
        "accounts", "add", "personal",
        "--email", "alice@example.com",
        "--quota-project", "flag-project",
        "--token", f"@{token_path}",
    ])

    list_result = connected.invoke(app.admin_cli, ["accounts", "list"])
    assert "quota=flag-project" in list_result.stdout
    assert "blob-project" not in list_result.stdout


def test_stdin_token_is_read(connected):
    token_blob = json.dumps({
        "client_id": "user-owned-client",
        "client_secret": "test-secret",
        "refresh_token": "from-stdin",
        "token_uri": "https://oauth2.googleapis.com/token",
    })

    result = connected.invoke(
        app.admin_cli,
        ["accounts", "add", "personal", "--email", "alice@example.com", "--token", "-"],
        input=token_blob,
    )
    assert result.exit_code == 0, result.stderr

    get_result = connected.invoke(
        app.admin_cli, ["accounts", "get", "personal", "--show-token"]
    )
    assert "from-stdin" in get_result.stdout


def test_list_shows_accounts_with_default_marker(connected, tmp_path):
    t1 = _token_file(tmp_path, filename="t1.json")
    t2 = _token_file(tmp_path, filename="t2.json",
                     client_id=GCLOUD_CLIENT_ID, quota_project="example-project")

    connected.invoke(app.admin_cli, [
        "accounts", "add", "personal",
        "--email", "alice@example.com", "--token", f"@{t1}",
    ])
    connected.invoke(app.admin_cli, [
        "accounts", "add", "work",
        "--email", "alice-work@example.org", "--token", f"@{t2}",
    ])

    result = connected.invoke(app.admin_cli, ["accounts", "list"])
    assert result.exit_code == 0, result.stderr
    assert "personal (default) — alice@example.com" in result.stdout
    assert "work — alice-work@example.org [gcloud] quota=example-project" in result.stdout


def test_use_changes_default(connected, tmp_path):
    t1 = _token_file(tmp_path, filename="t1.json")
    t2 = _token_file(tmp_path, filename="t2.json")
    connected.invoke(app.admin_cli, [
        "accounts", "add", "personal",
        "--email", "alice@example.com", "--token", f"@{t1}",
    ])
    connected.invoke(app.admin_cli, [
        "accounts", "add", "work",
        "--email", "alice-work@example.org", "--token", f"@{t2}",
    ])

    result = connected.invoke(app.admin_cli, ["accounts", "use", "work"])
    assert result.exit_code == 0, result.stderr
    assert "now 'work'" in result.stdout

    list_result = connected.invoke(app.admin_cli, ["accounts", "list"])
    assert "work (default)" in list_result.stdout
    assert "personal —" in list_result.stdout


def test_remove_promotes_sole_remaining_account_to_default(connected, tmp_path):
    t1 = _token_file(tmp_path, filename="t1.json")
    t2 = _token_file(tmp_path, filename="t2.json")
    connected.invoke(app.admin_cli, [
        "accounts", "add", "personal",
        "--email", "alice@example.com", "--token", f"@{t1}",
    ])
    connected.invoke(app.admin_cli, [
        "accounts", "add", "work",
        "--email", "alice-work@example.org", "--token", f"@{t2}",
    ])

    result = connected.invoke(app.admin_cli, ["accounts", "remove", "personal"])
    assert result.exit_code == 0, result.stderr
    assert "new default: work" in result.stdout


def test_get_hides_token_by_default(connected, tmp_path):
    token_path = _token_file(tmp_path)
    connected.invoke(app.admin_cli, [
        "accounts", "add", "personal",
        "--email", "alice@example.com", "--token", f"@{token_path}",
    ])

    result = connected.invoke(app.admin_cli, ["accounts", "get", "personal"])
    assert result.exit_code == 0, result.stderr
    assert "hidden" in result.stdout
    assert "test-refresh" not in result.stdout

    result = connected.invoke(
        app.admin_cli, ["accounts", "get", "personal", "--show-token"]
    )
    assert "test-refresh" in result.stdout


def test_add_with_explicit_user_must_exist(connected, tmp_path):
    token_path = _token_file(tmp_path)

    result = connected.invoke(app.admin_cli, [
        "accounts", "add", "personal",
        "--user", "ghost@example.com",
        "--email", "alice@example.com",
        "--token", f"@{token_path}",
    ])

    assert result.exit_code != 0
    assert "User not found" in result.stderr


def test_read_command_with_no_users_gives_actionable_error(connected):
    result = connected.invoke(app.admin_cli, ["accounts", "list"])
    assert result.exit_code != 0
    assert "No users registered" in result.stderr
    assert "gwsa-admin accounts add" in result.stderr


def test_duplicate_account_name_rejected(connected, tmp_path):
    token_path = _token_file(tmp_path)
    connected.invoke(app.admin_cli, [
        "accounts", "add", "personal",
        "--email", "alice@example.com", "--token", f"@{token_path}",
    ])

    result = connected.invoke(app.admin_cli, [
        "accounts", "add", "personal",
        "--email", "alice@example.com", "--token", f"@{token_path}",
    ])

    assert result.exit_code != 0
    assert "already exists" in result.stderr
