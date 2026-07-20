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

HTTP transport (for cloud deployments) is provided by the mcp-app
framework: `gwsa-mcp serve` is the HTTP entry point used by gapp
when building the Cloud Run container. See the README's
[Cloud deployment](README.md#cloud-deployment) section for the
deploy walkthrough and
[Cloud Multi-User Architecture](docs/CLOUD-MULTI-USER.md) §8 for
the design.

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

34 tools across five domains, one module per Google API plus an
account-discovery module. mcp-app auto-discovers public async
functions from each module:

- **`gwsa.mcp.tools.accounts`** (1): list_google_accounts
- **`gwsa.mcp.tools.mail`** (10): search_emails, read_email,
  modify_email_labels, list_email_labels,
  send_email, reply_email, create_email_draft,
  download_email_attachment, get_email_thread
- **`gwsa.mcp.tools.docs`** (6): list_docs, create_doc, read_doc,
  append_to_doc, insert_in_doc, replace_in_doc
- **`gwsa.mcp.tools.drive`** (11): drive_search, drive_get_metadata,
  drive_list_folder, drive_create_folder, drive_upload, drive_update,
  drive_download, drive_move, drive_delete, drive_find_folder,
  drive_search_folders
- **`gwsa.mcp.tools.chat`** (6): list_chat_spaces, list_chat_members,
  list_chat_messages, search_chat_messages,
  get_recent_direct_messages, get_recent_group_chats

### Drive: one API model, layered conveniences

Drive's underlying API has one resource type (``File``) and one search
endpoint (``files.list``). A folder is just a ``File`` with
``mimeType = "application/vnd.google-apps.folder"``; the same goes for
Google Docs, Sheets, Slides, and shortcuts. The MCP surface reflects
this with a primitive plus ergonomic wrappers:

- **`drive_search(query, max_results, corpora, account)`** — the
  primitive. Takes a [Drive query string](https://developers.google.com/drive/api/guides/search-files)
  directly. Use when no convenience covers the case.
- **`drive_get_metadata(file_id, account)`** — single-file primitive
  over ``files.get``. Use to pre-flight size/mimeType before
  ``drive_download``.
- **`drive_list_folder(folder_id)`** — convenience for the highest-
  frequency case ("what's inside this folder?"). Returns files,
  subfolders, and shortcuts together — mirroring Drive's UI.
- **`drive_search_folders(name)`** — convenience for folder-name
  lookup across My Drive and Shared Drives.
- **`drive_find_folder(path)`** — walks a ``/``-separated path.

Shortcuts surface ``target_id`` and ``target_mime_type`` everywhere so
the agent can resolve to the real underlying file.

### Byte-producing tools and the `destination` parameter

Tools that produce binary output (`download_email_attachment` today;
future bytes-from-API tools) accept a `destination` discriminated
union rather than a `save_path: str`. The parameter is required to be
hosted-transport-safe — a server-local path is unreachable from an
agent running on a different machine. Pass one of:

- `{"kind": "drive", "folder_id": "<id>", "name": "<name>"}` — upload
  to the user's Google Drive. `folder_id` defaults to My Drive root;
  `name` defaults to the source filename. Returns
  `{destination: "drive", drive_file_id, drive_url, name, mime_type,
  size_bytes, folder_id}`. Use `drive_move` afterwards to organize
  into a project folder.
- `{"kind": "inline", "max_size_bytes": <int>}` — return the bytes as
  an `EmbeddedResource` paired with a JSON summary `TextContent`.
  Default cap is 100,000 bytes (kept below Claude Code's ~25K-token
  tool-response limit). Oversized payloads return an error envelope
  hinting at the Drive destination.

`drive_download` is a special case: the file is already in Drive, so
the only sensible response is inline bytes. It takes `file_id` plus an
optional `max_size_bytes` and always returns an `EmbeddedResource +
TextContent` pair.

### Drive default location and trash semantics

- **Default upload location** for `drive_upload` and the `drive`
  destination on `download_email_attachment` is **My Drive root**. The
  agent doesn't need to look up or create a folder in advance — land
  the file first, organize later via `drive_move`.
- **`drive_delete` moves to Trash**, not hard-delete. The user can
  restore from Drive's Trash UI for ~30 days. This avoids irrecoverable
  destruction from agent error and matches Drive UI expectations.

Sheets is CLI-only today (`gwsa sheets ...`); MCP coverage is
pending. The composition root in `gwsa/__init__.py` wires the
modules into `App(tools_modules=[...])`.

## Account selection

The MCP server runs in stdio mode as one human (you). Credentials
are resolved from your mcp-app user record. Within that record:

- **Default behavior** — omit the `account` argument on any tool to
  use `default_account` (set with `gwsa-admin accounts use <name>`),
  or the sole account when only one is configured.
- **Per-call override** — every Google-touching tool accepts an
  optional `account` argument. Pass either the account `name`
  (e.g. `"work"`) or its Google `email` (e.g.
  `"me@example.org"`) to operate as that specific account for
  just that call. The default is unaffected.
- **Discovery** — call `list_google_accounts` to see the current
  user's accounts as `{name, email}` pairs plus the
  `default_account` pointer. The agent uses this to map user
  phrasing ("my work email") to a selector it can pass.

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
  surfaces fit together; the cloud HTTP architecture.
- [MCP specification](https://modelcontextprotocol.io/) — protocol
  reference.
