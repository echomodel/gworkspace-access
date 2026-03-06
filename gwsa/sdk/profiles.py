"""Profile management for multi-identity support.

Profiles allow switching between multiple Google account identities without
re-running OAuth consent flows. Each profile stores its own token and metadata
in an isolated vault directory.
"""

import os
import re
import json
import yaml
import shutil
import logging
from pathlib import Path
from datetime import datetime
from typing import Optional, List, Dict, Any

from .config import get_config_value, set_config_value, get_config_file_path

logger = logging.getLogger(__name__)


from enum import Enum

class ProfileType(Enum):
    OAUTH = "oauth"
    ADC = "adc"

# Valid profile name pattern: alphanumeric, hyphen, underscore, 1-32 chars
PROFILE_NAME_PATTERN = re.compile(r'^[a-zA-Z0-9][a-zA-Z0-9_-]{0,31}$')



def get_profiles_dir() -> Path:
    """Get the profiles directory path."""
    config_dir = get_config_file_path().parent
    return config_dir / "profiles"


def is_valid_profile_name(name: str) -> bool:
    """Check if a profile name is valid."""
    return bool(PROFILE_NAME_PATTERN.match(name))


def get_profile_dir(name: str) -> Path:
    """Get the directory path for a specific profile."""
    return get_profiles_dir() / name


def get_profile_token_path(name: str) -> Path:
    """Get the token file path for a specific profile."""
    return get_profile_dir(name) / "user_token.json"


def get_profile_metadata_path(name: str) -> Path:
    """Get the metadata file path for a specific profile."""
    return get_profile_dir(name) / "profile.yaml"


def list_profiles() -> List[Dict[str, Any]]:
    """
    List all available profiles with their metadata.

    Returns a list of dicts with:
        - name: profile name
        - is_adc: True if this is an ADC profile type
        - is_active: True if this is the currently active profile
        - email: cached user email (may be None if not validated)
        - scopes: list of validated scopes
        - last_validated: timestamp of last validation
    """
    profiles = []
    active_profile = get_active_profile_name()

    # List profiles from the vault
    profiles_dir = get_profiles_dir()
    if profiles_dir.exists():
        for entry in sorted(profiles_dir.iterdir()):
            if entry.is_dir() and is_valid_profile_name(entry.name):
                profile_data = load_profile_metadata(entry.name)
                profiles.append({
                    "name": entry.name,
                    "is_adc": profile_data.get("type") == "adc",
                    "is_active": active_profile == entry.name,
                    "email": profile_data.get("email"),
                    "scopes": profile_data.get("validated_scopes", []),
                    "last_validated": profile_data.get("last_validated"),
                })

    return profiles


def get_active_profile_name() -> Optional[str]:
    """
    Get the name of the currently active profile.

    Returns None if no profile is configured.
    """
    return get_config_value("active_profile")


def get_active_profile() -> Optional[Dict[str, Any]]:
    """
    Get the currently active profile with its metadata.

    Returns None if no profile is configured.
    """
    active_name = get_active_profile_name()
    if not active_name:
        return None

    for profile in list_profiles():
        if profile["name"] == active_name:
            return profile

    return None


def set_active_profile(name: str) -> bool:
    """
    Set the active profile.

    Args:
        name: Profile name to activate (can be "adc" or a token profile name)

    Returns:
        True if successful, False if profile doesn't exist
    """
    if not profile_exists(name):
        return False

    set_config_value("active_profile", name)
    return True


def profile_exists(name: str) -> bool:
    """Check if a profile exists in the vault."""
    profile_dir = get_profile_dir(name)
    token_path = get_profile_token_path(name)
    return profile_dir.exists() and token_path.exists()


def get_profile_status(name: str) -> dict:
    """
    Get the validity status of a profile.

    Returns a dict with:
        - exists: True if profile exists (for token profiles: dir + token file)
        - valid: True if profile is usable (exists, not stale, has been validated)
        - status: 'valid', 'stale', 'unvalidated', 'missing', or 'error'
        - reason: Human-readable explanation if not valid
        - email: Cached email if available

    This is the canonical routine for checking if a profile can be used.
    """
    profile_dir = get_profile_dir(name)
    token_path = get_profile_token_path(name)

    if not profile_dir.exists():
        return {
            "exists": False,
            "valid": False,
            "status": "missing",
            "reason": f"Profile '{name}' does not exist",
            "email": None,
        }

    if not token_path.exists():
        return {
            "exists": False,
            "valid": False,
            "status": "error",
            "reason": f"Token file missing for profile '{name}'",
            "email": None,
        }

    # Check if token file is readable/valid JSON
    try:
        import json
        with open(token_path, 'r') as f:
            json.load(f)
    except Exception as e:
        return {
            "exists": True,
            "valid": False,
            "status": "error",
            "reason": f"Token file corrupted: {e}",
            "email": None,
        }

    # Load metadata
    metadata = load_profile_metadata(name)
    last_validated = metadata.get("last_validated")
    email = metadata.get("email")

    if not last_validated:
        return {
            "exists": True,
            "valid": False,
            "status": "unvalidated",
            "reason": f"Profile '{name}' has never been validated",
            "email": email,
        }

    return {
        "exists": True,
        "valid": True,
        "status": "valid",
        "reason": None,
        "email": email,
    }


def load_profile_metadata(name: str) -> dict:
    """
    Load profile metadata from profile.yaml.

    Returns empty dict if file doesn't exist or can't be read.
    """
    metadata_path = get_profile_metadata_path(name)
    if not metadata_path.exists():
        return {}

    try:
        with open(metadata_path, 'r') as f:
            data = yaml.safe_load(f)
            return data if data else {}
    except Exception as e:
        logger.warning(f"Failed to load profile metadata for '{name}': {e}")
        return {}


def save_profile_metadata(name: str, metadata: dict):
    """Save profile metadata to profile.yaml."""
    metadata_path = get_profile_metadata_path(name)
    metadata_path.parent.mkdir(parents=True, exist_ok=True)

    with open(metadata_path, 'w') as f:
        yaml.safe_dump(metadata, f, default_flow_style=False)


def create_profile(name: str, token_data: dict, profile_type: ProfileType = ProfileType.OAUTH,
                   email: Optional[str] = None,
                   scopes: Optional[list] = None) -> bool:
    """
    Create a new token-based profile.

    Args:
        name: Profile name (must be valid and not "adc")
        token_data: OAuth token data (dict to be saved as user_token.json)
        profile_type: The type of profile (oauth or adc)
        email: User email to cache in metadata
        scopes: Validated scopes to cache in metadata

    Returns:
        True if created successfully, False otherwise
    """
    if not is_valid_profile_name(name):
        logger.error(f"Invalid profile name: {name}")
        return False

    profile_dir = get_profile_dir(name)
    token_path = get_profile_token_path(name)

    profile_dir.mkdir(parents=True, exist_ok=True)

    with open(token_path, 'w') as f:
        json.dump(token_data, f, indent=2)

    metadata = {
        "created": datetime.now().isoformat(),
        "type": profile_type.value,
    }
    if email:
        metadata["email"] = email
    if scopes:
        metadata["validated_scopes"] = scopes
        metadata["last_validated"] = datetime.now().isoformat()

    save_profile_metadata(name, metadata)

    logger.info(f"Created profile '{name}'")
    return True


def delete_profile(name: str) -> bool:
    """
    Delete a token-based profile.

    Args:
        name: Profile name to delete (cannot be "adc")

    Returns:
        True if deleted, False if profile doesn't exist
    """
    profile_dir = get_profile_dir(name)
    if not profile_dir.exists():
        return False

    shutil.rmtree(profile_dir)
    logger.info(f"Deleted profile '{name}'")

    if get_active_profile_name() == name:
        set_config_value("active_profile", None)

    return True


def update_profile_metadata(name: str, email: Optional[str] = None,
                            scopes: Optional[list] = None):
    """
    Update profile metadata after validation.

    Args:
        name: Profile name
        email: User email to cache
        scopes: Validated scopes to cache
    """
    metadata = load_profile_metadata(name)

    if email is not None:
        metadata["email"] = email
    if scopes is not None:
        metadata["validated_scopes"] = scopes
        metadata["last_validated"] = datetime.now().isoformat()

    save_profile_metadata(name, metadata)

