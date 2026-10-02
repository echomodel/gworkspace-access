# Antigravity CLI Setup (`gwsa`)

How to connect Antigravity CLI (`agy`) to your Google Workspace data with
the `gwsa-mcp` server.

## Overview

`gwsa-mcp` runs over **stdio**: `agy` starts the server when it needs it and
stops it afterwards. There is no background process to manage and no port to
configure. The server reads the same mcp-app user store that
`gwsa-admin accounts add` populates; the default account on your profile
governs every tool call unless the agent passes `account`.

## Register

```bash
agy mcp add gwsa -- gwsa-mcp stdio --user local
```

- The `--` is required: everything after it is the server command, and
  `--user` would otherwise be read as an `agy` flag.
- The registration is user-level (`~/.gemini/config/mcp_config.json`), so
  `gwsa` is available in every `agy` session.
- `--user local` pins the server to one local-store user. `local` is the
  default user key created by `gwsa-admin migrate`; it is an opaque local
  handle, **not a Google email**.

A project can instead declare servers in `.agents/mcp_config.json` at its
root, in the same JSON shape; `agy` loads them for sessions in that folder.

## Verify

```bash
agy mcp list
```

`gwsa` should be listed as `stdio` and `enabled`. (`agy mcp list` shows the
user-level registrations only, not a project's `.agents/mcp_config.json`.)

## Tool permissions

`agy` asks before running an MCP tool. In headless runs (`agy -p "…"`) it
cannot ask, so MCP tool calls are denied unless allowed by a rule in
`~/.gemini/antigravity-cli/settings.json`:

```json
{"permissions": {"allow": ["mcp(gwsa/*)"]}}
```

Narrow the rule to specific tools (`mcp(gwsa/read_doc)`) if you want
headless runs limited to reads.

## Troubleshooting

- **Tools missing:** run `agy mcp list`; if `gwsa` is absent, run the
  `agy mcp add` command again. `agy mcp remove gwsa` removes it.
- **Server fails to start:** confirm `gwsa-mcp` is on your `PATH`
  (`which gwsa-mcp`) and that gwsa has an account configured
  (`gwsa-admin accounts list`; if empty, follow the
  [README quick start](../README.md#quick-start-one-google-account)).
- **"a tool required the "mcp" permission that headless mode cannot prompt
  for":** add the allow rule under "Tool permissions".
