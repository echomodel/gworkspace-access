"""Configuration management for GWSA.

Handles loading and saving YAML configuration from ~/.config/gworkspace-access/.
"""

import os
import yaml
import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


def get_config_dir() -> Path:
    """Get the configuration directory path."""
    env_path = os.getenv("GWSA_CONFIG_DIR")
    if env_path:
        return Path(env_path)
    return Path.home() / ".config" / "gworkspace-access"


def get_config_file_path() -> Path:
    """
    Get the path to the config file, respecting the GWSA_CONFIG_FILE env var.
    """
    env_path = os.getenv("GWSA_CONFIG_FILE")
    if env_path:
        return Path(env_path)
    return get_config_dir() / "config.yaml"


DEFAULT_CONFIG = {
    "auth": {
        "mode": None
    }
}


def load_config() -> dict:
    """Load the gwsa configuration from the config file."""
    config_file = get_config_file_path()
    if not config_file.exists():
        logger.debug(f"Config file not found at {config_file}, using default config.")
        return DEFAULT_CONFIG.copy()

    try:
        with open(config_file, 'r') as f:
            config = yaml.safe_load(f)
            if config is None:
                return DEFAULT_CONFIG.copy()
            return _deep_merge(DEFAULT_CONFIG.copy(), config)
    except yaml.YAMLError as e:
        logger.error(f"Error loading config file {config_file}: {e}")
        return DEFAULT_CONFIG.copy()
    except Exception as e:
        logger.error(f"An unexpected error occurred while loading config: {e}")
        return DEFAULT_CONFIG.copy()


def save_config(config_data: dict):
    """Save the gwsa configuration to the config file."""
    config_file = get_config_file_path()
    config_file.parent.mkdir(parents=True, exist_ok=True)
    try:
        with open(config_file, 'w') as f:
            yaml.safe_dump(config_data, f, default_flow_style=False)
        logger.debug(f"Configuration saved to {config_file}")
    except Exception as e:
        logger.error(f"Error saving config file {config_file}: {e}")


def get_config_value(key: str, default: Any = None) -> Any:
    """Retrieve a configuration value using a dot-separated key."""
    config_data = load_config()
    keys = key.split('.')
    value = config_data
    for k in keys:
        if isinstance(value, dict) and k in value:
            value = value[k]
        else:
            return default
    return value


def set_config_value(key: str, value: Any):
    """Set a configuration value using a dot-separated key and save."""
    config_data = load_config()
    keys = key.split('.')
    current_level = config_data
    for i, k in enumerate(keys):
        if i == len(keys) - 1:
            current_level[k] = value
        else:
            if k not in current_level or not isinstance(current_level[k], dict):
                current_level[k] = {}
            current_level = current_level[k]
    save_config(config_data)


def _deep_merge(base: dict, new: dict) -> dict:
    """Recursively merge dictionary `new` into `base`."""
    for k, v in new.items():
        if k in base and isinstance(base[k], dict) and isinstance(v, dict):
            base[k] = _deep_merge(base[k], v)
        else:
            base[k] = v
    return base
