"""Google People API service for GWSA SDK."""

import logging
from typing import Any, Dict

from googleapiclient.discovery import build
from gwsa.sdk import auth

logger = logging.getLogger(__name__)

# Simple in-memory cache for resolved names
_NAME_CACHE: Dict[str, str] = {}

def get_people_service() -> Any:
    """Get an authenticated Google People API service object."""
    creds, _ = auth.get_credentials()
    return build("people", "v1", credentials=creds)

def get_person_name(user_id: str) -> str:
    """
    Resolve a Google User ID (e.g., 'users/12345') to a display name.
    
    Uses the People API and caches results to minimize API calls.
    Returns 'Unknown' if resolution fails or ID is invalid.
    """
    if not user_id or not user_id.startswith('users/'):
        return 'Unknown'

    if user_id in _NAME_CACHE:
        return _NAME_CACHE[user_id]

    try:
        # Extract numeric ID from 'users/12345'
        numeric_id = user_id.split('/')[1]
        resource_name = f"people/{numeric_id}"
        
        service = get_people_service()
        person = service.people().get(
            resourceName=resource_name,
            personFields="names"
        ).execute()
        
        names = person.get('names', [])
        if names:
            display_name = names[0].get('displayName')
            if display_name:
                _NAME_CACHE[user_id] = display_name
                return display_name
                
    except Exception as e:
        logger.debug(f"Failed to resolve name for {user_id}: {e}")
        pass

    # Cache failure as 'Unknown' (or maybe the ID itself?) to avoid retrying
    # For now, let's return the ID as a fallback so it's at least unique
    _NAME_CACHE[user_id] = user_id
    return user_id
