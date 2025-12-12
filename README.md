# Google Workspace Access CLI (`gwsa`)

This project provides a Command Line Interface (CLI) tool, `gwsa`, to search and manage your Gmail account using the Google Gmail API. It centralizes all environment and credential setup within a dedicated `gwsa setup` command.

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

## Quick Start (Single Command)

```bash
pip install git+https://github.com/krisrowe/gworkspace-access.git && gwsa setup
```

That's it! The `gwsa setup` command will guide you through the rest.

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

> **Important: Backing Up Your Credentials**
> You can only download the `credentials.json` file once. The `gwsa setup` command (run in a later step) will automatically back up this file as a secret in Google Secret Manager. This makes it easy to set up `gwsa` on a new workstation in the future without having to generate new credentials.

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

### 4. Run Initial Setup

Now, run the central `gwsa setup` command.

```bash
gwsa setup
```

This is the most important step and must be run before any other `gwsa` command. See the section below for a detailed explanation of what it does.

## What `gwsa setup` Does

The `gwsa setup` command is the heart of this tool's configuration. It must be run first because it performs several critical actions to bootstrap the environment:

1.  **Ensures a Project ID is Set**: It finds the Google Cloud project ID using either the labeled project (recommended) or the `.env` file.
2.  **Enables Cloud APIs**: It automatically enables the Gmail API and Secret Manager API on your project if they are not already active.
3.  **Secures Client Credentials**: It checks for `credentials.json` and synchronizes it with Google Secret Manager, creating a secure backup.
4.  **Manages User Authorization**: It triggers a browser-based OAuth 2.0 flow to get your permission for the tool to access your Google account. This interactive sign-in process is what generates the user-specific `user_token.json` file.
5.  **Refreshes Tokens**: On subsequent runs, it will automatically refresh your user token if it has expired.

Without running `setup` first, the tool has no project context and lacks the necessary client and user credentials to communicate with Google APIs.

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

### Setting Up a New Workstation

Once you have completed the first-time setup, configuring `gwsa` on another machine is much simpler.

1.  Clone this repository to your new machine.
2.  Ensure the [Prerequisites](#prerequisites) (Google Cloud CLI, Python) are met.
3.  Install the tool: `pip install -e .`
4.  Run the setup command:
    ```bash
    gwsa setup
    ```
That's it. Because you already have a labeled project and your client credentials are saved in Secret Manager, the script will automatically:
- Discover your Google Cloud project.
- Create the `.env` file with the correct project ID.
- Download `credentials.json` from Google Secret Manager.
- Initiate the browser flow to get a fresh `user_token.json` for the new machine.

### Re-authenticating or Switching Users

If you need to regenerate your user token, switch to a different Google account, or fix a corrupted `user_token.json`, you can force a new authentication flow by using the `--new-user` flag with the `setup` command. This will delete the existing token and trigger the browser sign-in process again.

```bash
gwsa setup --new-user
```

### Using Custom Credentials Path

If you have a `credentials.json` file in a non-standard location, you can specify its path using the `--client-creds` flag:

```bash
gwsa setup --client-creds /path/to/credentials.json
```

The specified credentials file will be copied to the configuration directory for use by the tool.

## Credential Storage

All credentials are stored centrally in `~/.config/gworkspace-access/` regardless of where the `gwsa` tool is installed or which directory you run the command from. This includes:

- **`credentials.json`**: Your OAuth 2.0 client credentials (downloaded from Google Cloud Console)
- **`user_token.json`**: Your user-specific authorization token (generated during the OAuth flow)

This centralized storage makes it easy to use `gwsa` from any directory on your machine.

---

## Authentication & Account Compatibility

Different Google account types have varying compatibility with authentication methods. See **[AUTHENTICATION.md](AUTHENTICATION.md)** for detailed guidance on:

- **Authentication methods**: OAuth User Token, Application Default Credentials (ADC), Service Accounts
- **Account compatibility**: Workspace, regular Gmail, Gmail with security keys
- **Advanced Protection Program (APP)**: Limitations and workarounds
- **Troubleshooting**: Common errors and solutions

**Quick summary:**

| Account Type | Recommended Method |
|--------------|-------------------|
| Google Workspace | ADC or OAuth Token |
| Regular Gmail | Either works |
| Gmail + security keys | OAuth Token (ADC may be blocked) |
| Gmail + APP | OAuth Token created *before* enabling APP |

For information about API quotas, billing, and the "No project ID" warning, see **[QUOTAS.md](QUOTAS.md)**.

---

## Future Enhancements

While `gwsa` currently functions as a CLI tool, the architecture is designed with a broader vision in mind: **a centralized API service** that can be consumed by any application, not just command-line users.

### The Problem with CLI-Only Access

Projects that need programmatic access to Google Workspace APIs (like a Gmail automation service) currently must:
- Shell out to CLI commands, which is fragile and inefficient
- Manage their own OAuth credentials and token refresh logic
- Handle the complexity of Google's OAuth client verification process
- Duplicate credential management across multiple deployments

### The API Vision

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