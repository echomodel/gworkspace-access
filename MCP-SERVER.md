# Google Workspace MCP Server (`gwsa-mcp`)

A **Model Context Protocol (MCP)** server that exposes Google Workspace data to AI assistants and agentic tools via the `gwsa` CLI.

## What is MCP?

The [Model Context Protocol](https://modelcontextprotocol.io/) is an open standard that enables AI assistants to securely connect to external data sources and tools. MCP allows LLMs to:

- **Read data** from your applications (emails, documents, spreadsheets)
- **Take actions** on your behalf (label emails, modify documents)
- **Maintain context** across conversations

By running the `gwsa-mcp` Server, you give AI assistants like Claude Desktop, Gemini CLI, and other MCP-compatible tools direct access to your Google Workspace data—enabling powerful workflows like:

- "Show me my unread emails from the last day"
- "Find all documents titled 'Project Phoenix'"
- "Add the 'Processed' label to this email"

## Features

### Tools (Actions)

| Tool | Description |
|------|-------------|
| `gmail_search` | Search for emails with a Gmail query |
| `gmail_read` | Read the content of a specific email |
| `gmail_label` | Add or remove labels from an email |
| `docs_list` | List Google Docs with a search query |
| `docs_create` | Create a new Google Doc |
| `docs_read` | Read the text content of a Google Doc |
| `docs_append` | Append text to a Google Doc |
| `docs_insert` | Insert text at a specific location in a Doc |
| `docs_replace` | Find and replace text in a Google Doc |

### Resources (Read-only Data)

This server primarily exposes its capabilities through tools, not static resources.

For detailed documentation, see the main project [README.md](./README.md).

## Quick Start

### Prerequisites

1. **`gwsa` CLI installed and configured**:
   ```bash
   pipx install git+https://github.com/krisrowe/gworkspace-access.git
   gwsa client import /path/to/client_secrets.json
   gwsa profiles add default
   gwsa profiles use default
   ```
   The MCP server uses your gwsa profiles for authentication. Without a configured profile, all tools will return: *"No active profile configured."*

2. **MCP Client**: Gemini CLI, Claude Code, or a similar MCP-compatible tool.

### Step 1: Verify gwsa is configured

Confirm you have an active profile before proceeding:

```bash
gwsa profiles list
# Should show at least one profile with an email address
```

If you see only the built-in `adc` profile or get errors, create a profile first with `gwsa profiles add`.

### Step 2: Register the Server with Gemini CLI

Register the `gwsa-mcp` server with your Gemini CLI client. This command makes the tool available globally for your user.

```bash
gemini mcp add gwsa gwsa-mcp --stdio --scope user
```

The server uses **stdio transport**, which means the Gemini client will automatically start and stop the `gwsa-mcp` process for each session. No manual server management or port configuration is needed.

### Step 3: Verify

Check the status to ensure the client can connect to the newly registered server.

```bash
gemini mcp list
```

You should see `gwsa` listed with a "Connected" status.

## Configuring MCP Clients

The recommended setup for both Gemini CLI and Claude is to use the **stdio transport**, which allows the client to manage the server's lifecycle automatically.

### Gemini CLI and Gemini Code Assist

The `gemini mcp add` command shown in the Quick Start is the only step needed. It registers the `gwsa-mcp` command globally for your user.

```bash
gemini mcp add gwsa gwsa-mcp --stdio --scope user
```

For more details on Gemini CLI configuration, see **[docs/GEMINI-CLI.md](./docs/GEMINI-CLI.md)**.

### Claude Code (CLI)

Quick setup (mounts your existing token config):

```bash
claude mcp add --scope user gwsa -- docker run -i --rm \
  -v ~/.config/gwsa:/root/.config/gwsa:ro \
  gwsa-mcp-server:latest python server-stdio.py
```

For detailed configuration options, scope levels, and troubleshooting, see **[docs/CLAUDE-CODE.md](./docs/CLAUDE-CODE.md)**.

### Other MCP Clients

For HTTP transport, connect to `http://localhost:8000/mcp` with the Docker container running.

For stdio transport, configure the client to execute:
```bash
docker run -i --rm -e GWSA_TOKEN="$TOKEN" gwsa-mcp-server:latest python server-stdio.py
```

## Local Development

Run without Docker for development:

```bash
# Install dependencies
pip install -e ".[mcp]"

# HTTP transport
uvicorn server:mcp_app --host 0.0.0.0 --port 8000

# Stdio transport
python server.py --stdio
```

## Transport Options

| Transport | Description | Use Case |
|-----------|-------------|----------|
| **HTTP** | Server runs persistently, clients connect via HTTP | Multiple clients, persistent connection |
| **Stdio** | Server starts/stops with each client session | Single client, automatic lifecycle |

## Local Development

The `pipx install -e .` command installs the server in editable mode. Any changes you make to the source code will be reflected the next time the Gemini client starts the `gwsa-mcp` process.

To test the server directly, you can run it with the `--stdio` flag:
```bash
gwsa-mcp --stdio
```

## Transport Options

| Transport | Description | Use Case |
|-----------|-------------|----------|
| **Stdio** | Server starts/stops with each client session | Recommended for Gemini CLI, Claude, and other clients that manage the tool's lifecycle. |
| **HTTP** | Server runs persistently, clients connect via HTTP | Useful for development or when multiple clients need to connect to a single, persistent server instance. |

## Troubleshooting

### Authentication Issues

**"No active profile configured" or credential errors:**
- Ensure you have created a profile with `gwsa profiles add` and activated it with `gwsa profiles use`.
- Check your active profile with `gwsa profiles current`.
- The `gwsa-mcp` server uses the same credentials as the `gwsa` CLI. If the CLI works, the server should too.

### Client Connection Issues

1. Verify the server is registered correctly: `gemini mcp list`
2. Run the server directly to check for errors: `gwsa-mcp --stdio`
3. Ensure `gwsa-mcp` is in your `PATH` (the `pipx` installation should handle this automatically).

## Architecture

The MCP server uses the same SDK and authentication logic as the CLI:

```
┌──────────────────┐     ┌──────────────────┐
│   Claude/Gemini  │     │       CLI        │
│   (MCP Client)   │     │      (gwsa)      │
└────────┬─────────┘     └────────┬─────────┘
         │                        │
         ▼                        ▼
┌──────────────────────────────────────────┐
│              GWSA SDK                    │
│    Profiles, Auth, Mail, Docs, Sheets    │
└──────────────────────────────────────────┘
```

This ensures consistent behavior and credential management across all entry points.

## Security Considerations

- **Credential Storage**: `gwsa-mcp` reads from the secure credential store at `~/.config/gworkspace-access/`. It never needs credentials passed to it directly.
- **Local only**: The server runs as a local process under your user account and does not expose any network ports by default.

## Limitations

The MCP server intentionally does **not** support certain operations that require interactive authentication or could be destructive:

| Operation | MCP Support | Workaround |
|-----------|-------------|------------|
| List profiles | ✓ `list_profiles` | - |
| Get active profile | ✓ `get_active_profile` | - |
| Switch profile | ✓ `switch_profile` | - |
| **Create profile** | ✗ | `gwsa profiles add <name>` |
| **Refresh/re-auth** | ✗ | `gwsa profiles refresh <name>` |
| **Rename profile** | ✗ | `gwsa profiles rename <old> <new>` |
| **Delete profile** | ✗ | `gwsa profiles delete <name>` |
| **Retrieve credentials** | ✗ | Not supported |

**Why these limitations?**

- **Create/Refresh** require an OAuth browser flow - interactive authentication cannot be performed via MCP
- **Rename/Delete** are destructive write operations that should require explicit user action via CLI
- **Credentials** are never exposed through MCP for security reasons

If the AI assistant needs a profile operation that isn't available, it should instruct the user to run the appropriate `gwsa profiles` CLI command.

## Related Documentation

- [Gemini CLI Setup](./docs/GEMINI-CLI.md) - Gemini CLI and Code Assist configuration
- [Main README](./README.md) - CLI usage and authentication setup
- [AUTHENTICATION.md](./AUTHENTICATION.md) - Detailed authentication guide
- [MCP Specification](https://modelcontextprotocol.io/) - Official MCP documentation
