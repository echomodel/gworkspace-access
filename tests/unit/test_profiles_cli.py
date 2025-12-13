"""
Unit tests for profiles CLI command validation.

Tests validation logic without requiring real OAuth flows or network calls.
Uses Click's CliRunner with isolated filesystem and mocked profile state.
"""

import json
import os
from pathlib import Path
import pytest
import yaml
from click.testing import CliRunner
from unittest.mock import patch, MagicMock

from gwsa.cli.__main__ import gwsa


@pytest.fixture
def isolated_config(tmp_path, monkeypatch):
    """
    Create an isolated config directory with mocked paths.

    Returns a dict with paths and helper functions for setting up test state.
    """
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    profiles_dir = config_dir / "profiles"
    profiles_dir.mkdir()

    config_file = config_dir / "config.yaml"
    client_secrets = config_dir / "client_secrets.json"

    # Use environment variables to redirect config paths
    monkeypatch.setenv("GWSA_CONFIG_DIR", str(config_dir))
    monkeypatch.setenv("GWSA_CONFIG_FILE", str(config_file))

    # Also patch setup_local constants for client_secrets
    monkeypatch.setattr("gwsa.cli.setup_local.CLIENT_SECRETS_FILE", str(client_secrets))
    monkeypatch.setattr("gwsa.cli.client_commands.CLIENT_SECRETS_FILE", str(client_secrets))

    def create_profile(name: str, email: str = "test@example.com", valid: bool = True):
        """Helper to create a mock profile."""
        profile_dir = profiles_dir / name
        profile_dir.mkdir(exist_ok=True)

        # Create profile.yaml
        profile_yaml = {
            "email": email,
            "validated_scopes": ["https://www.googleapis.com/auth/gmail.modify"],
            "last_validated": "2025-01-01T00:00:00" if valid else None,
        }
        with open(profile_dir / "profile.yaml", "w") as f:
            yaml.dump(profile_yaml, f)

        # Create token file
        token = {"token": "fake_token", "refresh_token": "fake_refresh"}
        with open(profile_dir / "user_token.json", "w") as f:
            json.dump(token, f)

    def set_active_profile(name: str):
        """Helper to set active profile in config."""
        with open(config_file, "w") as f:
            yaml.dump({"active_profile": name}, f)

    def create_client_secrets():
        """Helper to create valid client secrets file."""
        secrets = {
            "installed": {
                "client_id": "test_client_id",
                "project_id": "test-project",
                "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                "token_uri": "https://oauth2.googleapis.com/token",
                "client_secret": "test_secret",
                "redirect_uris": ["http://localhost"]
            }
        }
        with open(client_secrets, "w") as f:
            json.dump(secrets, f)

    return {
        "config_dir": config_dir,
        "profiles_dir": profiles_dir,
        "config_file": config_file,
        "client_secrets": client_secrets,
        "create_profile": create_profile,
        "set_active_profile": set_active_profile,
        "create_client_secrets": create_client_secrets,
    }


class TestProfilesAdd:
    """Tests for 'gwsa profiles add' command validation."""

    def test_add_duplicate_profile_rejected(self, isolated_config):
        """Adding a profile that already exists should fail."""
        isolated_config["create_profile"]("existing")
        isolated_config["create_client_secrets"]()

        runner = CliRunner()
        result = runner.invoke(gwsa, ["profiles", "add", "existing"])

        assert result.exit_code == 1
        assert "already exists" in result.output.lower()

    def test_add_reserved_name_adc_rejected(self, isolated_config):
        """Adding profile named 'adc' should fail (reserved name)."""
        isolated_config["create_client_secrets"]()

        runner = CliRunner()
        result = runner.invoke(gwsa, ["profiles", "add", "adc"])

        assert result.exit_code == 1
        assert "built-in" in result.output.lower() or "adc" in result.output.lower()

    def test_add_without_client_secrets_rejected(self, isolated_config):
        """Adding profile without client secrets configured should fail."""
        # Don't create client_secrets.json

        runner = CliRunner()
        result = runner.invoke(gwsa, ["profiles", "add", "newprofile"])

        assert result.exit_code == 1
        assert "client" in result.output.lower()
        assert "import" in result.output.lower()


class TestProfilesRename:
    """Tests for 'gwsa profiles rename' command validation."""

    def test_rename_adc_rejected(self, isolated_config):
        """Renaming the built-in 'adc' profile should fail."""
        runner = CliRunner()
        result = runner.invoke(gwsa, ["profiles", "rename", "adc", "something"])

        assert result.exit_code == 1
        assert "cannot rename" in result.output.lower() or "built-in" in result.output.lower()

    def test_rename_to_adc_rejected(self, isolated_config):
        """Renaming any profile TO 'adc' should fail (reserved name)."""
        isolated_config["create_profile"]("myprofile")

        runner = CliRunner()
        result = runner.invoke(gwsa, ["profiles", "rename", "myprofile", "adc"])

        assert result.exit_code == 1
        assert "reserved" in result.output.lower() or "adc" in result.output.lower()

    def test_rename_nonexistent_rejected(self, isolated_config):
        """Renaming a profile that doesn't exist should fail."""
        runner = CliRunner()
        result = runner.invoke(gwsa, ["profiles", "rename", "nonexistent", "newname"])

        assert result.exit_code == 1
        assert "not found" in result.output.lower() or "does not exist" in result.output.lower()

    def test_rename_to_existing_rejected(self, isolated_config):
        """Renaming to a name that already exists should fail."""
        isolated_config["create_profile"]("source")
        isolated_config["create_profile"]("target")

        runner = CliRunner()
        result = runner.invoke(gwsa, ["profiles", "rename", "source", "target"])

        assert result.exit_code == 1
        assert "already exists" in result.output.lower()


class TestProfilesDelete:
    """Tests for 'gwsa profiles delete' command validation."""

    def test_delete_adc_rejected(self, isolated_config):
        """Deleting the built-in 'adc' profile should fail."""
        runner = CliRunner()
        result = runner.invoke(gwsa, ["profiles", "delete", "adc", "-y"])

        assert result.exit_code == 1
        assert "cannot delete" in result.output.lower() or "built-in" in result.output.lower()

    def test_delete_nonexistent_rejected(self, isolated_config):
        """Deleting a profile that doesn't exist should fail."""
        runner = CliRunner()
        result = runner.invoke(gwsa, ["profiles", "delete", "nonexistent", "-y"])

        assert result.exit_code == 1
        assert "not found" in result.output.lower()


class TestProfilesUse:
    """Tests for 'gwsa profiles use' command validation."""

    def test_use_nonexistent_rejected(self, isolated_config):
        """Switching to a profile that doesn't exist should fail."""
        runner = CliRunner()
        result = runner.invoke(gwsa, ["profiles", "use", "nonexistent"])

        assert result.exit_code == 1
        assert "not found" in result.output.lower()
