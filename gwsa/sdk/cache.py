import os
import json
import tempfile
import logging
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)

CACHE_DIR = os.path.join(tempfile.gettempdir(), 'gwsa_cache')
PROFILES_CACHE_FILE = os.path.join(CACHE_DIR, 'profiles.json')
MEMBERS_CACHE_FILE = os.path.join(CACHE_DIR, 'members.json')
CACHE_TTL = timedelta(days=1)

def _ensure_cache_dir():
    """Ensure the cache directory exists."""
    try:
        os.makedirs(CACHE_DIR, exist_ok=True)
    except OSError as e:
        logger.error(f"Failed to create cache directory at {CACHE_DIR}: {e}")
        raise

def _load_cache(cache_file):
    """Load a specific cache file from disk."""
    _ensure_cache_dir()
    if not os.path.exists(cache_file):
        logger.debug(f"Cache file {cache_file} not found, returning empty cache.")
        return {}
    try:
        with open(cache_file, 'r') as f:
            return json.load(f)
    except (json.JSONDecodeError, IOError) as e:
        logger.warning(f"Error loading cache file {cache_file}, returning empty cache: {e}")
        return {}

def _save_cache(cache_data, cache_file):
    """Save data to a specific cache file on disk."""
    _ensure_cache_dir()
    try:
        with open(cache_file, 'w') as f:
            json.dump(cache_data, f, indent=2)
        logger.debug(f"Cache saved successfully to {cache_file}.")
    except IOError as e:
        logger.error(f"Error saving cache file to {cache_file}: {e}")

def get_cached_item(key, cache_file):
    """Generic function to get an item from a specified cache file."""
    cache = _load_cache(cache_file)
    if key not in cache:
        logger.debug(f"Item '{key}' not found in cache file {cache_file}.")
        return None

    cached_item = cache[key]
    cached_at = datetime.fromisoformat(cached_item.get('cached_at', '1970-01-01'))
    
    if datetime.now() - cached_at > CACHE_TTL:
        logger.debug(f"Cache for '{key}' in {cache_file} is expired.")
        del cache[key]
        _save_cache(cache, cache_file)
        return None
    
    logger.debug(f"Item '{key}' found in cache {cache_file}, still valid.")
    return cached_item.get('data')

def set_cached_item(key, data, cache_file):
    """Generic function to save an item to a specified cache file."""
    cache = _load_cache(cache_file)
    cache[key] = {
        'data': data,
        'cached_at': datetime.now().isoformat()
    }
    _save_cache(cache, cache_file)
    logger.debug(f"Item '{key}' saved to cache file {cache_file}.")

# --- Profile-specific functions ---
def get_cached_profile(user_id):
    return get_cached_item(user_id, PROFILES_CACHE_FILE)

def set_cached_profile(user_id, profile_data):
    set_cached_item(user_id, profile_data, PROFILES_CACHE_FILE)

# --- Members-specific functions ---
def get_cached_members(space_id):
    return get_cached_item(space_id, MEMBERS_CACHE_FILE)

def set_cached_members(space_id, members_data):
    set_cached_item(space_id, members_data, MEMBERS_CACHE_FILE)