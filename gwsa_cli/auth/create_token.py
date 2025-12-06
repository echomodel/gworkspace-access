"""Create OAuth tokens for specified scopes.

This is a standalone utility that does NOT affect gwsa configuration.
Use it to create tokens for other projects or specific scope combinations.
The tokens created here are independent of gwsa's standard user_token.json.
"""

import os
import logging
from .scopes import resolve_scopes


logger = logging.getLogger(__name__)


def create_token_for_scopes(
    client_creds_path: str,
    output_path: str,
    scopes: list[str]
) -> bool:
    """
    Create a new OAuth token for the specified scopes.

    Performs a fresh OAuth flow using the provided client credentials
    and saves the resulting token to the specified output location.
    Accepts both full scope URLs and short aliases.

    This does NOT touch gwsa configuration or the standard user_token.json.

    Args:
        client_creds_path: Path to the client_secrets.json (OAuth client credentials)
        output_path: Path where the new token should be saved
        scopes: List of Google API scopes or short aliases to request

    Returns:
        True if successful, False otherwise
    """
    from google_auth_oauthlib.flow import InstalledAppFlow

    if not os.path.exists(client_creds_path):
        logger.error(f"Client credentials file not found: {client_creds_path}")
        return False

    if not scopes:
        logger.error("At least one scope must be specified")
        return False

    # Resolve aliases to full URLs before creating the flow
    resolved_scopes = resolve_scopes(scopes)

    # Ensure the output directory exists
    output_dir = os.path.dirname(output_path)
    if output_dir:
        os.makedirs(output_dir, exist_ok=True)
        logger.debug(f"Ensured output directory exists: {output_dir}")

    logger.info(f"Requesting OAuth token for scopes: {', '.join(resolved_scopes)}")
    logger.info(f"Using client credentials: {client_creds_path}")
    logger.info(f"Output token file: {output_path}")

    try:
        flow = InstalledAppFlow.from_client_secrets_file(
            client_creds_path, resolved_scopes
        )
        creds = flow.run_local_server(port=0)
        logger.info("User authorization completed via browser.")

        with open(output_path, "w") as token_file:
            token_file.write(creds.to_json())
        logger.info(f"Token saved to {output_path}")

        return True
    except Exception as e:
        logger.error(f"Failed to complete OAuth flow: {e}")
        return False
