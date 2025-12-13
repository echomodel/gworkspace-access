"""
Unit tests for client CLI command validation.

Tests validation logic for client credentials management.
Uses Click's CliRunner with isolated filesystem.
"""

import json
import os
from pathlib import Path
import pytest
from click.testing import CliRunner

from gwsa.cli.__main__ import gwsa


@pytest.fixture
def isolated_config(tmp_path, monkeypatch):
    """
    Create an isolated config directory with mocked paths.

    Returns a dict with paths and helper functions.
    """
    config_dir = tmp_path / "config"
    config_dir.mkdir()

    client_secrets = config_dir / "client_secrets.json"

    # Patch the module constant
    monkeypatch.setattr("gwsa.cli.setup_local.CLIENT_SECRETS_FILE", str(client_secrets))
    monkeypatch.setattr("gwsa.cli.client_commands.CLIENT_SECRETS_FILE", str(client_secrets))

    def create_client_secrets(client_id: str = "test_client_id"):
        """Helper to create valid client secrets file."""
        secrets = {
            "installed": {
                "client_id": client_id,
                "project_id": "test-project",
                "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                "token_uri": "https://oauth2.googleapis.com/token",
                "client_secret": "test_secret_value",
                "redirect_uris": ["http://localhost"]
            }
        }
        with open(client_secrets, "w") as f:
            json.dump(secrets, f)

    return {
        "config_dir": config_dir,
        "client_secrets": client_secrets,
        "create_client_secrets": create_client_secrets,
    }


class TestClientShow:
    """Tests for 'gwsa client show' command."""

    def test_show_no_credentials_configured(self, isolated_config):
        """Show should indicate when no credentials are configured."""
        # Don't create client_secrets.json

        runner = CliRunner()
        result = runner.invoke(gwsa, ["client", "show"])

        assert result.exit_code == 1
        assert "no client credentials" in result.output.lower()

    def test_show_displays_client_id(self, isolated_config):
        """Show should display the client ID."""
        isolated_config["create_client_secrets"]("my_test_client_id")

        runner = CliRunner()
        result = runner.invoke(gwsa, ["client", "show"])

        assert result.exit_code == 0
        assert "my_test_client_id" in result.output

    def test_show_hides_client_secret(self, isolated_config):
        """Show should NOT display the actual client secret."""
        isolated_config["create_client_secrets"]()

        runner = CliRunner()
        result = runner.invoke(gwsa, ["client", "show"])

        assert result.exit_code == 0
        # Should NOT contain the actual secret
        assert "test_secret_value" not in result.output
        # Should show hash indicator instead
        assert "hash:" in result.output.lower() or "configured" in result.output.lower()


class TestClientImport:
    """Tests for 'gwsa client import' command."""

    def test_import_nonexistent_file_rejected(self, isolated_config):
        """Importing a file that doesn't exist should fail."""
        runner = CliRunner()
        result = runner.invoke(gwsa, ["client", "import", "/nonexistent/path.json"])

        assert result.exit_code != 0
        assert "does not exist" in result.output.lower() or "error" in result.output.lower()

    def test_import_invalid_json_rejected(self, isolated_config, tmp_path):
        """Importing invalid JSON should fail."""
        bad_file = tmp_path / "bad.json"
        bad_file.write_text("{ invalid json }")

        runner = CliRunner()
        result = runner.invoke(gwsa, ["client", "import", str(bad_file)])

        assert result.exit_code == 1
        assert "invalid" in result.output.lower() or "json" in result.output.lower()

    def test_import_wrong_format_rejected(self, isolated_config, tmp_path):
        """Importing JSON without 'installed' or 'web' key should fail."""
        bad_file = tmp_path / "wrong_format.json"
        bad_file.write_text('{"wrong": "format"}')

        runner = CliRunner()
        result = runner.invoke(gwsa, ["client", "import", str(bad_file)])

        assert result.exit_code == 1
        assert "invalid" in result.output.lower() or "format" in result.output.lower()

    def test_import_valid_file_succeeds(self, isolated_config, tmp_path):
        """Importing a valid client secrets file should succeed."""
        valid_file = tmp_path / "valid_secrets.json"
        secrets = {
            "installed": {
                "client_id": "imported_client_id",
                "project_id": "test-project",
                "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                "token_uri": "https://oauth2.googleapis.com/token",
                "client_secret": "imported_secret",
                "redirect_uris": ["http://localhost"]
            }
        }
        valid_file.write_text(json.dumps(secrets))

        runner = CliRunner()
        result = runner.invoke(gwsa, ["client", "import", str(valid_file)])

        assert result.exit_code == 0
        assert "success" in result.output.lower() or "imported" in result.output.lower()

        # Verify file was copied
        assert isolated_config["client_secrets"].exists()
        with open(isolated_config["client_secrets"]) as f:
            copied = json.load(f)
        assert copied["installed"]["client_id"] == "imported_client_id"

    def test_import_web_app_format_succeeds(self, isolated_config, tmp_path):
        """Importing web app credentials (not just desktop) should succeed."""
        valid_file = tmp_path / "web_secrets.json"
        secrets = {
            "web": {
                "client_id": "web_client_id",
                "project_id": "test-project",
                "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                "token_uri": "https://oauth2.googleapis.com/token",
                "client_secret": "web_secret",
                "redirect_uris": ["http://localhost"]
            }
        }
        valid_file.write_text(json.dumps(secrets))

        runner = CliRunner()
        result = runner.invoke(gwsa, ["client", "import", str(valid_file)])

        assert result.exit_code == 0
        assert "success" in result.output.lower() or "imported" in result.output.lower()
