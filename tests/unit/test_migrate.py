"""Tests for ``gwsa-admin migrate``.

In-process via ``CliRunner`` against a synthetic legacy vault under an
isolated ``GWSA_CONFIG_DIR``. No subprocesses; no real filesystem touch.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml
from click.testing import CliRunner

from gwsa import app


@pytest.fixture(autouse=True)
def isolate_paths(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    monkeypatch.setenv("APP_USERS_PATH", str(tmp_path / "users"))
    # GWSA_CONFIG_DIR points at the legacy pre-mcp-app vault that
    # `migrate` reads.
    monkeypatch.setenv("GWSA_CONFIG_DIR", str(tmp_path / "gwsa-legacy"))
    for p in [tmp_path / "home", tmp_path / "config", tmp_path / "data",
              tmp_path / "users", tmp_path / "gwsa-legacy"]:
        p.mkdir(parents=True, exist_ok=True)


@pytest.fixture
def runner():
    return CliRunner()


@pytest.fixture
def connected(runner):
    result = runner.invoke(app.admin_cli, ["connect", "local"])
    assert result.exit_code == 0, result.stderr
    return runner


def _make_legacy_profile(tmp_path: Path, name: str, email: str,
                         refresh_token: str = "legacy-refresh",
                         quota_project: str | None = None,
                         scopes: list[str] | None = None,
                         active: bool = False):
    """Write a fake legacy profile mirroring gwsa.sdk.profiles' on-disk shape."""
    vault_root = tmp_path / "gwsa-legacy"
    profile_dir = vault_root / "profiles" / name
    profile_dir.mkdir(parents=True, exist_ok=True)

    blob = {
        "client_id": "user-owned-client",
        "client_secret": "test-secret",
        "refresh_token": refresh_token,
        "token_uri": "https://oauth2.googleapis.com/token",
    }
    if quota_project:
        blob["quota_project_id"] = quota_project
    (profile_dir / "user_token.json").write_text(json.dumps(blob))

    metadata = {
        "created": "2024-01-01T00:00:00",
        "type": "oauth",
        "email": email,
    }
    if scopes:
        metadata["validated_scopes"] = scopes
        metadata["last_validated"] = "2024-01-15T12:00:00"
    (profile_dir / "profile.yaml").write_text(yaml.safe_dump(metadata))

    if active:
        config_path = vault_root / "config.yaml"
        config_path.write_text(yaml.safe_dump({"active_profile": name}))


def test_no_legacy_profiles_is_noop(connected):
    result = connected.invoke(app.admin_cli, ["migrate"])
    assert result.exit_code == 0, result.stderr
    assert "Nothing to migrate" in result.stdout


def test_single_active_profile_round_trips(connected, tmp_path):
    _make_legacy_profile(tmp_path, "personal", "alice@example.com",
                         scopes=["https://www.googleapis.com/auth/gmail.modify"],
                         active=True)

    result = connected.invoke(app.admin_cli, ["migrate"])
    assert result.exit_code == 0, result.stderr
    assert "Migrated 1 legacy profile(s) into user 'local'" in result.stdout

    list_users = connected.invoke(app.admin_cli, ["users", "list"])
    assert "local" in list_users.stdout

    list_accounts = connected.invoke(app.admin_cli, ["accounts", "list"])
    assert "personal (default) — alice@example.com" in list_accounts.stdout


def test_multiple_profiles_use_active_for_default(connected, tmp_path):
    _make_legacy_profile(tmp_path, "personal", "alice@example.com")
    _make_legacy_profile(tmp_path, "work", "alice-work@example.org",
                         quota_project="example-project",
                         active=True)

    result = connected.invoke(app.admin_cli, ["migrate"])
    assert result.exit_code == 0, result.stderr
    assert "into user 'local'" in result.stdout

    list_accounts = connected.invoke(
        app.admin_cli, ["accounts", "list", "--user", "local"]
    )
    assert "work (default) — alice-work@example.org" in list_accounts.stdout
    assert "personal — alice@example.com" in list_accounts.stdout


def test_explicit_user_key_overrides_default(connected, tmp_path):
    _make_legacy_profile(tmp_path, "personal", "alice@example.com", active=True)

    result = connected.invoke(
        app.admin_cli, ["migrate", "--user-key", "alt-handle"]
    )
    assert result.exit_code == 0, result.stderr
    assert "into user 'alt-handle'" in result.stdout


def test_dry_run_writes_nothing(connected, tmp_path):
    _make_legacy_profile(tmp_path, "personal", "alice@example.com", active=True)

    result = connected.invoke(app.admin_cli, ["migrate", "--dry-run"])
    assert result.exit_code == 0, result.stderr
    assert "Would create user: local" in result.stdout

    list_users = connected.invoke(app.admin_cli, ["users", "list"])
    assert "local" not in list_users.stdout


def test_refuses_to_overwrite_existing_user(connected, tmp_path):
    _make_legacy_profile(tmp_path, "personal", "alice@example.com", active=True)
    connected.invoke(app.admin_cli, ["migrate"])

    result = connected.invoke(app.admin_cli, ["migrate"])
    assert result.exit_code != 0
    assert "already exists" in result.stderr


def test_skip_broken_skips_profiles_without_email(connected, tmp_path):
    _make_legacy_profile(tmp_path, "good", "alice@example.com", active=True)
    broken_dir = tmp_path / "gwsa-legacy" / "profiles" / "broken"
    broken_dir.mkdir(parents=True, exist_ok=True)
    (broken_dir / "user_token.json").write_text(json.dumps({
        "client_id": "x", "client_secret": "y",
        "refresh_token": "z", "token_uri": "https://oauth2.googleapis.com/token",
    }))
    (broken_dir / "profile.yaml").write_text(yaml.safe_dump({"type": "oauth"}))

    result = connected.invoke(app.admin_cli, ["migrate", "--skip-broken"])
    assert result.exit_code == 0, result.stderr
    assert "skipped: broken" in result.stderr
    assert "Migrated 1 legacy profile(s)" in result.stdout


def test_carries_quota_project_from_blob(connected, tmp_path):
    _make_legacy_profile(tmp_path, "personal", "alice@example.com",
                         quota_project="example-project",
                         active=True)

    connected.invoke(app.admin_cli, ["migrate"])
    list_accounts = connected.invoke(app.admin_cli, ["accounts", "list"])
    assert "quota=example-project" in list_accounts.stdout


def test_leaves_legacy_vault_in_place(connected, tmp_path):
    _make_legacy_profile(tmp_path, "personal", "alice@example.com", active=True)

    legacy_path = tmp_path / "gwsa-legacy" / "profiles" / "personal"
    assert legacy_path.exists()

    connected.invoke(app.admin_cli, ["migrate"])

    assert legacy_path.exists()
    assert (legacy_path / "user_token.json").exists()
