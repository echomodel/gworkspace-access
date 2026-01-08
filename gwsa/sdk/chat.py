from googleapiclient.discovery import build
from ..sdk.auth import get_credentials
from ..sdk.people import get_person_name


def get_chat_service():
    creds = get_credentials()
    return build('chat', 'v1', credentials=creds, static_discovery=False)


def get_recent_chats(chat_type: str, limit: int = 10):
    chat_service = get_chat_service()
    
    # 1. List spaces using server-side filtering and requesting metadata
    filter_query = f"space_type = \"{chat_type}\""
    fields = "nextPageToken,spaces(name,displayName,spaceType,lastActiveTime,membershipCount)"
    
    all_spaces = []
    page_token = None
    while True:
        results = chat_service.spaces().list(
            pageSize=100, 
            pageToken=page_token, 
            filter=filter_query,
            fields=fields
        ).execute()
        
        spaces = results.get('spaces', [])
        all_spaces.extend(spaces)
        
        page_token = results.get('nextPageToken')
        if not page_token:
            break

    # 2. Sort by lastActiveTime (descending)
    # Handle missing timestamps gracefully (treat as very old)
    sorted_spaces = sorted(
        all_spaces, 
        key=lambda x: x.get('lastActiveTime', '1970-01-01T00:00:00Z'), 
        reverse=True
    )

    # 3. Prepare and return the final list
    recent_chats = []
    for space in sorted_spaces[:limit]:
        display_name = space.get('displayName', 'Unknown')

        # For DMs, try to resolve the name of the other person
        if chat_type == 'DIRECT_MESSAGE' and display_name == 'Unknown':
            try:
                members_result = chat_service.spaces().members().list(parent=space['name'], pageSize=2).execute()
                members = members_result.get('memberships', [])
                
                # Simplified logic: Assume the first member found is the other user.
                # A robust solution would need to know the current user's ID to filter them out.
                if members:
                    other_member = members[0].get('member', {})
                    # The Chat API often returns a displayName for members directly.
                    # If not, we fall back to the People API.
                    resolved_name = other_member.get('displayName')
                    if not resolved_name:
                        resolved_name = get_person_name(other_member.get('name'))
                    display_name = resolved_name

            except Exception:
                pass # Stick with "Unknown" if we can't resolve it.

        recent_chats.append({
            'id': space['name'],
            'displayName': display_name
        })
        
    return recent_chats
