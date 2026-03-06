import pytest
import os
import json
from pathlib import Path
from unittest.mock import patch, MagicMock

from gwsa.sdk.profiles import (
    create_profile,
    get_profile_metadata_path,
    get_profile_token_path,
    get_profile_dir,
    ProfileType,
    profile_exists,
    delete_profile
)

@pytest.fixture
def mock_profiles_dir(tmp_path, monkeypatch):
    """Fixture to override the config directory using environment variables."""
    monkeypatch.setenv("GWSA_CONFIG_DIR", str(tmp_path))
    yield tmp_path

def test_create_oauth_profile(mock_profiles_dir):
    """Test creating a standard OAuth profile."""
    token_data = {"access_token": "test-oauth-token", "refresh_token": "test-refresh"}
    
    assert create_profile(
        name="test-oauth", 
        token_data=token_data, 
        profile_type=ProfileType.OAUTH, 
        email="oauth@example.com", 
        scopes=["scope1"]
    ) is True
    
    assert profile_exists("test-oauth")
    
    # Verify token
    token_path = get_profile_token_path("test-oauth")
    assert token_path.exists()
    with open(token_path, "r") as f:
        loaded_token = json.load(f)
        assert loaded_token["access_token"] == "test-oauth-token"
        
    # Verify metadata
    metadata_path = get_profile_metadata_path("test-oauth")
    assert metadata_path.exists()
    import yaml
    with open(metadata_path, "r") as f:
        metadata = yaml.safe_load(f)
        assert metadata["type"] == "oauth"
        assert metadata["email"] == "oauth@example.com"
        assert "validated_scopes" in metadata

def test_create_adc_profile(mock_profiles_dir):
    """Test creating an isolated ADC profile."""
    # ADC tokens have a different internal schema, but gwsa Vault treats it as generic JSON
    token_data = {
        "client_id": "test-adc-client", 
        "client_secret": "test-adc-secret",
        "quota_project_id": "test-project-123",
        "type": "authorized_user"
    }
    
    assert create_profile(
        name="test-adc", 
        token_data=token_data, 
        profile_type=ProfileType.ADC, 
        email="adc@example.com", 
        scopes=["https://www.googleapis.com/auth/cloud-platform"]
    ) is True
    
    assert profile_exists("test-adc")
    
    # Verify metadata handles ADC type appropriately
    metadata_path = get_profile_metadata_path("test-adc")
    import yaml
    with open(metadata_path, "r") as f:
        metadata = yaml.safe_load(f)
        assert metadata["type"] == "adc"
        assert metadata["email"] == "adc@example.com"
        assert metadata["validated_scopes"] == ["https://www.googleapis.com/auth/cloud-platform"]

def test_delete_profiles(mock_profiles_dir):
    """Test that deleting profiles works homogeneously regardless of type."""
    create_profile("p1", {}, ProfileType.OAUTH)
    create_profile("p2", {}, ProfileType.ADC)
    
    assert profile_exists("p1")
    assert profile_exists("p2")
    
    assert delete_profile("p1") is True
    assert delete_profile("p2") is True
    
    assert not profile_exists("p1")
    assert not profile_exists("p2")
