import logging
from googleapiclient.discovery import build
from ..sdk.auth import get_credentials
from ..sdk.cache import get_cached_profile, set_cached_profile
from ..sdk.timing import time_api_call

from ..sdk.timing import time_api_call

logger = logging.getLogger(__name__)

def get_people_service():
    creds = get_credentials()
    return build('people', 'v1', credentials=creds, static_discovery=False)

@time_api_call
def _fetch_person_from_api(user_id):
    """Helper function to isolate the API call for timing."""
    people_service = get_people_service()
    return people_service.people().get(
        resourceName=user_id,
        personFields='names'
    ).execute()

def get_person_name(user_id):
    """
    Get a person's display name, using a cache to speed up lookups.
    """
    # Try the cache first
    cached_data = get_cached_profile(user_id)
    if cached_data:
        display_name = cached_data.get('displayName', 'Unknown')
        logger.debug(f"[Cache Hit] Retrieved name for {user_id}: {display_name}")
        return display_name

    logger.debug(f"[Cache Miss] Fetching name for {user_id} from API...")
    # If not in cache, fetch from API
    try:
        person = _fetch_person_from_api(user_id)
        
        display_name = "Unknown"
        if 'names' in person and len(person['names']) > 0:
            display_name = person['names'][0].get('displayName', 'Unknown')
        
        # Cache the result
        set_cached_profile(user_id, {'displayName': display_name})
        logger.debug(f"[API Fetch] Resolved and cached name for {user_id}: {display_name}")
        return display_name
    except Exception as e:
        logger.error(f"Error fetching name for {user_id}: {e}")
        # Don't cache failures
        return "Unknown"
