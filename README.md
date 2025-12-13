# Google Workspace Access CLI (`gwsa`)

A CLI tool for managing Gmail, Google Docs, and Sheets via the Google Workspace APIs. Supports multiple Google account profiles for easy switching between identities.

## Prerequisites

Before you begin, ensure you have the following installed and configured:

1.  **Google Cloud CLI (`gcloud`)**:
    *   Install the `gcloud` CLI: [https://cloud.google.com/sdk/docs/install](https://cloud.google.com/sdk/docs/install)
    *   Initialize `gcloud` and authenticate:
        ```bash
        gcloud init
        gcloud auth application-default login
        ```
2.  **Python 3 (Recommended: 3.11 or higher)**:
    *   Ensure Python 3 is installed. For optimal compatibility and to avoid potential issues with Google Cloud client libraries, Python 3.11 or higher is recommended.

    *   **Upgrading Python with `pyenv` (Recommended)**:
        `pyenv` allows you to easily switch between multiple Python versions.
        If you don't have `pyenv` installed, follow its official installation guide: [https://github.com/pyenv/pyenv#installation](https://github.com/pyenv/pyenv#installation)

        Once `pyenv` is installed, you can upgrade Python and set it globally with:
        ```bash
        pyenv install 3.11
        pyenv global 3.11
        python3 --version # Verify the active Python version
        ```
3.  **`pip`**:
    *   Python's package installer.

## Quick Start

```bash
# Install
pipx install git+https://github.com/krisrowe/gworkspace-access.git

# Import your OAuth client credentials (one-time)
gwsa client import /path/to/client_secrets.json

# Create your first profile (opens browser for OAuth)
gwsa profiles add default

# Activate it
gwsa profiles use default

# Verify
gwsa status
```

This installs two commands:
- **`gwsa`** - The CLI tool for direct command-line use
- **`gwsa-mcp`** - The MCP server for AI assistant integration (see [MCP Server](#mcp-server-for-ai-assistants))

> **Note:** If you don't have `pipx`, you can use `pip install` instead, though `pipx` is recommended for CLI tools as it creates isolated environments.

### Upgrading

To upgrade to the latest version:

```bash
pipx upgrade gwsa
```

Or with pip:
```bash
pip install --upgrade git+https://github.com/krisrowe/gworkspace-access.git
```

> **Important:** Without `--upgrade`, pip will skip installation if any version is already installed, even if a newer version is available.

---

## First-Time Setup

This process walks through installing the `gwsa` tool and configuring it for the first time.

### 1. Choose a Project Identification Method

The `gwsa` tool needs to know which Google Cloud Project to use. You have two options:

**Option A: Project Labels (Recommended)**

Label your Google Cloud project. The setup script will automatically discover and save the project ID for you. This is the easiest method and simplifies setting up other workstations later.

```bash
gcloud alpha projects update YOUR_GCP_PROJECT_ID --update-labels=gws-access=default
```
> Replace `YOUR_GCP_PROJECT_ID` with your actual project ID.

**Option B: Manual `.env` Configuration**

If you prefer not to label your project, you can create a file named `.env` in the root of this directory and add your project ID to it.

```dotenv
# .env
WORKSPACE_ACCESS_PROJECT="YOUR_GCP_PROJECT_ID"
```

### 2. Generate and Secure Client Credentials

Next, you need to get OAuth 2.0 client credentials from the Google Cloud Console.

1.  Navigate to your project in the [Google Cloud Console](https://console.developers.google.com/).
2.  Ensure the **Gmail API** and **Secret Manager API** are enabled.
3.  Go to "APIs & Services" -> "Credentials".
4.  Click "Create Credentials" -> "OAuth client ID".
5.  Select **"Desktop app"** as the Application type and give it a name.
6.  Click "Create". On the next screen, click **"Download JSON"**.
7.  Rename the downloaded file to `credentials.json` and place it in the root of this project directory.

> **Important:** You can only download the `credentials.json` file once. Keep a backup in a secure location.

### 3. Install the CLI Tool

Install the `gwsa` tool and its dependencies using `pip`.

```bash
# Recommended for development (your code changes are reflected immediately)
pip install -e .
```

> **Troubleshooting `externally-managed-environment` error:**
> If you encounter this error, it means your system's Python distribution prevents direct package installation. The recommended solution is to use `pipx`, which installs CLI tools in isolated environments.
>
> ```bash
> # First, ensure pipx is installed
> python3 -m pip install --user pipx
> python3 -m pipx ensurepath
>
> # Then, install the tool in editable mode using pipx
> pipx install -e .
> ```

```bash
# For a regular installation
# pip install .
```

### 4. Import Client Credentials and Create a Profile

Import your OAuth client credentials (one-time setup):

```bash
gwsa client import /path/to/credentials.json
```

Then create your first profile:

```bash
gwsa profiles add default
```

This opens a browser for Google OAuth consent. After authenticating, activate the profile:

```bash
gwsa profiles use default
```

Verify everything is working:

```bash
gwsa status
```

For detailed profile management, see **[PROFILES.md](PROFILES.md)**.

## Using the `gwsa` CLI Tool

Once setup is complete, you can use the `gwsa` tool. All `mail` sub-commands output their results in JSON format, allowing for easy parsing and integration with other tools like `jq`.

**Search for Emails:**
```bash
gwsa mail search "after:2025-11-27 -label:Processed"
```

**Pagination:**
The search command supports Gmail API pagination for handling large result sets. By default, the tool returns 25 results per page.

Control the page size with `--max-results`:
```bash
gwsa mail search label:Inbox --max-results 50
```
Note: `--max-results` reflects Gmail API terminology. Maximum allowed is 500, though larger values may be slower due to body extraction overhead.

Fetch subsequent pages using the `--page-token` from the previous response:
```bash
# First page returns metadata with nextPageToken in the logs
gwsa mail search label:Inbox --max-results 20
# Output includes: "More pages available. Use --page-token XXXXXX to fetch next page"

# Fetch the next page using the token
gwsa mail search label:Inbox --max-results 20 --page-token XXXXXX
```

**Read a Specific Email:**
```bash
gwsa mail read MESSAGE_ID
```
> Replace `MESSAGE_ID` with an ID from the search results.

**Label an Email:**
To add a label:
```bash
gwsa mail label MESSAGE_ID MyCustomLabel
```
To remove a label:
```bash
gwsa mail label MESSAGE_ID MyCustomLabel --remove
```

**Debugging:**
You can set the `LOG_LEVEL` environment variable to `DEBUG` to get detailed logging output.
```bash
LOG_LEVEL=DEBUG gwsa mail search "after:2025-11-27"
```

---
## Advanced Usage

### Multiple Profiles

Create additional profiles for different Google accounts:

```bash
gwsa profiles add work
gwsa profiles add personal
```

Switch between them:

```bash
gwsa profiles use work
gwsa profiles use personal
```

List all profiles:

```bash
gwsa profiles list
```

### Re-authenticating

If credentials expire or become invalid:

```bash
gwsa profiles refresh <profile-name>
gwsa profiles refresh adc  # For ADC profile
```

### Setting Up a New Workstation

1. Install the tool: `pipx install git+https://github.com/krisrowe/gworkspace-access.git`
2. Copy your `client_secrets.json` to the new machine
3. Import credentials: `gwsa client import /path/to/client_secrets.json`
4. Create a profile: `gwsa profiles add default`
5. Activate it: `gwsa profiles use default`

## Credential Storage

All credentials are stored in `~/.config/gworkspace-access/`:

```
~/.config/gworkspace-access/
├── config.yaml           # Active profile setting
├── client_secrets.json   # OAuth client credentials
└── profiles/
    └── <profile-name>/
        ├── user_token.json  # OAuth token
        └── profile.yaml     # Metadata
```

This centralized storage makes it easy to use `gwsa` from any directory.

---

## Authentication & Profiles

See **[PROFILES.md](PROFILES.md)** for complete documentation on:

- **Profile management**: Creating, switching, refreshing, deleting profiles
- **Profile states**: Valid, stale, unvalidated - what they mean
- **Error recovery**: Common issues and how to fix them
- **Edge cases**: Deleted profiles, offline switching, etc.

See **[AUTHENTICATION.md](AUTHENTICATION.md)** for initial OAuth/ADC setup:

- **OAuth setup**: Creating client_secrets.json, first-time authentication
- **ADC setup**: Using gcloud credentials, quota project configuration
- **Account compatibility**: Workspace, Gmail, security keys, APP

**Quick summary:**

| Account Type | Recommended Method |
|--------------|-------------------|
| Google Workspace | ADC or OAuth Token |
| Regular Gmail | Either works |
| Gmail + security keys | OAuth Token (ADC may be blocked) |
| Gmail + APP | OAuth Token created *before* enabling APP |

For information about API quotas, billing, and the "No project ID" warning, see **[QUOTAS.md](QUOTAS.md)**.

---

## MCP Server for AI Assistants

The `gwsa` package includes an MCP (Model Context Protocol) server that exposes Google Workspace operations to AI assistants like Claude and Gemini.

```bash
# The MCP server is included with gwsa - no separate install needed
gwsa-mcp  # Starts the MCP server (typically called by your AI assistant)
```

For configuration instructions, see **[MCP-SERVER.md](MCP-SERVER.md)**.

---

## Future Enhancements

### Google Drive Integration

Planned additions to the CLI and MCP server:

- **`drive_search`** - Search for files/folders by name or query
- **`drive_list_folder`** - List contents of a folder
- **`drive_create_folder`** - Create new folders
- **`drive_upload`** / **`drive_download`** - File transfers

This will enable workflows like "Upload this report to my Project Reports folder" directly from AI assistants.

### Centralized API Service

While `gwsa` currently functions as a CLI tool, the architecture is designed with a broader vision in mind: **a centralized API service** that can be consumed by any application, not just command-line users.

Projects that need programmatic access to Google Workspace APIs (like a Gmail automation service) currently must:
- Shell out to CLI commands, which is fragile and inefficient
- Manage their own OAuth credentials and token refresh logic
- Handle the complexity of Google's OAuth client verification process
- Duplicate credential management across multiple deployments

#### The API Vision

The goal is to host `gwsa` as a **REST API on Google Cloud Run**, providing:

1. **Centralized Credential Management** - OAuth client credentials and token refresh handled in one place, not scattered across consuming applications
2. **Simplified Authentication** - Clients authenticate to the API using Google Cloud identity tokens (easily acquired from any GCP environment), not OAuth flows
3. **No Client Verification Required** - Google's OAuth client verification only applies to the hosted service, not to every consuming application
4. **User Authentication Without OAuth Complexity** - Consuming apps authenticate users through Cloud Run's built-in IAM/identity mechanisms, entirely under our control
5. **Full Workspace API Coverage** - Once the pattern is established for Gmail, it extends naturally to Calendar, Drive, Docs, and the entire Google Workspace suite

### Authentication Model

```
┌─────────────────┐     Google Identity Token      ┌─────────────────┐
│  Consuming App  │  ─────────────────────────────▶│   gwsa API      │
│  (gmail-manager)│                                │  (Cloud Run)    │
└─────────────────┘                                └────────┬────────┘
                                                           │
                                                   OAuth 2.0 (managed)
                                                           │
                                                           ▼
                                                   ┌─────────────────┐
                                                   │  Google APIs    │
                                                   │  (Gmail, etc.)  │
                                                   └─────────────────┘
```

- **Consuming applications** authenticate to the API using Google Cloud identity tokens - no OAuth dance, no client secrets, no token refresh to manage
- **The API service** handles all OAuth complexity internally - client credentials stored in Secret Manager, automatic token refresh, proper scope management
- **User context** is derived from the authenticated identity, not from per-app credential storage

### SDK as a Thin Client

With a stable API in place, an SDK becomes a thin HTTP client rather than a credential-management library:

```python
# Future SDK usage - no credentials to manage
from gwsa import GwsaClient

client = GwsaClient()  # Auto-discovers identity from environment
emails = client.mail.search("after:2024-01-01 label:Inbox")
```

The SDK would:
- Automatically acquire identity tokens from the runtime environment (Cloud Run, GCE, local `gcloud` auth)
- Provide typed interfaces to the API
- Handle retries and error mapping
- Remain lightweight since all credential complexity lives server-side

### Operational Benefits

Centralizing on a hosted API provides:

- **Single point of credential rotation** - Update OAuth credentials once, not in every deployment
- **Unified audit logging** - All API access flows through one service
- **Consistent token refresh** - No more expired token bugs in consuming apps
- **Easier compliance** - OAuth client verification and consent screens managed centrally
- **Horizontal scaling** - Cloud Run handles load balancing and scaling automatically

This approach transforms Google Workspace API access from a per-application burden into a shared, managed service.

---