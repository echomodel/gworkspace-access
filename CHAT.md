# Google Chat Integration

This document describes the setup and usage of the Google Chat features in `gwsa`.

## Overview

The `gwsa` tool provides CLI commands and MCP tools to interact with Google Chat.
*   **List Spaces**: See available rooms and DMs.
*   **List Members**: See who is in a space.
*   **Search Messages**: Search for text across message history in a space.

## Prerequisites & Setup

Using the Google Chat API with user credentials (ADC) requires specific setup steps, especially for Google Workspace accounts.

### 1. Google Cloud Project

You must have a Google Cloud Project to enable the required APIs.

### 2. Enable APIs

Enable the following APIs in your Google Cloud Project:
*   **Google Chat API** (`chat.googleapis.com`)
*   **Google People API** (`people.googleapis.com`) - *Required for resolving User IDs to names.*

### 3. Configure OAuth Consent Screen

Ensure your OAuth consent screen is configured for your project. For internal use, "Internal" user type is recommended.

### 4. Create a "Chat App" (Workspace Only)

**Crucial Step:** To use the Chat API with user credentials, you must configure a "Chat App" in the Google Cloud Console.
1.  Go to **APIs & Services** > **Google Chat API** > **Configuration**.
2.  **App Name**: Enter a name (e.g., "GWSA CLI").
3.  **Avatar URL**: Optional.
4.  **Description**: Optional.
5.  **Functionality**: Select **"App URL"** (you don't need to enter a valid URL if you are only using the API, but the field might be required; `https://localhost` is fine).
6.  **Connection Settings**: You can leave these as default or minimal.
7.  **Visibility**: Check **"Join any space"** or ensure it's available to your users.
8.  **Save**.

*Note: This step effectively "registers" your project as a valid Chat application, allowing it to make API calls on behalf of users.*

### 5. Authentication Scopes

The `gwsa` tool automatically requests the following scopes when you run `gwsa setup` or `gwsa profiles refresh`:

*   `https://www.googleapis.com/auth/chat.spaces.readonly`: To list spaces.
*   `https://www.googleapis.com/auth/chat.memberships.readonly`: To list members.
*   `https://www.googleapis.com/auth/chat.messages.readonly`: To read and search messages.
*   `https://www.googleapis.com/auth/directory.readonly`: To resolve User IDs to names via People API.

### 6. Quota Project (ADC)

When using Application Default Credentials (ADC), the Chat API requires a "Quota Project" to be set.
If you see `PERMISSION_DENIED` errors mentioning a quota project:

```bash
gcloud auth application-default set-quota-project YOUR_PROJECT_ID
```

## Usage

### CLI Workflow Examples

Here is a common workflow for investigating a chat conversation:

1.  **List Spaces** to find a specific room or to filter by type:
    ```bash
    # List all spaces
    gwsa chat spaces list
    # Output:
    # spaces/AAAA... - Project Alpha Team
    # spaces/BBBB... - Lunch Planning (GROUP_CHAT)
    # spaces/CCCC... - Unknown (DIRECT_MESSAGE)

    # List only Direct Messages
    gwsa chat spaces list --type=DIRECT_MESSAGE

    # List only Group Chats
    gwsa chat spaces list --type=GROUP_CHAT
    ```

2.  **List Members** to see who is in the "Project Alpha Team" (spaces/AAAA...):
    ```bash
    gwsa chat spaces members spaces/AAAA...
    # Output:
    # Alice Smith (users/123...)
    # Bob Jones (users/456...)
    ```

3.  **Search Messages** for a specific topic (e.g., "deadline"):
    ```bash
    gwsa chat messages search spaces/AAAA... "deadline"
    # Output:
    # [2025-12-15T10:00:00Z] Alice Smith: The deadline is next Friday.
    ```

4.  **List Recent Messages** to see the context around that search result:
    ```bash
    gwsa chat messages list spaces/AAAA... --limit 50
    ```

### MCP Tools

The following tools are available to agents:

The following tools are available to agents:
*   `list_chat_spaces`
*   `list_chat_members`
*   `list_chat_messages`
*   `search_chat_messages`

## Troubleshooting

*   **"Unknown" Names**: Ensure the **People API** is enabled and you have re-authenticated to grant the `directory.readonly` scope.
*   **403 Forbidden (Quota Project)**: Run the `gcloud auth application-default set-quota-project` command.
*   **403 Forbidden (Chat App)**: Ensure you have configured the Chat API "Configuration" tab in the Cloud Console.
