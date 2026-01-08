"""Google People API service for GWSA SDK."""

import logging
from typing import Any, Dict

from googleapiclient.discovery import build
from ..auth import get_credentials
from ..cache import get_cached_profile, set_cached_profile
from ..timing import time_api_call

logger = logging.getLogger(__name__)

def get_people_service() -> Any:
    """Get an authenticated Google People API service object."""
    creds, _ = get_credentials()
    return build("people", "v1", credentials=creds, static_discovery=False)

@time_api_call
def _fetch_person_from_api(resource_name: str, fields: str = 'names'):
    """Helper function to isolate the API call for timing."""
    service = get_people_service()
    return service.people().get(
        resourceName=resource_name,
        personFields=fields
    ).execute()

def get_person_name(user_id: str) -> str:
    """
    Resolve a Google User ID (e.g., 'users/12345') to a display name.
    
    Uses the People API and caches results to minimize API calls.
    Returns 'Unknown' if resolution fails or ID is invalid.
    """
    if not user_id:
        return 'Unknown'
        
    # Standardize ID
    if user_id.startswith('users/'):
        user_id = user_id.split('/')[1]
    
    resource_name = f"people/{user_id}"

    # Try the cache first
    cached_data = get_cached_profile(user_id)
    if cached_data:
        return cached_data.get('displayName', 'Unknown')

    # Fetch from API
    try:
        person = _fetch_person_from_api(resource_name, fields='names')
        
        display_name = "Unknown"
        if 'names' in person and len(person['names']) > 0:
            display_name = person['names'][0].get('displayName', 'Unknown')
        
        # Cache the result
        set_cached_profile(user_id, {'displayName': display_name})
        return display_name
    except Exception as e:
        logger.error(f"Error fetching name for {user_id}: {e}")
        return "Unknown"

def get_me() -> Dict[str, Any]:
    """
    Get the authenticated user's profile information.
    """
    user_id = "me"
    
    # Try cache (keyed by 'me')
    cached_data = get_cached_profile(user_id)
    if cached_data:
        return cached_data

    try:
        person = _fetch_person_from_api('people/me', fields='names,emailAddresses')
        
        # Add a convenience display name at top level if found
        if 'names' in person and person['names']:
            person['displayName'] = person['names'][0].get('displayName')
            
        # Cache the profile
        set_cached_profile(user_id, person)
        return person
    except Exception as e:
        logger.error(f"Error fetching 'me' profile: {e}")
        return {}