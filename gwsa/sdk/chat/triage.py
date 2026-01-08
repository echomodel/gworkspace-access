"""
Advanced Chat Triage Strategy (TODO):

1. **Start with most recent message** in a space.
2. **If sender is ME**: Stop. Thread is handled.
3. **If sender is NOT ME**:
    a. **DM/Small Group (<= Threshold)**: Implicit Mention.
       - Stop here (it's unreplied).
    b. **Large Group (> Threshold)**:
       - Walk back through messages (Newest -> Oldest).
       - Stop at 'Lookback Days' limit.
       - **Check for Mentions**: First message that tags me is the "Latest Mention".
       - **Reaction Check**: Once a mention is found, check if I reacted to it.
         - If yes -> Handled.
         - If no -> Walk forward from that mention to Newest.
           - If I reacted to any newer message? -> Handled.
           - If I sent any newer message? -> Handled.
           - Else -> Unhandled Mention.
"""
import logging
import re
from typing import List, Dict, Any, Optional
from datetime import datetime, timedelta, timezone
from .service import get_chat_service
from ..people.service import get_me, get_person_name
from ..timing import get_api_call_stats, reset_api_call_count, time_api_call

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
    discovery_limit: int = 200,
    unanswered_only: bool = True,
    message_limit: int = 100
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
    
    # Metrics
    reset_api_call_count()

    # Friendly wrappers for triage-specific calls
    @time_api_call
    def _list_spaces(page_token=None):
        fields = "nextPageToken,spaces(name,displayName,spaceType,lastActiveTime,membershipCount)"
        return service.spaces().list(pageSize=100, fields=fields, pageToken=page_token).execute()

    @time_api_call
    def _list_members(space_name):
        return service.spaces().members().list(parent=space_name, pageSize=5).execute()

    @time_api_call
    def _list_space_messages(space_name, fetch_limit):
        return service.spaces().messages().list(
            parent=space_name, 
            pageSize=fetch_limit, 
            orderBy="createTime desc"
        ).execute()

    @time_api_call
    def _list_reactions(message_name):
        return service.spaces().messages().reactions().list(parent=message_name).execute()

    # Identify myself
    logger.debug("Invoking profile resolution (logical API call)...")
    myself = get_me()
    # People API returns 'resourceName' as 'people/123...', 
    # Chat API expects 'sender.name' as 'users/123...'
    raw_name = myself.get('resourceName', '')
    my_id = None
    if raw_name.startswith('people/'):
        my_id = f"users/{raw_name.split('/')[1]}"
    
    my_display_name = myself.get('displayName', '').split(' ')[0] if myself.get('displayName') else None

    def _analyze_message(msg: Dict[str, Any], my_id: str, my_display_name: str, is_implicit: bool, i_have_responded: bool) -> Optional[Dict[str, Any]]:
        """Determines if a single message constitutes a mention or actionable item."""
        if is_implicit:
            logger.debug(f"     -> Implicit mention check (members <= {implicit_mention_threshold})")
            if not i_have_responded:
                logger.debug(f"     -> Candidate found (Implicit)")
                return {
                    "type": "Inferred",  # Changed from DM/Small Group
                    "reason": "Unreplied message"
                }
            return None

        # Explicit mention check
        logger.debug(f"     -> Explicit mention check")
        mentioned = False
        
        # 1. Check User Mentions (Annotations)
        if 'annotations' in msg:
            for ann in msg['annotations']:
                if ann.get('type') == 'USER_MENTION':
                    if my_id and ann.get('userMention', {}).get('user', {}).get('name') == my_id:
                        mentioned = True
                        logger.debug(f"     -> User mention annotation matched")
                        break
        
        # 2. Check Text Mentions (@Name)
        if not mentioned and my_display_name and f"@{my_display_name}" in msg.get('text', ''):
            mentioned = True
            logger.debug(f"     -> Text mention matched @{my_display_name}")
            
        if mentioned and not i_have_responded:
            logger.debug(f"     -> Candidate found (Explicit)")
            return {
                "type": "Explicit", # Changed from Mention
                "reason": "Explicit mention"
            }
        
        return None

    all_spaces = []
    page_token = None
    
    while True:
        try:
            res = _list_spaces(page_token)
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
            
        lookback_days = 0 # Default to 0 (exclude) if no tier matches
        
        # Match Tier
        matched_tier = False
        for tier in tiers:
            limit_members = tier.get('max_members')
            # If explicit max limit is set, and we are above it, we stop matching (assuming sorted asc)
            # BUT tiers logic is: find first tier that FITS.
            if limit_members is None or members_count <= limit_members:
                lookback_days = tier.get('lookback_days', 1)
                matched_tier = True
                break
        
        if not matched_tier or lookback_days <= 0:
            continue
            
        last_active = _parse_api_time(space.get('lastActiveTime'))
        cutoff = now - timedelta(days=lookback_days)
        
        if last_active > cutoff:
            # Determine Sort Priority
            # 1. Type: DM (0) < Group (1) < Space (2)
            stype = space.get('spaceType', 'SPACE')
            if stype == 'DIRECT_MESSAGE':
                # Differentiate DMs (2 people) vs Group DMs (>2)
                type_score = 0 if members_count <= 2 else 1
            else:
                type_score = 2
            
            candidates.append({
                'space': space,
                'members': members_count,
                'last_active': last_active,
                'lookback_days': lookback_days,
                'type_score': type_score
            })

    # Sort Candidates: Type Score ASC, then Members ASC
    candidates.sort(key=lambda x: (x['type_score'], x['members']))
    
    # 3. Analyze Candidates
    results = []
    space_stats = []
    total_messages_scanned = 0
    exit_reason = "completed"
    
    for item in candidates: # Remove slice [:limit], handle loop break manually if needed or rely on message limit
        # We still respect 'limit' for *spaces to scan* if provided?
        # The user said "highest users one will be the limit above which no space will be consddered".
        # But `limit` param (default 20) was "active spaces to scan".
        # Let's keep respecting `limit` as "max spaces to scan".
        if len(space_stats) >= limit:
            exit_reason = "space_limit_reached"
            break

        if total_messages_scanned >= message_limit:
            exit_reason = "message_limit_reached"
            break

        space = item['space']
        members_count = item['members']
        space_name = space['name']
        display_name = space.get('displayName')
        last_active = item['last_active']
        lookback_days = item['lookback_days']
        cutoff = now - timedelta(days=lookback_days)
        
        # Stats for this space
        current_space_stat = {
            "id": space_name,
            "name": display_name or "Unknown", # Will update if resolved
            "type": space.get('spaceType'),
            "members": members_count,
            "last_active": last_active.isoformat(),
            "lookback_days": lookback_days,
            "messages_scanned": 0,
            "messages_in_range": 0,
            "mentions_found": 0,
            "unanswered_mentions": 0
        }
        
        # Enhanced metadata logging before processing
        logger.debug(f"Analyzing space: {display_name} ({space_name}) | Last Active: {last_active} | Members: {members_count} | Lookback: {lookback_days} days")

        # Final fallback for display_name
        if not display_name:
            display_name = "Unknown Space"

        is_implicit = members_count <= implicit_mention_threshold
        
        # Safety: Cannot do implicit check without knowing who I am
        if is_implicit and not my_id:
            space_stats.append(current_space_stat)
            continue

        try:
            fetch_limit = 1 if is_implicit else 20
            msgs_res = _list_space_messages(space_name, fetch_limit)
            
            messages = msgs_res.get('messages', [])
            current_space_stat["messages_scanned"] = len(messages)
            total_messages_scanned += len(messages)
            
            if not messages:
                logger.debug(f"  -> No messages found")
                space_stats.append(current_space_stat)
                continue
            
            i_have_responded = False
            for msg in messages:
                msg_time = _parse_api_time(msg.get('createTime'))
                sender_id = msg.get('sender', {}).get('name')
                sender_name = msg.get('sender', {}).get('displayName', 'Unknown')
                text_snippet = msg.get('text', '')[:50]
                
                logger.debug(f"  -> Message {msg.get('name')} from {sender_name} ({sender_id}) at {msg_time}: {text_snippet}")

                if msg_time < cutoff:
                    logger.debug(f"     -> Skipped (too old)")
                    continue
                
                current_space_stat["messages_in_range"] += 1

                if sender_id == my_id:
                    logger.debug(f"     -> Is me. Thread handled.")
                    i_have_responded = True
                    if unanswered_only:
                        break # Stop scanning this thread
                    continue
                
                # Check for actionable item
                found_item = _analyze_message(msg, my_id, my_display_name, is_implicit, i_have_responded)
                
                if found_item:
                    current_space_stat["mentions_found"] += 1
                
                if found_item and unanswered_only:
                    logger.debug(f"     -> Checking reactions...")
                    # Check for my reaction to this message (1 extra API call)
                    try:
                        reac_res = _list_reactions(msg.get('name'))
                        reactions = reac_res.get('reactions', [])
                        for r in reactions:
                            if r.get('user', {}).get('name') == my_id:
                                found_item = None # Handled by reaction!
                                logger.debug(f"     -> Handled by reaction")
                                break
                    except Exception as e:
                        logger.debug(f"     -> Reaction check failed: {e}")
                        pass # Continue as unreplied if check fails

                if found_item:
                    current_space_stat["unanswered_mentions"] += 1
                    logger.debug(f"     -> Actionable item confirmed: {found_item['reason']}")
                    
                    final_sender_name = msg.get('sender', {}).get('displayName')
                    if not final_sender_name:
                        s_id = msg.get('sender', {}).get('name')
                        if s_id:
                            logger.debug(f"Invoking name resolution for sender {s_id} (logical API call)...")
                            final_sender_name = get_person_name(s_id)
                    
                    # Fallback: Check for email if name is still unknown
                    if (not final_sender_name or final_sender_name == "Unknown"):
                        email = msg.get('sender', {}).get('email')
                        if email:
                            final_sender_name = email
                        else:
                            # Note: We could try the Directory API here for external users, but it adds
                            # significant complexity/latency for a rare edge case. Sticking to "Unknown".
                            # Future: As more customers adopt Workspace federation, they may appear as 
                            # "Unknown" if not in contacts/directory. We're not there yet.
                            logger.debug(f"Sender object for unresolved external user: {msg.get('sender', {})}")
                            pass

                    results.append({
                        "type": found_item['type'],
                        "space": display_name,
                        "space_id": space_name,
                        "members": members_count,
                        "thread_name": msg.get('thread', {}).get('name'),
                        "time": msg.get('createTime'),
                        "sender": final_sender_name or "Unknown",
                        "text": msg.get('text', '')[:100],
                        "reason": found_item['reason']
                    })
                    break 
            
            space_stats.append(current_space_stat)

        except Exception as e:
            logger.warning(f"Failed to scan space {space_name}: {e}")
            space_stats.append(current_space_stat)
            continue

    stats = get_api_call_stats()
    total_calls = sum(stats.values())
    logger.debug(f"Total logical API calls made: {total_calls} ({stats})")
    
    return {
        "mentions": results,
        "source": {
            "spaces": space_stats,
            "total_spaces_scanned": len(space_stats),
            "total_messages_scanned": total_messages_scanned,
            "exit_reason": exit_reason
        },
        "scanned_count": len(candidates),
        "total_count": len(all_spaces),
        "api_stats": stats
    }