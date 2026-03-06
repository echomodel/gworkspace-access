"""Profile management - re-exports from SDK."""

# Re-export everything from SDK profiles
from gwsa.sdk.profiles import (
    PROFILE_NAME_PATTERN,
    get_profiles_dir,
    is_valid_profile_name,
    get_profile_dir,
    get_profile_token_path,
    get_profile_metadata_path,
    list_profiles,
    get_active_profile_name,
    get_active_profile,
    set_active_profile,
    profile_exists,
    get_profile_status,
    load_profile_metadata,
    save_profile_metadata,
    create_profile,
    delete_profile,
    update_profile_metadata,
)

__all__ = [
    "PROFILE_NAME_PATTERN",
    "get_profiles_dir",
    "is_valid_profile_name",
    "get_profile_dir",
    "get_profile_token_path",
    "get_profile_metadata_path",
    "list_profiles",
    "get_active_profile_name",
    "get_active_profile",
    "set_active_profile",
    "profile_exists",
    "get_profile_status",
    "load_profile_metadata",
    "save_profile_metadata",
    "create_profile",
    "delete_profile",
    "update_profile_metadata",
]
