
import click
import json
import os
import logging
import sys
from datetime import datetime
from zoneinfo import ZoneInfo
from gwsa.sdk.chat import get_chat_service
from gwsa.sdk import profiles
from gwsa.sdk.timing import time_api_call

# Configure logging to respect LOG_LEVEL environment variable
log_level = os.environ.get('LOG_LEVEL', 'INFO').upper()
if log_level == 'DEBUG':
    log_file_path = 'gwsa-debug.log'
    # Get the root logger
    root_logger = logging.getLogger()
    root_logger.setLevel(logging.DEBUG)
    
    # Remove existing handlers to avoid duplicate logs
    for handler in root_logger.handlers[:]:
        root_logger.removeHandler(handler)
        
    # Add a file handler
    handler = logging.FileHandler(log_file_path, mode='w')
    formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
    handler.setFormatter(formatter)
    root_logger.addHandler(handler)
    
    click.echo(f"DEBUG mode enabled. Log file: {os.path.abspath(log_file_path)}", err=True)
else:
    # Default logging for non-debug levels
    logging.basicConfig(level=getattr(logging, log_level), stream=sys.stderr, format='%(levelname)s:%(name)s:%(message)s')

@click.group()
def chat():
    """Manage Google Chat resources."""
    pass

@chat.group()
def spaces():
    """Manage Chat spaces."""
    pass

@spaces.command("list")
@click.option("--limit", default=10, help="Maximum number of spaces to list.")
@click.option("--type", "space_type", type=click.Choice(['DIRECT_MESSAGE', 'GROUP_CHAT', 'SPACE'], case_sensitive=False), help="Filter by space type.")
@click.option("--format", default="text", type=click.Choice(['text', 'json'], case_sensitive=False), help="Output format.")
@click.option("-v", "--verbose", is_flag=True, help="Show additional metadata (Last Active, Users, Description).")
@click.option("--names", is_flag=True, help="Resolve and show participant names for DMs and Group Chats (slower).")
def list_spaces(limit, space_type, format, verbose, names):
    """List available Chat spaces."""
    try:
        profile = profiles.get_active_profile()
        if not profile:
            click.echo("Error: No active profile configured.", err=True)
            return

        chat_service = get_chat_service()
        
        filter_query = ''
        if space_type:
            filter_query = f"space_type = \"{space_type.upper()}\""

        results = chat_service.spaces().list(pageSize=limit, filter=filter_query).execute()
        spaces = results.get('spaces', [])

        if not spaces:
            click.echo("No spaces found.")
            return

        if names:
            from gwsa.sdk.people import get_person_name
            from gwsa.sdk.cache import get_cached_members, set_cached_members

            @time_api_call
            def _fetch_members_from_api(space_name):
                """Helper to isolate the members API call for timing."""
                return chat_service.spaces().members().list(parent=space_name, pageSize=10).execute()

            # This is the slower part, as it makes extra API calls (though cached)
            for space in spaces:
                if space.get('spaceType') in ['DIRECT_MESSAGE', 'GROUP_CHAT']:
                    try:
                        members = get_cached_members(space['name'])
                        if not members:
                            members_result = _fetch_members_from_api(space['name'])
                            members = members_result.get('memberships', [])
                            set_cached_members(space['name'], members)
                        
                        # We need the current user's ID to exclude them from the name list.
                        # For now, we'll just show all members. A future improvement could be to
                        # get the current user's profile once and filter them out.
                        participant_names = [
                            get_person_name(m.get('member', {}).get('name')).split(' ')[0]
                            for m in members
                        ]
                        space['participant_names'] = ", ".join(participant_names)
                    except Exception:
                        space['participant_names'] = "Error fetching names"


        if format == 'json':
            click.echo(json.dumps(spaces, indent=2))
        else:
            # Fixed column widths for robust alignment
            # As requested: " .!!!! 🧨 [GCP Networking Practice]  " -> 41 chars
            # As requested: "Communite the status o" -> 21 chars
            ID_WIDTH = 15  # Reduced width
            TYPE_WIDTH = 6
            NAME_WIDTH = 41
            LAST_ACTIVE_WIDTH = 12
            USERS_WIDTH = 5
            DESCRIPTION_WIDTH = 21

            headers = ["ID", "Type", "Name"]
            if verbose:
                headers.extend(["Last Active", "Users", "Description"])
            
            header_parts = [f"{h:<{w}}" for h, w in zip(headers, [ID_WIDTH, TYPE_WIDTH, NAME_WIDTH])]
            if verbose:
                 header_parts.extend([
                    f"{headers[3]:<{LAST_ACTIVE_WIDTH}}",
                    f"{headers[4]:<{USERS_WIDTH}}",
                    f"{headers[5]:<{DESCRIPTION_WIDTH}}"
                ])
            
            header_str = " | ".join(header_parts)
            click.echo(header_str)
            click.echo("-" * len(header_str))

            for space in spaces:
                name_full = space.get('name', '')
                name_short = name_full.replace('spaces/', '')  # Strip prefix
                
                # Determine display name
                if names and space.get('participant_names'):
                    display_name = space['participant_names']
                else:
                    display_name = space.get('displayName', 'Unknown')
                
                # Truncate display name
                if len(display_name) > NAME_WIDTH:
                    display_name = display_name[:NAME_WIDTH - 3] + '...'
                
                # Shorten space type
                space_type_full = space.get('spaceType', 'Unknown')
                space_type_short = {
                    'SPACE': 'space',
                    'DIRECT_MESSAGE': 'direct',
                    'GROUP_CHAT': 'group'
                }.get(space_type_full, 'other')
                
                row_parts = [f"{name_short:<{ID_WIDTH}}", f"{space_type_short:<{TYPE_WIDTH}}", f"{display_name:<{NAME_WIDTH}}"]

                if verbose:
                    # Format Last Active Time
                    last_active_str = space.get('lastActiveTime', '')
                    formatted_time = ''
                    if last_active_str:
                        dt_obj_utc = datetime.fromisoformat(last_active_str.replace('Z', '+00:00'))
                        local_timezone = datetime.now().astimezone().tzinfo
                        dt_obj_local = dt_obj_utc.astimezone(local_timezone)
                        formatted_time = dt_obj_local.strftime('%m-%d %H:%M')

                    # Format User Count
                    count = space.get('membershipCount', {}).get('joinedDirectHumanUserCount', 0)
                    user_count_str = str(count) if count < 1000 else '999+'

                    # Format Description
                    description = space.get('spaceDetails', {}).get('description', '')
                    description_snippet = (description[:DESCRIPTION_WIDTH - 3] + '...') if len(description) > DESCRIPTION_WIDTH else description
                    
                    row_parts.extend([
                        f"{formatted_time:<{LAST_ACTIVE_WIDTH}}",
                        f"{user_count_str:<{USERS_WIDTH}}",
                        f"{description_snippet:<{DESCRIPTION_WIDTH}}"
                    ])
                
                click.echo(" | ".join(row_parts))

    except Exception as e:
        click.echo(f"Error listing spaces: {e}", err=True)

@spaces.command("members")
@click.argument("space_id")
def list_members(space_id):
    """List members of a Chat space."""
    try:
        profile = profiles.get_active_profile()
        if not profile:
            click.echo("Error: No active profile configured.", err=True)
            return

        chat_service = get_chat_service()
        # Use a reasonable page size
        members = chat_service.spaces().members().list(parent=space_id, pageSize=100).execute()
        
        if 'memberships' not in members:
            click.echo("No members found.")
            return

        from gwsa.sdk.people import get_person_name

        for m in members['memberships']:
            member = m.get('member', {})
            user_id = member.get('name')
            display_name = member.get('displayName', 'Unknown')
            
            # Try to resolve name if it's unknown or just an ID (though API usually gives displayName for members)
            # But let's be consistent and use our resolver if needed, or at least show what we have.
            # Actually, for members, the Chat API *does* often return displayName if the scope is right.
            # But let's use our resolver to be safe if it's missing.
            
            if display_name == 'Unknown' or not display_name:
                 display_name = get_person_name(user_id)
            
            click.echo(f"{display_name} ({user_id})")

    except Exception as e:
        click.echo(f"Error listing members: {e}", err=True)


@chat.group()
def messages():
    """Manage Chat messages."""
    pass

@messages.command("list")
@click.argument("space_id")
@click.option("--limit", default=25, help="Maximum number of messages to list.")
def list_chat_messages(space_id, limit):
    """List messages in a space."""
    try:
        profile = profiles.get_active_profile()
        if not profile:
            click.echo("Error: No active profile configured.", err=True)
            return

        chat_service = get_chat_service()
        result = chat_service.spaces().messages().list(parent=space_id, pageSize=limit).execute()
        messages = result.get('messages', [])
        
        if not messages:
            click.echo("No messages found.")
            return

        from gwsa.sdk.people import get_person_name

        for msg in messages:
            sender = msg.get('sender', {})
            user_id = sender.get('name')
            author = get_person_name(user_id)
            
            text = msg.get('text', '').replace('\n', ' ')
            click.echo(f"[{msg.get('createTime')}] {author}: {text[:100]}")

    except Exception as e:
        click.echo(f"Error listing messages: {e}", err=True)

@messages.command("search")
@click.argument("space_id")
@click.argument("query")
@click.option("--limit", default=100, help="Max messages to scan.")
def search_chat_messages(space_id, query, limit):
    """Search for messages containing QUERY in a space."""
    try:
        profile = profiles.get_active_profile()
        if not profile:
            click.echo("Error: No active profile configured.", err=True)
            return

        click.echo(f"Searching for '{query}' in {space_id} (scanning last {limit} messages)...")
        
        chat_service = get_chat_service()
        results = chat_service.spaces().messages().list(parent=space_id, pageSize=limit).execute()
        messages = results.get('messages', [])
        
        matches = [msg for msg in messages if query.lower() in msg.get('text', '').lower()]
        
        click.echo(f"Scanned: {len(messages)}, Found: {len(matches)}")
        
        for msg in matches:
            from gwsa.sdk.people import get_person_name
            author = get_person_name(msg.get('sender', {}).get('name'))
            text = msg.get('text', '').replace('\n', ' ')
            click.echo(f"[{msg.get('createTime')}] {author}: {text}")

    except Exception as e:
        click.echo(f"Error searching messages: {e}", err=True)
