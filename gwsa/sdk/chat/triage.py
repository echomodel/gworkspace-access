import logging
import re
from typing import List, Dict, Any, Optional
from datetime import datetime, timedelta, timezone
from .service import get_chat_service
from ..people.service import get_me, get_person_name

logger = logging.getLogger(__name__)

def _parse_api_time(timestamp: str) -> datetime:
    """Parses Google API timestamp (RFC 3339) to UTC datetime."""
    if not timestamp:
        return datetime.min.replace(tzinfo=timezone.utc)
    ts = timestamp.replace("Z", "+00:00")
    if "." in ts:
        parts = ts.split(".")
        seconds = parts[1].split("+")
        if len(seconds[0]) > 6:
            ts = f"{parts[0]}.{seconds[0][:6]}+{seconds[1]}"
    return datetime.fromisoformat(ts)

def get_chat_mentions(
    limit: int = 20,
    implicit_mention_threshold: int = 3,
    tiers: Optional[List[Dict[str, Any]]] = None,
    discovery_limit: int = 200
) -> Dict[str, Any]:
    """
    Scans Google Chat for actionable mentions and unread DMs.
    
    Default tiers match the persona-specific sliding window.
    """
    if tiers is None:
        tiers = [
            {'max_members': 2, 'lookback_days': 14},
            {'max_members': 10, 'lookback_days': 5},
            {'max_members': 50, 'lookback_days': 2},
            {'max_members': None, 'lookback_days': 1}
        ]
    
    # Sort tiers by max_members asc
    tiers.sort(key=lambda x: float('inf') if x['max_members'] is None else x['max_members'])

    service = get_chat_service()
    
    # Identify myself
    myself = get_me()
    my_id = myself.get('name') 
    my_display_name = myself.get('displayName', '').split(' ')[0]

    # 1. Fetch Candidate Spaces
    fields = "nextPageToken,spaces(name,displayName,spaceType,lastActiveTime,membershipCount)"
    all_spaces = []
    page_token = None
    
    while True:
        try:
            res = service.spaces().list(pageSize=100, fields=fields, pageToken=page_token).execute()
            all_spaces.extend(res.get('spaces', []))
            page_token = res.get('nextPageToken')
            if not page_token or len(all_spaces) >= discovery_limit:
                break
        except Exception as e:
            logger.error(f"Failed to list spaces: {e}")
            break
            
    # 2. Filter Candidates
    now = datetime.now(timezone.utc)
    candidates = []
    
    for space in all_spaces:
        members_count = 0
        if 'membershipCount' in space:
            members_count = space['membershipCount'].get('joinedDirectHumanUserCount', 2)
        elif space.get('spaceType') == 'DIRECT_MESSAGE':
            members_count = 2
            
        lookback_days = 1
        for tier in tiers:
            limit_members = tier.get('max_members')
            if limit_members is None or members_count <= limit_members:
                lookback_days = tier.get('lookback_days', 1)
                break
        
        if lookback_days <= 0:
            continue
            
        last_active = _parse_api_time(space.get('lastActiveTime'))
        cutoff = now - timedelta(days=lookback_days)
        
        if last_active > cutoff:
            candidates.append({
                'space': space,
                'members': members_count,
                'last_active': last_active,
                'lookback_days': lookback_days
            })

    candidates.sort(key=lambda x: x['last_active'], reverse=True)
    
    # 3. Analyze Candidates
    results = []
    
    for item in candidates[:limit]:
        space = item['space']
        members_count = item['members']
        space_name = space['name']
        display_name = space.get('displayName')
        lookback_days = item['lookback_days']
        cutoff = now - timedelta(days=lookback_days)
        
        # If DM and no display name, resolve other member
        if not display_name or display_name == "Unknown":
            try:
                m_res = service.spaces().members().list(parent=space_name, pageSize=5).execute()
                memberships = m_res.get('memberships', [])
                other_names = []
                for m in memberships:
                    m_id = m.get('member', {}).get('name')
                    if m_id != my_id:
                        other_names.append(get_person_name(m_id))
                if other_names:
                    display_name = ", ".join(other_names)
                else:
                    display_name = f"Group ({members_count} members)"
            except Exception:
                display_name = "Unknown Space"

        is_implicit = members_count <= implicit_mention_threshold
        
        try:
            fetch_limit = 1 if is_implicit else 20
            msgs_res = service.spaces().messages().list(
                parent=space_name, 
                pageSize=fetch_limit, 
                orderBy="createTime desc"
            ).execute()
            
            messages = msgs_res.get('messages', [])
            if not messages:
                continue
            
            i_have_responded = False
            for msg in messages:
                msg_time = _parse_api_time(msg.get('createTime'))
                if msg_time < cutoff:
                    continue

                sender_id = msg.get('sender', {}).get('name')
                if sender_id == my_id:
                    i_have_responded = True
                    continue
                
                found_item = None
                if is_implicit:
                    if not i_have_responded:
                        found_item = {
                            "type": "DM" if members_count == 2 else "Small Group",
                            "reason": "Unreplied message"
                        }
                else:
                    mentioned = False
                    if 'annotations' in msg:
                        for ann in msg['annotations']:
                            if ann.get('type') == 'USER_MENTION':
                                if ann.get('userMention', {}).get('user', {}).get('name') == my_id:
                                    mentioned = True
                                    break
                    if not mentioned and my_display_name and f"@{my_display_name}" in msg.get('text', ''):
                        mentioned = True
                    if mentioned and not i_have_responded:
                        found_item = {
                            "type": "Mention",
                            "reason": "Explicit mention"
                        }
                
                if found_item:
                    results.append({
                        "type": found_item['type'],
                        "space": display_name,
                        "space_id": space_name,
                        "thread_name": msg.get('thread', {}).get('name'),
                        "time": msg.get('createTime'),
                        "sender": msg.get('sender', {}).get('displayName') or "Unknown",
                        "text": msg.get('text', '')[:100],
                        "reason": found_item['reason']
                    })
                    break 

        except Exception as e:
            logger.warning(f"Failed to scan space {space_name}: {e}")
            continue

    return {
        "mentions": results,
        "scanned_count": len(candidates),
        "total_count": len(all_spaces)
    }
