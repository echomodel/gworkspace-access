import logging
import json
import base64 # Imported here as it's used within the function
from ..mail import _get_gmail_service # Changed to relative import

logger = logging.getLogger(__name__)

def read_message(message_id: str):
    """
    Retrieves the full content of a specific Gmail message.
    Returns a dictionary containing message details, including raw body and labels.
    """
    try:
        service = _get_gmail_service()
        logger.info(f"Retrieving message with ID: {message_id}")

        # Get the message in full format
        msg = service.users().messages().get(userId='me', id=message_id, format='full').execute()

        # Extract relevant parts
        headers = msg['payload']['headers']
        subject = next((header['value'] for header in headers if header['name'] == 'Subject'), 'N/A')
        from_addr = next((header['value'] for header in headers if header['name'] == 'From'), 'N/A')
        to_addr = next((header['value'] for header in headers if header['name'] == 'To'), 'N/A')
        date = next((header['value'] for header in headers if header['name'] == 'Date'), 'N/A')
        
        # Get the body. Emails can have both text/plain and text/html parts.
        # Extract both if available.
        text_body = None
        html_body = None

        def extract_body_part(payload_part):
            """Extract and decode body content from a MIME part."""
            if 'body' in payload_part and 'data' in payload_part['body']:
                encoded_data = payload_part['body']['data']
                return base64.urlsafe_b64decode(encoded_data).decode('utf-8')
            return None

        # Check for multipart message with alternative parts
        if 'parts' in msg['payload']:
            for part in msg['payload']['parts']:
                mime_type = part.get('mimeType', '')

                if mime_type == 'text/plain' and text_body is None:
                    text_body = extract_body_part(part)
                elif mime_type == 'text/html' and html_body is None:
                    html_body = extract_body_part(part)

                # Also check nested parts (e.g., multipart/alternative inside multipart/related)
                if 'parts' in part:
                    for subpart in part['parts']:
                        submime_type = subpart.get('mimeType', '')
                        if submime_type == 'text/plain' and text_body is None:
                            text_body = extract_body_part(subpart)
                        elif submime_type == 'text/html' and html_body is None:
                            html_body = extract_body_part(subpart)

        # Fallback: check if there's a simple body at top level
        elif 'body' in msg['payload'] and 'data' in msg['payload']['body']:
            text_body = extract_body_part(msg['payload'])

        # Structure body as object with text and html fields
        body = {
            "text": text_body,
            "html": html_body
        }

        message_details = {
            "id": message_id,
            "subject": subject,
            "from": from_addr,
            "to": to_addr,
            "date": date,
            "snippet": msg.get('snippet', ''),
            "body": body,
            "labelIds": msg.get('labelIds', []),
            "raw": json.dumps(msg, indent=2)
        }

        logger.debug(f"Successfully retrieved message: '{subject}' from '{from_addr}' to '{to_addr}'")
        return message_details

    except HttpError as error:
        logger.error(f"An error occurred with the Gmail API while reading message {message_id}: {error}")
        raise
    except FileNotFoundError as e:
        logger.error(f"Missing required file: {e}")
        raise
    except Exception as e:
        logger.critical(f"An unexpected error occurred during message read for ID {message_id}: {e}", exc_info=True)
        raise
