# MCP Server (`gwsa-mcp`)

`gwsa-mcp` is a [Model Context Protocol](https://modelcontextprotocol.io/)
server that exposes Google Workspace operations to AI assistants. It's
installed alongside `gwsa` (see [README](README.md#install)) and uses
the same credentials managed by `gwsa-admin`.

## Prerequisites

You must have a gwsa account configured before registering the MCP
server. The MCP server reads credentials from the mcp-app user store
populated by `gwsa-admin accounts add`. Without that, every tool call
returns an authentication error.

Walk through the [README quick start](README.md#quick-start-one-google-account)
first. Confirm with:

```bash
gwsa-admin accounts list
```

If you have at least one account listed, the MCP server has what it
needs.

## Transport

`gwsa-mcp` uses **stdio**. The MCP client starts the process when a
session begins and terminates it when the session ends — no port
allocation, no persistent server, no manual lifecycle management.

HTTP transport (for cloud deployments) is part of Phase 2; see
[Cloud Multi-User Architecture](docs/CLOUD-MULTI-USER.md) §8.

## Registering with clients

Every registration must include `stdio --user KEY`. The key is an
opaque local-store handle, **not a Google email** — the Google
account emails live on each `GoogleAccount` inside the user's
profile. `gwsa-admin migrate` creates a single user keyed `local`
by default.

### Claude Code

```bash
claude mcp add --scope user gwsa -- gwsa-mcp stdio --user local
claude mcp list                                          # verify
```

`--scope user` (the first one — Claude's own flag) makes `gwsa`
available in every Claude Code session on this machine, not just
the current project. Detailed config options and troubleshooting
are in [Claude Code Configuration](docs/CLAUDE-CODE.md).

### Gemini CLI / Gemini Code Assist

```bash
gemini mcp add gwsa gwsa-mcp stdio --user local --scope user
gemini mcp list                                          # verify
```

A successful registration shows the server with a `Connected` status.
Detailed config in [Gemini CLI Configuration](docs/GEMINI-CLI.md).

### Other MCP clients

Configure the client to execute `gwsa-mcp stdio --user local` (or
the user key you chose when migrating). The binary is on `$PATH`
after `pipx install`.

## Tool inventory

29 tools across four domains, one module per Google API. mcp-app
auto-discovers public async functions from each module:

- **`gwsa.mcp.tools.mail`** (10): search_emails, read_email,
  add_email_label, remove_email_label, list_email_labels,
  send_email, reply_email, create_email_draft,
  download_email_attachment, get_email_thread
- **`gwsa.mcp.tools.docs`** (6): list_docs, create_doc, read_doc,
  append_to_doc, insert_in_doc, replace_in_doc
- **`gwsa.mcp.tools.drive`** (7): drive_list_folder,
  drive_create_folder, drive_upload, drive_update, drive_download,
  drive_find_folder, drive_search_folders
- **`gwsa.mcp.tools.chat`** (6): list_chat_spaces, list_chat_members,
  list_chat_messages, search_chat_messages,
  get_recent_direct_messages, get_recent_group_chats

Sheets is CLI-only today (`gwsa sheets ...`); MCP coverage is
pending. The composition root in `gwsa/__init__.py` wires the four
modules into `App(tools_modules=[...])`.

## Account selection

The MCP server runs in stdio mode as one human (you). Credentials
are resolved from your mcp-app user record. Within that record, the
**default account** (set with `gwsa-admin accounts use <name>`) is
used implicitly.

Per-call account override at the tool level is planned but not yet
wired on the migrated tools; for now, the default account governs
every tool call. To temporarily use a different account, run
`gwsa-admin accounts use <name>` before starting the session.

## Troubleshooting

**"No user configured" or "no accounts" errors:** the gwsa account
store is empty. Run `gwsa-admin connect local` and
`gwsa-admin accounts add ...` (or `gwsa-admin migrate` if you used
gwsa before the mcp-app migration). See
[README quick start](README.md#quick-start-one-google-account).

**"This token was issued by gcloud's well-known OAuth client..."**:
the account was added without a quota project. Re-add with
`--quota-project YOUR_GCP_PROJECT`, or set it on the underlying blob
with `gcloud auth application-default set-quota-project`.

**Refresh-token expired during a tool call:** re-acquire the token
(`gwsa-admin acquire-token ...`) and replace the account on the
profile. See README troubleshooting for the full sequence.

**Client connection issues:** run the server directly to confirm
it boots: `gwsa-mcp stdio --user local` (use the user key you
migrated with) and check stderr for messages. Confirm the binary
is on `$PATH` (`which gwsa-mcp`); a `pipx` install places it
there automatically.

## Security

- **Credentials never travel to the MCP client.** The server reads
  them from the local user store on its own.
- **Local process only.** Stdio means no network ports, no remote
  exposure.
- **One identity per session.** The server serves exactly the gwsa
  user whose store it's reading from. There is no in-session
  identity switching.

## Related

- [README](README.md) — install, account setup, daily usage.
- [Claude Code Configuration](docs/CLAUDE-CODE.md) — Claude-specific
  setup details and troubleshooting.
- [Gemini CLI Configuration](docs/GEMINI-CLI.md) — Gemini-specific
  setup details.
- [Cloud Multi-User Architecture](docs/CLOUD-MULTI-USER.md) — the
  locked design that governs how identity, accounts, and tool
  surfaces fit together; the Phase 2 cloud HTTP plan.
- [MCP specification](https://modelcontextprotocol.io/) — protocol
  reference.
