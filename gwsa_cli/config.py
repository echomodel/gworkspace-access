import os
import yaml
from pathlib import Path
import logging
from typing import Any

logger = logging.getLogger(__name__)

def get_config_file_path() -> Path:
    """
    Gets the path to the config file, respecting the GWSA_CONFIG_FILE env var.
    This singleton-like function allows tests to override the config path.
    """
    env_path = os.getenv("GWSA_CONFIG_FILE")
    if env_path:
        return Path(env_path)
    
    config_dir = Path.home() / ".config" / "gworkspace-access"
    return config_dir / "config.yaml"

DEFAULT_CONFIG = {
    "auth": {
        # No default mode anymore, must be explicitly set.
        "mode": None
    }
}

def load_config() -> dict:
    """Loads the gwsa configuration from the dynamic config file path."""
    config_file = get_config_file_path()
    if not config_file.exists():
        logger.debug(f"Config file not found at {config_file}, using default config.")
        return DEFAULT_CONFIG.copy()
    
    try:
        with open(config_file, 'r') as f:
            config = yaml.safe_load(f)
            if config is None: # Handle empty config file
                return DEFAULT_CONFIG.copy()
            # Merge with default config to ensure all keys exist
            return _deep_merge(DEFAULT_CONFIG.copy(), config)
    except yaml.YAMLError as e:
        logger.error(f"Error loading config file {config_file}: {e}")
        return DEFAULT_CONFIG.copy()
    except Exception as e:
        logger.error(f"An unexpected error occurred while loading config: {e}")
        return DEFAULT_CONFIG.copy()

def save_config(config_data: dict):
    """Saves the gwsa configuration to the dynamic config file path."""
    config_file = get_config_file_path()
    config_file.parent.mkdir(parents=True, exist_ok=True)
    try:
        with open(config_file, 'w') as f:
            yaml.safe_dump(config_data, f, default_flow_style=False)
        logger.info(f"Configuration saved to {config_file}")
    except Exception as e:
        logger.error(f"Error saving config file {config_file}: {e}")

def get_config_value(key: str, default: Any = None) -> Any:
    """Retrieves a configuration value using a dot-separated key."""
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
    """Sets a configuration value using a dot-separated key and saves the config."""
    config_data = load_config()
    keys = key.split('.')
    current_level = config_data
    for i, k in enumerate(keys):
        if i == len(keys) - 1: # Last key
            current_level[k] = value
        else:
            if k not in current_level or not isinstance(current_level[k], dict):
                current_level[k] = {}
            current_level = current_level[k]
    save_config(config_data)

def _deep_merge(base: dict, new: dict) -> dict:
    """Recursively merges dictionary `new` into `base`."""
    for k, v in new.items():
        if k in base and isinstance(base[k], dict) and isinstance(v, dict):
            base[k] = _deep_merge(base[k], v)
        else:
            base[k] = v
    return base
