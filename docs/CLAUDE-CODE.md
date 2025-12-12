# Claude Code CLI Setup (`gwsa`)

This guide covers how to connect Claude Code CLI to your Google Workspace data using the `gwsa-mcp` server.

## Overview

The `gwsa-mcp` server uses **stdio transport**, which is the recommended integration method for Claude Code CLI. This means the client manages the server's lifecycle automatically—starting it when a session begins and stopping it when the session ends.

This approach offers several advantages:
- **No Manual Server Management**: You don't need to start or stop a background process.
- **No Port Conflicts**: Communication happens over standard I/O, not network ports.
- **Automatic Lifecycle**: Ensures a clean state for every session.
- **Uses Existing `gwsa` Config**: The server automatically uses the active profile and credentials from your `gwsa` CLI setup.

## Quick Setup

This single command registers the `gwsa-mcp` server globally for your user, making it available in any Claude Code CLI session, regardless of your current directory. It also includes the necessary `--scope user` flag to ensure the tools are available to Claude.

```bash
claude mcp add --scope user gwsa -- gwsa-mcp --stdio
```

## How It Works

When you interact with Claude Code (e.g., in a workspace with the `gwsa` tool enabled), the Claude client:
1.  Looks up the `gwsa` server in its configuration.
2.  Finds the registered command: `gwsa-mcp --stdio`.
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
  - Test your main `gwsa` configuration by running a command like `gwsa profiles current`. If the CLI isn't configured, the MCP server won't work either. Follow the setup instructions in the main [README.md](./README.md).

