"""Google People API service for GWSA SDK."""

import logging
from typing import Any, Dict, Optional

from googleapiclient.discovery import build
from ..auth import get_credentials
from ..cache import get_cached_profile, set_cached_profile
from ..timing import time_api_call

logger = logging.getLogger(__name__)

def get_people_service(account: Optional[str] = None) -> Any:
    """Get an authenticated Google People API service object.

    Args:
        account: Optional account selector — name or email. Omit to use
            the user's default account.
    """
    creds, _ = get_credentials(account=account)
    return build("people", "v1", credentials=creds, static_discovery=False)

@time_api_call
def _fetch_person_from_api(resource_name: str, fields: str = 'names', account: Optional[str] = None):
    """Helper function to isolate the API call for timing."""
    service = get_people_service(account=account)
    return service.people().get(
        resourceName=resource_name,
        personFields=fields
    ).execute()

def _resolve_person_profile(user_id: Optional[str], account: Optional[str] = None) -> Dict[str, Optional[str]]:
    """Resolve and cache a Google User ID's displayName and primary email address."""
    if not user_id:
        return {"displayName": "Unknown", "email": None}

    if user_id.startswith("users/"):
        user_id = user_id.split("/")[1]

    resource_name = f"people/{user_id}"

    cached_data = get_cached_profile(user_id)
    if cached_data and "email" in cached_data:
        return {
            "displayName": cached_data.get("displayName", "Unknown"),
            "email": cached_data.get("email"),
        }

    try:
        person = _fetch_person_from_api(
            resource_name, fields="names,emailAddresses", account=account
        )

        display_name = "Unknown"
        if "names" in person and len(person["names"]) > 0:
            display_name = person["names"][0].get("displayName", "Unknown")

        email = None
        if "emailAddresses" in person and len(person["emailAddresses"]) > 0:
            email = person["emailAddresses"][0].get("value")

        profile = {"displayName": display_name, "email": email}
        set_cached_profile(user_id, profile)
        return profile
    except Exception as e:
        logger.error(f"Error fetching profile for {user_id}: {e}")
        return {
            "displayName": (cached_data or {}).get("displayName", "Unknown"),
            "email": None,
        }


@time_api_call
def get_person_name(user_id: str, account: Optional[str] = None) -> str:
    """Resolve a Google User ID (e.g., 'users/12345') to a display name.

    Uses the People API and caches results to minimize API calls.
    Returns 'Unknown' if resolution fails or ID is invalid.

    Args:
        user_id: The user ID to resolve.
        account: Optional account selector — name or email. Omit to use
            the user's default account.
    """
    return _resolve_person_profile(user_id, account=account).get("displayName") or "Unknown"


def get_person_email(user_id: Optional[str], account: Optional[str] = None) -> Optional[str]:
    """Resolve a Google User ID (e.g., 'users/12345') to a primary email address if available."""
    return _resolve_person_profile(user_id, account=account).get("email")


@time_api_call
def get_me(account: Optional[str] = None) -> Dict[str, Any]:
    """Get the authenticated user's profile information.

    Args:
        account: Optional account selector — name or email. Omit to use
            the user's default account.
    """
    user_id = "me"

    # Try cache (keyed by 'me')
    cached_data = get_cached_profile(user_id)
    if cached_data:
        return cached_data

    try:
        person = _fetch_person_from_api('people/me', fields='names,emailAddresses', account=account)
        
        # Add a convenience display name at top level if found
        if 'names' in person and person['names']:
            person['displayName'] = person['names'][0].get('displayName')
            
        # Cache the profile
        set_cached_profile(user_id, person)
        return person
    except Exception as e:
        logger.error(f"Error fetching 'me' profile: {e}")
        return {}