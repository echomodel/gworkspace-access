# Claude Code CLI Setup (`gwsa`)

This guide covers how to connect Claude Code CLI to your Google Workspace data using the `gwsa-mcp` server.

## Overview

The `gwsa-mcp` server uses **stdio transport**, which is the recommended integration method for Claude Code CLI. This means the client manages the server's lifecycle automatically—starting it when a session begins and stopping it when the session ends.

This approach offers several advantages:
- **No Manual Server Management**: You don't need to start or stop a background process.
- **No Port Conflicts**: Communication happens over standard I/O, not network ports.
- **Automatic Lifecycle**: Ensures a clean state for every session.
- **Uses Existing `gwsa` Credentials**: The server reads from the same mcp-app user store populated by `gwsa-admin accounts add`. The default account on your profile governs every tool call.

## Quick Setup

This single command registers the `gwsa-mcp` server globally for your user, making it available in any Claude Code CLI session, regardless of your current directory. It also includes the necessary `--scope user` flag to ensure the tools are available to Claude.

```bash
claude mcp add --scope user gwsa -- gwsa-mcp stdio --user local
```

The `--user` flag pins this registration to one local-store user.
`local` is the default user key created by `gwsa-admin migrate`.
The key is an opaque local handle, **not a Google email** — the
Google account emails live inside the user's profile.

## How It Works

When you interact with Claude Code (e.g., in a workspace with the `gwsa` tool enabled), the Claude client:
1.  Looks up the `gwsa` server in its configuration.
2.  Finds the registered command: `gwsa-mcp stdio --user local`.
3.  Executes that command, starting a new `gwsa-mcp` process.
4.  Communicates with the process over stdin/stdout.
5.  Terminates the process when the interaction is complete.

## Verifying the Setup

You can see all registered MCP servers for Claude by running (note: the exact command may vary based on Claude's CLI version):

```bash
claude mcp list
```

A successful connection should show `gwsa` listed.

## Troubleshooting

- **"Server not found: gwsa"**:
  - Run the `claude mcp add` command again.

- **Connection Errors**:
  - Ensure `gwsa-mcp` is in your `PATH`. The `pipx install` should handle this. You can verify by running `which gwsa-mcp`.
  - Confirm gwsa has at least one account configured: `gwsa-admin accounts list`. If empty, follow the [README quick start](../README.md#quick-start-one-google-account).

