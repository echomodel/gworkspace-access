# Contributing

## Project structure

```
gworkspace-access/
├── README.md                     # User-facing overview, install, quick start.
├── CONTRIBUTING.md               # This file — dev workflow + repo layout.
├── MCP-SERVER.md                 # MCP client registration.
├── pyproject.toml                # Build + entry points + dependencies.
├── gwsa/
│   ├── __init__.py               # App composition root (declares mcp-app App, profile model, admin extensions).
│   ├── sdk/                      # All behavior. Layered access to Google APIs.
│   │   ├── auth.py               # Credential resolution (bridges mcp-app + legacy vault).
│   │   ├── mail/, docs/, drive/, chat/, calendar/, people/
│   │   └── profiles.py, config.py    # Legacy vault — read path during migration.
│   ├── cli/                      # Thin Click wrappers over the SDK. Domain commands only.
│   │   ├── __main__.py           # gwsa entry point (mail / sheets / docs / drive / chat / calendar).
│   │   ├── mail/, docs_commands.py, drive_commands.py, sheets_commands.py, chat.py, calendar_commands.py
│   │   └── decorators.py         # require_scopes, status formatting.
│   ├── mcp/
│   │   ├── tools.py              # mcp-app-native tool module (auto-discovered).
│   │   └── server.py             # Legacy FastMCP server. Still serves gwsa-mcp during migration.
│   └── admin/                    # gwsa-admin extensions (accounts subgroup, acquire-token, migrate).
├── tests/
│   ├── framework/                # mcp-app conformance test pack (App wiring, auth, tool protocol).
│   ├── unit/                     # SDK + admin CLI unit tests.
│   └── integration/              # Live-API tests (Gmail, Drive, Docs). Require valid token.
└── docs/
    └── CLOUD-MULTI-USER.md       # Locked architecture + migration plan.
```

## Architecture rules

**All behavior lives in the SDK** (`gwsa/sdk/`). CLI commands and MCP
tools are thin wrappers that parse input, call the SDK, and format
output. If you find yourself writing logic in `gwsa/cli/` or
`gwsa/mcp/`, move it to the SDK.

**Profile / account / token management lives exclusively in
`gwsa-admin`.** The user-facing `gwsa` CLI is Google Workspace
domain operations only.

**MCP tool surface lives in `gwsa/mcp/tools.py`.** Plain async
functions, no decorators — name becomes tool name, docstring becomes
schema description, type hints drive parameter schemas. mcp-app
discovers them automatically.

### Byte-producing tools: control plane carries references, data plane is out-of-band

Tools that produce binary output (email attachments, Drive downloads,
generated reports) must work under any MCP transport — including HTTP,
where the agent and the server do not share a filesystem. A parameter
like `save_path: str` is therefore an antipattern: under HTTP transport
the file lands on the server container and is unreachable from the
agent.

The convention in this repo is the **`destination` parameter** defined
in `gwsa.sdk.destinations`:

- `InlineDestination` — return the bytes as a content block
  (`EmbeddedResource` + `TextContent` summary). Subject to a size cap
  (default 100KB) because tool responses have practical client limits.
- `DriveDestination` — upload to the user's Google Drive and return a
  file id + URL. The user already has tools to retrieve files from
  Drive, so the data plane is out-of-band of the MCP response.

The `materialize()` helper handles the discrimination. Any new tool
that produces bytes should accept a `Destination` parameter and return
either `list[ContentBlock]` (inline) or a plain dict (Drive). Never
introduce a server-local-path parameter on a byte-producing tool.

The `gwsa.sdk` layer stays transport-agnostic: byte-producing SDK
helpers expose `*_bytes` and `*_file` variants. The CLI uses
`download_file(save_path)`-style helpers because the CLI is stdio-only.
The MCP layer always uses the `*_bytes` variants and the destination
plumbing.

### Calendar event availability (Free/Busy)

Calendar event create/update map an `availability` value (`free`/`busy`)
to the Calendar API `transparency` field (`transparent`/`opaque`) in
`gwsa/sdk/calendar/events.py`. Two design rules must be preserved if you
touch this code:

1. **All-day events default to Free; timed events default to Busy.**
   This mirrors the Google Calendar web UI. `create_event` applies the
   all-day default; `update_event` does **not** apply any default — an
   update only changes `transparency` when `availability` is passed, so
   it never silently flips a user's existing event.
2. **Always echo a normalized `transparency` + `availability` back.**
   The raw API omits `transparency` when it is the default `opaque`, so
   `_normalize()` fills it in. Don't return raw API events for calendar
   operations — callers rely on the explicit value to confirm what was
   set.

## Development setup

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

## Testing

**Unit + framework tests** run offline with no credentials:

    make setup       # bootstrap venv (once)
    pytest           # run unit + framework tests

Or from a fresh clone:

    make test        # creates venv + runs unit + framework tests

Bare `pytest` ignores `tests/integration/` by default (see
`pyproject.toml` `[tool.pytest.ini_options]`).

**Integration tests** require additional setup:

| Suite | Path | Prerequisites |
|-------|------|--------------|
| real-user | `tests/integration/real-user/` | A configured local gwsa account (`gwsa-admin connect local` + `gwsa-admin accounts add`). Each contributor uses their own Google identity. |

Run explicitly:

    make integration-test
    # or:
    pytest tests/integration/real-user/

### Test philosophy (sociable)

Tests run real collaborators end-to-end against isolated temp
directories. The only mocked boundaries are uncontrollable network
calls (e.g., `InstalledAppFlow.run_local_server` in
`test_acquire_token.py`). CLI tests use Click's `CliRunner` —
in-process invocation against `gwsa.app.admin_cli`, not subprocess.

Storage isolation uses `monkeypatch.setenv` to redirect
`HOME` / `XDG_CONFIG_HOME` / `XDG_DATA_HOME` / `APP_USERS_PATH` /
`GWSA_CONFIG_DIR` to per-test `tmp_path` directories. Nothing touches
the real filesystem.

The mcp-app test pack lives under `tests/framework/` and verifies the
`App` declaration, auth enforcement, and tool protocol compliance
against our actual `App` instance.

## Pre-commit

A precommit hook scans for credentials and PII before allowing the
commit. Don't bypass it; if a finding is a false positive, surface it
and we'll work around it.

## Version management

**Single source of truth:** `gwsa/__init__.py` `__version__`.

| Change type | Bump | Example |
|-------------|------|---------|
| Bug fix | Patch | 0.7.0 → 0.7.1 |
| Backwards-compatible feature | Minor | 0.7.0 → 0.8.0 |
| Breaking change | Major | 0.7.0 → 1.0.0 |

Don't bump to 1.0.0 without explicit approval — 0.x → 1.0.0 is a
product decision, not a mechanical version increment.

**Release:**

```bash
# 1. Bump version in gwsa/__init__.py and pyproject.toml (keep in sync).
git add gwsa/__init__.py pyproject.toml
git commit -m "chore: bump version to X.Y.Z"

# 2. Tag and push.
git tag vX.Y.Z
git push && git push --tags
```

Editable installs (`pip install -e .`) always use the working tree
regardless of version, so dev iteration doesn't need bumps.
