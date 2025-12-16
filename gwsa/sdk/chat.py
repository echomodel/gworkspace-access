from googleapiclient.discovery import build
from ..sdk.auth import get_credentials
from ..sdk.people import get_person_name


def get_chat_service():
    creds = get_credentials()
    return build('chat', 'v1', credentials=creds, static_discovery=False)


def get_recent_chats(chat_type: str, limit: int = 10):
    chat_service = get_chat_service()
    
    # 1. List spaces using server-side filtering (more efficient)
    filter_query = f"space_type = \"{chat_type}\""
    
    all_spaces = []
    page_token = None
    while True:
        # Fetch a bit more than the limit to account for spaces we can't read.
        results = chat_service.spaces().list(pageSize=100, pageToken=page_token, filter=filter_query).execute()
        all_spaces.extend(results.get('spaces', []))
        page_token = results.get('nextPageToken')
        if not page_token or len(all_spaces) >= limit * 2: # Stop if we have enough candidates
            break

    # 2. Fetch latest message for each space to get timestamp
    spaces_with_timestamp = []
    for space in all_spaces:
        try:
            messages_result = chat_service.spaces().messages().list(parent=space['name'], pageSize=1, orderBy="createTime desc").execute()
            latest_message = messages_result.get('messages', [{}])[0]
            
            if latest_message:
                spaces_with_timestamp.append({
                    "space": space,
                    "latest_message_time": latest_message.get('createTime', '1970-01-01T00:00:00Z')
                })
        except Exception:
            # Ignore spaces where we can't read messages
            continue

    # 3. Sort by timestamp
    sorted_spaces = sorted(spaces_with_timestamp, key=lambda x: x['latest_message_time'], reverse=True)

    # 4. Prepare and return the final list
    recent_chats = []
    for item in sorted_spaces[:limit]:
        space = item['space']
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
