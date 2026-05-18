# Gemini CLI & Code Assist Setup (`gwsa`)

This guide covers how to connect Gemini CLI and Gemini Code Assist (in VS Code) to your Google Workspace data using the `gwsa-mcp` server.

## Overview

The `gwsa-mcp` server uses **stdio transport**, which is the recommended integration method for Gemini CLI. This means the client manages the server's lifecycle automatically—starting it when a session begins and stopping it when the session ends.

This approach offers several advantages:
- **No Manual Server Management**: You don't need to start or stop a background process.
- **No Port Conflicts**: Communication happens over standard I/O, not network ports.
- **Automatic Lifecycle**: Ensures a clean state for every session.
- **Uses Existing `gwsa` Credentials**: The server reads from the same mcp-app user store populated by `gwsa-admin accounts add`. The default account on your profile governs every tool call.

## Quick Setup

This single command registers the `gwsa-mcp` server globally for your user, making it available in any Gemini CLI session, regardless of your current directory.

```bash
gemini mcp add gwsa gwsa-mcp stdio --user local --scope user
```

The `--user` flag pins this registration to one local-store user.
`local` is the default user key created by `gwsa-admin migrate`.
The key is an opaque local handle, **not a Google email** — the
Google account emails live inside the user's profile.

## How It Works

When you run a command like `gemini -t gwsa "show my unread mail"`, the Gemini client:
1.  Looks up the `gwsa` server in its configuration.
2.  Finds the registered command: `gwsa-mcp stdio --user local`.
3.  Executes that command, starting a new `gwsa-mcp` process.
4.  Communicates with the process over stdin/stdout.
5.  Terminates the process when the interaction is complete.

## Verifying the Setup

You can see all registered MCP servers, including `gwsa`, by running:

```bash
gemini mcp list
```

A successful connection will show a `✓` and "Connected" status next to the `gwsa` entry.

## VS Code Integration (Gemini Code Assist)

Gemini Code Assist in VS Code uses the same user-level configuration as the Gemini CLI. Once you have registered the server using the `gemini mcp add --scope user` command, it will be **automatically available** in VS Code.

To use it, open the chat in the VS Code sidebar and use the `@gwsa` handle to direct your requests to the Google Workspace tools.

## Troubleshooting

- **"Server not found: gwsa"**:
  - Run `gemini mcp list` to check if the server is registered.
  - If it's missing, run the `gemini mcp add` command again.

- **Connection Errors**:
  - Ensure `gwsa-mcp` is in your `PATH`. The `pipx install` should handle this. You can verify by running `which gwsa-mcp`.
  - Confirm gwsa has at least one account configured: `gwsa-admin accounts list`. If empty, follow the [README quick start](../README.md#quick-start-one-google-account).

- **"Unknown argument: scope"**:
  - You may have an older version of Gemini CLI. Ensure your client is up to date. The `--scope` flag is the correct way to create a user-level (global) registration.

