# Cloud, Multi-User, and the mcp-app Framework: Design

**Status:** Design locked through architecture (§6), documentation discipline (§7), and Phase 1 plan (§8). Phase 2 and a handful of housekeeping items remain open — see §9.

**Purpose:** Captures the design for evolving `gworkspace-access` from its current shape (local stdio MCP server, single active Google identity per process, custom profile vault) toward a cloud-deployable, multi-user MCP service by adopting the [mcp-app](https://github.com/echomodel/mcp-app) framework. The design is the locked piece; the migration is staged, with cloud deployment deliberately deferred until local stdio adoption is stable.

**Migration branch:** `feat/use-mcp-app-framework`.

---

## 1. Scope of "cloud and multi-user"

Two distinct shifts, often discussed together, but separable:

**Shift A — Local stdio on mcp-app.** Move from today's FastMCP + custom-vault setup to mcp-app's framework. One human-user record per machine (typical case); that user's profile carries one or more Google accounts; account selection happens via a per-tool-call `account=` arg with a default. Still stdio, still local, no remote users.

**Shift B — Cloud HTTP deployment.** Run an HTTP MCP server in a managed environment (Cloud Run, container host). Multiple human users register against it, each potentially with their own multiple Google accounts. MCP clients (including claude.ai web and mobile) connect over HTTP with per-user JWTs. Multi-user is the *expected* case for cloud — it's typically why someone deploys (see §8 Phase 2).

Shift A is a UX/architecture refactor that lands on its own (Phase 1). Shift B is a separate deployment-and-trust decision that builds on Shift A (Phase 2). The mcp-app framework supports both natively.

---

## 2. Today: what gwsa actually does

Comprehensive inventory of every command, concept, and side-effect that touches identity, auth, or Google API client configuration. This is the surface area a migration has to preserve, replace, or knowingly drop.

### 2.1 Command tree

| Command | What it does | Filesystem effect |
|---|---|---|
| `gwsa status [--check]` | Show active profile, type, status, email, scope count. `--check` runs live Gmail/Docs/Sheets/Drive/Chat API probes. | Read-only |
| `gwsa profiles list` | Table of all profiles + active marker + cached validation state | Read-only |
| `gwsa profiles current` | Active profile details | Read-only |
| `gwsa profiles use <name> [--no-recheck]` | Validates via tokeninfo (unless `--no-recheck`), then sets active | Writes `config.yaml`, updates profile metadata |
| `gwsa profiles add <name> [--type=oauth\|adc] [--quota-project=...] [--basic-scopes/--all-scopes]` | OAuth browser flow or `gcloud auth application-default login`; validates via tokeninfo; writes profile to vault | Creates `profiles/<name>/{user_token.json,profile.yaml}` |
| `gwsa profiles refresh <name>` | Re-runs OAuth or ADC flow for an existing profile, preserves quota project | Atomic rewrite of `user_token.json` + metadata |
| `gwsa profiles delete <name>` | Removes profile dir; clears active pointer if matched | Deletes `profiles/<name>/`; may clear `active_profile` in config |
| `gwsa profiles rename <old> <new>` | Atomic rename with config rollback | Renames dir; updates `active_profile` if matched |
| `gwsa profiles export [name]` | Dumps raw token JSON to stdout | Read-only |
| `gwsa profiles path [name]` | Prints the absolute path to a profile's token file (for `GOOGLE_APPLICATION_CREDENTIALS=$(gwsa profiles path …)`) | Read-only |
| `gwsa profiles apply [name]` | Copies vault token to `~/.config/gcloud/application_default_credentials.json` (system gcloud ADC) | Writes outside vault — touches gcloud's state |
| `gwsa client show` | Inspect imported OAuth client credentials (client ID, project, type) | Read-only |
| `gwsa client import <path>` | Copy `client_secrets.json` into vault for use by all OAuth profiles | Writes `client_secrets.json` to config dir |
| `gwsa token generate <adc\|custom> [--scopes …] [--output …]` | Run a standalone OAuth/ADC flow and dump the resulting token. Does NOT touch any profile. | Optional file output; otherwise stdout |
| `gwsa config view` / `gwsa config set <key> <value>` | View/edit `config.yaml`. Currently supports `auth.mode = token\|adc` (legacy?). | Writes `config.yaml` |
| `gwsa mail …`, `gwsa docs …`, `gwsa sheets …`, `gwsa drive …`, `gwsa chat …` | Product commands. All resolve credentials via the active profile. | Reads profile state; product side-effects |

### 2.2 The "profile" object — what it actually is

A profile is **a Google identity in the vault**, identified by a user-chosen nickname (alphanumeric/hyphen/underscore, 1–32 chars). It consists of two files:

- `user_token.json` — the credential blob. For OAuth profiles, this is a standard `authorized_user`-shaped Google OAuth token. For ADC profiles, it's the same shape but with a `quota_project_id` field, produced by `gcloud auth application-default login` and then **copied into the vault** so it's isolated from the system-default ADC location.
- `profile.yaml` — metadata: `type` (oauth/adc), cached `email`, cached `validated_scopes`, `last_validated` timestamp, `created` timestamp.

The "active profile" is a string pointer in `~/.config/gworkspace-access/config.yaml`. Every CLI command and every MCP tool call reads this pointer at runtime and resolves credentials from the named profile.

**Important framing:** in gwsa, "profile" means *which Google account am I acting as*. It is a user-facing concept that the human switches between. This is fundamentally different from mcp-app's "profile," which means *what credentials does this individual user have for this app's backend*. The two systems use the same word for non-overlapping ideas. Migration must resolve this collision — see §4.

### 2.3 The ADC isolation feature (non-trivial)

ADC profiles do something most apps don't bother with. When you run `gwsa profiles add work --type=adc --quota-project=…`:

1. Back up `~/.config/gcloud/application_default_credentials.json` to a sidecar file.
2. Run `gcloud auth application-default login --scopes=…`. gcloud writes to its standard location, ignoring our wishes.
3. Run `gcloud auth application-default set-quota-project …` so quota goes to the right project.
4. Copy gcloud's result into the vault as `profiles/<name>/user_token.json`.
5. Restore the original gcloud ADC file from backup (or delete if there was none).

Net effect: the user can create N isolated ADC identities and switch between them without ever clobbering their system-default gcloud auth. The `apply` command is the legacy escape hatch for tools that ignore `GOOGLE_APPLICATION_CREDENTIALS` and only read the system path — it explicitly does clobber, on demand.

### 2.4 Scopes — the OAuth-side complexity

`gwsa/sdk/auth.py` and `cli/auth/scopes.py` together define:

- **Scope aliases** — short names (`mail-read`, `docs`, `drive`, `tasks`, ...) → full Google scope URLs.
- **Feature scopes** — named bundles of scopes per product area (mail, docs, sheets, drive, chat, people).
- **Identity scopes** — `openid`, `email`, `profile` always requested.
- **Scope implications** — `gmail.modify` implies `gmail.readonly`, etc., for satisfaction checks.
- **Effective-scopes resolver** — given granted scopes, returns the set with implications expanded.
- **API probes** — `--check` calls each Google API minimally to verify the credential actually works (Gmail labels list, Docs/Sheets nonexistent-ID lookups, Drive files list, Chat spaces list).

All of this is **app-specific Google-API knowledge** that lives above any auth framework. It is not auth in the JWT sense.

### 2.5 MCP server's relationship to profiles today

`gwsa/mcp/server.py` exposes 30+ tools. Three are profile-related:

- `list_profiles()` — returns the same list the CLI shows.
- `get_active_profile()` — returns active profile name + email + is_adc.
- `switch_profile(profile_name)` — mutates `config.yaml`'s `active_profile`.

Every other tool that talks to Google resolves the credential at call time by reading the active profile from disk. **The server has no in-process notion of "the current user."** A `switch_profile` call mutates global config and the next tool call picks up the change.

This is fine for single-user single-machine stdio. It does not generalize to multi-user HTTP at all.

### 2.6 Client secrets — a server-level secret, not a user-level one

`~/.config/gworkspace-access/client_secrets.json` is the OAuth **client** credential — the GCP-issued identity of the gwsa app itself, used by every OAuth profile to perform the user-consent flow. One file per machine, shared across all profiles. There is no per-user client secret.

This concept does not have a natural home in mcp-app's user/profile model. It is server-level configuration. See §5.

### 2.7 Things specifically NOT in scope of any framework

- `profiles apply` — touches the gcloud system path, outside any vault. It exists to satisfy non-gwsa-aware tools.
- `profiles path` — outputs a path for shell composition. CLI plumbing only.
- `profiles export` — outputs token JSON. CLI plumbing only.
- `token generate` — standalone token producer, never touches profiles. CLI plumbing only.
- `client import` — pre-OAuth one-time setup. CLI plumbing only.
- Scope aliasing/implication — app-level Google knowledge.
- Live API probes (`--check`) — app-level Google knowledge.

These all survive any migration as ordinary CLI commands. They are not affected by the choice of MCP framework.

---

## 3. The mcp-app framework: the relevant capabilities

(Cross-referenced against current source as of this writing; see [github.com/echomodel/mcp-app](https://github.com/echomodel/mcp-app).)

### 3.1 Core model

- `App` is a single composition root: name, tools module, optional Pydantic profile model, optional safe-tool, optional custom middleware, store backend.
- Tools are plain async functions in a module; all public coroutines are auto-registered.
- Identity middleware runs by default for HTTP. Every tool is wrapped in identity-enforcement.
- Two transports: `serve` (HTTP, JWT-authenticated) and `stdio` (single-user, identity set via `--user <email>`).

### 3.2 The user/profile model

- **User** is identified by email. The store is keyed by email.
- **Profile** is a Pydantic `BaseModel` declared by the app. Stored as JSON, hydrated as a typed object on `current_user.get().profile`.
- **Admin CLI** auto-generates typed `--flag` arguments from the profile model fields, with `Field(description=…)` driving `--help` text.
- Operations: `users add`, `users list`, `users update-profile`, `users get-profile`, `users revoke`, `tokens create`.

### 3.3 stdio identity

- `App.stdio(user)` runs one MCP server over stdin/stdout under exactly **one** identity.
- `--user` is **required** for stdio. No implicit identity.
- There is **no built-in concept of switching users within a single stdio process**.

gwsa's design (see §6) puts multiple Google accounts inside one mcp-app user's profile, so the stdio process serves one *human* with potentially many *Google accounts*. Account selection happens at the tool-call level, not by spawning multiple stdio processes.

### 3.4 HTTP routes

- `GET /health` — public, identity-free, `healthy|degraded|unhealthy` with 503 on unhealthy.
- `/` — root, MCP transport (not `/mcp`).
- `/admin/users`, `/admin/users/{email}/profile`, `/admin/tokens`, `/admin/safe-tool`, `/admin/health` — admin-only, JWT with `scope: admin`.
- JWT extraction accepts `Authorization: Bearer` and `?token=…` query param (for claude.ai-style URLs).

### 3.5 What it does NOT do

- No DB-backed store ships. Filesystem only. Anything else means implementing `UserAuthStore` directly.
- No opinion on how user profile fields get *populated* in the first place — the admin CLI/REST takes them as given. If the values are themselves OAuth tokens that require interactive flows, that is the app's problem to solve.
- No built-in profile-switching protocol within a stdio process.
- No Google-anything. The framework is identity-and-credential-agnostic.

---

## 4. Concept mapping: gwsa → mcp-app

The crux of the migration. Each row is one gwsa concept and how (or whether) it maps under the locked design (§6).

| gwsa concept (today) | Maps to (post-migration) | Notes |
|---|---|---|
| Profile (a Google identity, nickname + credential) | One element in `Profile.accounts: list[GoogleAccount]` on a mcp-app user record | Identified by user-chosen `name` field within the accounts list. |
| Profile's nickname | `GoogleAccount.name` | Same idea, renamed. Field name "name" is used consistently — never "nickname". |
| OAuth token (`user_token.json`) | `GoogleAccount.token` (opaque dict) | Stored as the Google authorized_user blob; round-trips through `Credentials.from_authorized_user_info()`. |
| ADC token | `GoogleAccount.token` | Same shape. There's only one method (OAuth); the only real distinction is whether the blob was issued by gcloud's well-known client or by an OAuth client the user owns. That's derivable from `token["client_id"]` — no separate field needed. |
| Profile type (oauth vs adc) | *Not stored.* Detected from `token["client_id"]` when needed (re-acquisition routing, quota_project guard). | One source of truth; no field drift. |
| `--quota-project` for ADC | `GoogleAccount.quota_project: str \| None` | Required when the token was issued by gcloud's well-known client (no host project of its own). Optional otherwise. |
| Cached email | `GoogleAccount.email` | Reported by tokeninfo at validation time. Distinct from the mcp-app user record's email (which is the *human's* identity). |
| Cached `validated_scopes` / `last_validated` | `GoogleAccount.validated_scopes` / `GoogleAccount.last_validated` | Same idea, on the account record. |
| Profile validation states (valid/stale/unvalidated/error) | App-level | Compute on-demand from token contents + last_validated. The "stale" state from today's ADC vault doesn't carry over — the new model doesn't have externally-mutable credentials. |
| Scope management (aliases, implications, probes) | App-level (gwsa SDK) | Pure Google-API logic, framework-agnostic. Unchanged. |
| `client_secrets.json` | Server-level config | Not per-user, not per-account. Stays in `~/.config/gworkspace-access/` for local install; per-user under BYOC for cloud (see §5). |
| Active-profile pointer in `config.yaml` | **Removed.** Replaced by `Profile.default_account: str \| None` on the user record | Identity is established per-process (stdio `--user`) or per-request (HTTP JWT). |
| `gwsa profiles use` | **Removed.** Replaced by `gwsa-admin accounts use <name>` (writes `default_account` on the profile) | Profile mutation belongs in the admin CLI per mcp-app convention. |
| `gwsa profiles add` | **Removed.** Replaced by `gwsa-admin acquire-token …` followed by `gwsa-admin accounts add <name> --token=@file …` | Two-step: acquire interactively, then register. |
| `gwsa profiles refresh` | `gwsa-admin acquire-token …` followed by `gwsa-admin users update-profile … accounts '<JSON>'` (or via the `accounts` subgroup) | Re-acquisition uses the appropriate flow (browser or `gcloud auth application-default login`) depending on the account's `client_id`. |
| `gwsa profiles delete` | `gwsa-admin accounts remove <name>` | Removes one account from the user's accounts list. `gwsa-admin users revoke <email>` removes the whole user. |
| `gwsa profiles rename` | **Dropped.** Account names are user-chosen; renaming = remove and re-add | Rarely needed. |
| `gwsa profiles export` | `gwsa-admin users get-profile <email> --json` | Returns the profile blob including all accounts. |
| `gwsa profiles path` | `gwsa-admin profile-path <name>` (custom admin subcommand) | Plain helper; reads from the local store. Outside the framework's standard surface but trivially added. |
| `gwsa profiles apply` | `gwsa-admin apply-system-adc <name>` (custom admin subcommand) | Same — reads token, writes to system gcloud ADC. Custom because it touches state outside the store. |
| `gwsa client import/show` | `gwsa-admin oauth-client import/show` (custom admin subcommand) | One-time setup, server-level. |
| `gwsa token generate` | `gwsa-admin acquire-token --client-secrets … [--out FILE]` | Standalone OAuth acquisition step that emits a token JSON (stdout by default, pipeable into `accounts add --token=-`). For gcloud-issued tokens, operators run `gcloud auth application-default login` directly. |
| `gwsa config set auth.mode` | **Dropped.** Legacy; unused under new model | — |
| `gwsa status` | `gwsa-admin probe` (framework) + `gwsa-admin api-check` (custom subcommand, app-specific Google-API probes) | Framework probe covers MCP transport health; deep API probes stay on the gwsa side. |
| MCP tool: `list_profiles` | **Dropped** | Replaced by `list_google_accounts` (returns current user's own accounts, not anyone else's). |
| MCP tool: `get_active_profile` | Optionally exposed as `whoami` | Implicit via `current_user.get()`. |
| MCP tool: `switch_profile` | **Dropped** | Identity is established at the framework layer (JWT or `--user`); account selection is a per-tool-call `account=` arg. |

### 4.1 OAuth-flow-ownership question

In cloud HTTP, where does the OAuth flow run?

- **Local-generated, push-to-cloud (preferred):** the user runs the OAuth/ADC flow on their workstation (gwsa CLI, or `gcloud`, or a one-shot helper), gets a token, then pushes it to the cloud via `<app>-admin users add --oauth-token=…` (or `--token-file @path`). Token refresh happens server-side using the refresh token. No browser flow on the server.
- **Server-mediated OAuth (heavier):** the cloud service hosts an OAuth redirect endpoint. User visits a URL, consents, server stores tokens. Requires a verified OAuth client with valid redirect URIs, consent screen review for sensitive scopes, etc. Heavier compliance burden.

Local-generated/push-to-cloud preserves most of today's flows and avoids the OAuth-verification burden for the hosted service. It does mean: the user must have a Google Cloud project with the OAuth client configured *somewhere* — either their own (BYOC) or one published by the gwsa service.

---

## 5. Where `client_secrets.json` goes

This is a real design question that mcp-app doesn't answer.

Today: one shared OAuth client across all profiles on one machine.

In a cloud deployment:

- **(a) Shared service OAuth client.** The deployment publishes one OAuth client. All users authenticate against it. Pros: zero per-user setup. Cons: requires OAuth verification with Google for any non-trivial scope set; ties usage to one project's quota; one revocation hits everyone.
- **(b) BYOC (bring your own client).** Each user supplies their own client_secrets.json (or its contents) when running the OAuth flow locally. The cloud server never sees the client secret — only the resulting user refresh token. Pros: no service-level OAuth verification; users own their quota; aligns with how gwsa works today. Cons: users have to do the GCP Console dance.
- **(c) Hybrid.** Service publishes a client, but users can override with their own.

For Shift A (still local, stdio), this question doesn't matter — client_secrets.json keeps its current role and location.

For Shift B (cloud HTTP), **BYOC is the path of least resistance** and matches gwsa's current philosophy of "you bring your own GCP project." Three reinforcing reasons:

1. **Avoids OAuth verification compliance burden** on the service operator (sensitive scopes like Gmail need Google's app verification for any client used by users outside the developer's org).
2. **Billing flows correctly.** Under BYOC, API calls bill to the end user's GCP project (the OAuth client's project, or the quota project named in their token if ADC). Under a service-published client, billing flows to the *service operator's* project — surprise cost on whoever runs the deployment.
3. **Aligns with today's mental model.** Existing gwsa users already have a GCP project with a configured OAuth client and (often) ADC quota project. Keeping that intact in the cloud variant means less to explain and less to break.

**Workspace org-level constraint to flag.** BYOC presumes each user has a usable, owned GCP project for *every* Google identity they want to register. That assumption breaks for corp Workspace identities under most security postures:

- Corp Workspace orgs commonly enforce OAuth client allowlists; only IT-blessed app IDs can request user consent. A personal-project OAuth client cannot be used to grant the corp identity's Gmail access.
- Sensitive-scope restrictions (Gmail/Drive/Calendar) may require admin allowlisting even when the client is generally permitted.
- Context-Aware Access policies can gate auth flows on device/network posture.

ADC profiles route around the OAuth-client-allowlist problem (gcloud uses Google's own OAuth client) but Context-Aware Access can still block them.

The practical effect: a user with a personal Gmail account and a corp Workspace account may have *one* GCP project they can use for the personal identity and *zero* for the corp identity — corp side often requires the corp's blessed GCP project or just doesn't permit third-party API access at all. This reinforces per-account `quota_project` and per-account OAuth-client config: different identities may *have* to use different projects, not just prefer to. Phase 2 design should not assume "the user's GCP project" as a singular thing.

Open sub-question for Phase 2: how does the cloud deployment refresh OAuth tokens it didn't issue? Refresh calls need the client_id and client_secret of the original OAuth client. For installed-app OAuth (which gwsa uses today), the client_secret is technically required but is also distributed with the app — not actually secret. Under BYOC, the cloud server would need either: (a) the user uploads their client_secrets.json alongside their token, server stores both, or (b) a refresh helper runs locally and the cloud only holds the access token (re-uploaded on expiry — fragile). (a) is cleaner; flag for Phase 2 design.

---

## 6. Architecture (the locked design)

This section describes the design we're committing to. Earlier conversations weighed alternatives (one mcp-app user per Google identity vs. one user per human with multiple Google accounts; cross-user delegation patterns). Those alternatives are not preserved here — they were considered and rejected for reasons captured in commit history if a future contributor needs the backstory.

### 6.1 The model in one paragraph

One mcp-app user record represents one **human**, identified by their email. That human's profile contains a list of **Google accounts** they own — each with its own name, email, credential, and (optionally) quota project. Tools that talk to Google take an optional `account` arg to pick which one; if omitted, they use the user's `default_account`. One stdio process per human; one cloud user record per human; one MCP-client registration per human per client. The word "user" means the human; the word "account" means the Google identity.

### 6.2 Profile model

```python
class GoogleAccount(BaseModel):
    name: str = Field(description="Friendly handle: 'personal', 'work', etc. Alphanumeric/hyphen/underscore, 1–32 chars.")
    email: str = Field(description="The Google account email, as reported by tokeninfo.")
    token: dict = Field(description="Google authorized_user blob — stored opaquely, round-trips through google-auth-python. Steady-state refresh is automatic; re-acquisition (when refresh_token dies) is a manual operator step routed by token['client_id'].")
    quota_project: str | None = Field(
        default=None,
        description="GCP project for billing (sets x-goog-user-project). Required when the token was issued by gcloud's well-known OAuth client (no host project); optional otherwise."
    )
    validated_scopes: list[str] = Field(default_factory=list, description="Scopes the token actually carries per last tokeninfo call.")
    last_validated: datetime | None = Field(default=None, description="When the token last passed tokeninfo. None = never validated.")

class Profile(BaseModel):
    accounts: list[GoogleAccount] = Field(default_factory=list)
    default_account: str | None = Field(default=None, description="Name of the account used when a tool/CLI doesn't specify one.")
```

**Field scoping** — every field on `GoogleAccount` is intrinsically per-Google-identity (the token is issued to one identity; the quota project bills under that identity's permissions; scopes are granted at the identity level). Nothing on `GoogleAccount` belongs to the human. If a human-level field is ever needed (display preferences, default region), it lives as a sibling of `accounts` on `Profile`, not inside each `GoogleAccount`.

### 6.3 CLI surfaces

Three console scripts. Strict separation:

| CLI | Purpose | Examples |
|---|---|---|
| `gwsa` | **Domain only.** Direct Google Workspace operations. | `gwsa mail search`, `gwsa drive list`, `gwsa docs append` |
| `gwsa-mcp` | **MCP transport.** | `gwsa-mcp serve`, `gwsa-mcp stdio --user alice@example.com` |
| `gwsa-admin` | **All user/profile/admin.** mcp-app-generated commands + gwsa-specific extensions. | `gwsa-admin users add`, `gwsa-admin accounts add`, `gwsa-admin connect` |

There is no `gwsa profiles`, no `gwsa accounts`, no `gwsa client`, no `gwsa token`, no `gwsa config`. Profile/credential management lives **exclusively** in `gwsa-admin`. This matches the established mcp-app pattern used by other apps built on the framework.

### 6.4 Custom `accounts` subgroup in `gwsa-admin`

`app.admin_cli` returns a Click `Group`, which Click groups support `add_command`. gwsa extends the framework-generated admin CLI with a custom `accounts` subgroup that hides list-mutation operations behind clean verbs:

```
gwsa-admin accounts add <name> --email EMAIL --token=<- | @FILE | JSON> [--quota-project ID] [--user EMAIL]
gwsa-admin accounts list [--user EMAIL]
gwsa-admin accounts get <name> [--user EMAIL]
gwsa-admin accounts remove <name> [--user EMAIL]
gwsa-admin accounts use <name> [--user EMAIL]              # sets default_account
```

Under the hood, each subcommand reads the user's current profile, mutates the `accounts` list (or `default_account`), and writes back via mcp-app's standard `UserAuthStore.update_profile` API. **No new write path** — the custom subgroup is sugar over the framework's existing primitive.

Coexistence with mcp-app's generic commands:

| Command | What it does | Safe? |
|---|---|---|
| `gwsa-admin users add <email>` | Creates user with `accounts=[]`, `default_account=None` | ✓ |
| `gwsa-admin users get-profile <email>` | Reads profile, shows accounts list | ✓ |
| `gwsa-admin users update-profile <email> default_account <name>` | Same effect as `accounts use <name>` | ✓ |
| `gwsa-admin users update-profile <email> accounts '<JSON>'` | Replaces whole list — power-tool escape hatch | ⚠ Pydantic rejects malformed JSON; user can still blow away their list intentionally |
| `gwsa-admin users revoke <email>` | Deletes user entirely | ✓ |
| `gwsa-admin accounts add/remove/use` | Sugar over `update_profile` | ✓ |

Both paths converge on the same write API. Power users can use either.

gwsa also adds a few small admin subcommands for operations the framework doesn't cover:

```
gwsa-admin acquire-token --client-secrets PATH [--scopes mail,drive,...] [--out FILE]   # OAuth browser flow → token JSON on stdout (or --out file)
gwsa-admin oauth-client import PATH                                     # imports the OAuth client_secrets.json
gwsa-admin oauth-client show
gwsa-admin profile-path <name> [--user EMAIL]                           # prints path to a stored token file
gwsa-admin apply-system-adc <name> [--user EMAIL]                       # copies token to ~/.config/gcloud/...
gwsa-admin api-check [--user EMAIL] [--account NAME]                    # deep API probes (gmail, drive, docs, sheets, chat)
```

These all live in `gwsa-admin` because they're setup/admin concerns, not domain operations.

### 6.5 SDK and tool ergonomics

Every domain tool that talks to Google takes an optional `account: str | None = None` parameter. The selector matches either the account's `name` (e.g. `"work"`) or its Google `email` (e.g. `"alice@example.com"`) — whichever the caller has on hand:

```python
async def search_emails(query: str, account: str | None = None) -> dict:
    """Search emails in one of the user's Google accounts.

    Args:
        query: Gmail search query.
        account: Optional account selector — name (e.g. "work") or email
                 (e.g. "alice@example.com"). Omit to use the user's
                 default account, or the sole account when only one is
                 configured. Call list_google_accounts to discover
                 available names and emails.
    """
```

A new MCP tool `list_google_accounts` returns the current user's accounts — `name`, `email`, and the `default_account` pointer — so the agent has a discovery surface for mapping user phrasing ("my work email") to either selector form. It returns only the *current user's own* accounts, never anyone else's, and never any token material.

The SDK is the only credential-resolution path. Both CLI commands and MCP tools call into it; both surfaces share the same store and the same logic. See §6.7 for the sharing pattern.

### 6.6 Flag resolution: `--user` and `--account`

Both flags are optional on every gwsa surface that needs them (`gwsa mail …`, `gwsa-admin accounts …`). They become required only when ambiguity exists.

| Store state | `--user` needed? | `--account` needed? |
|---|---|---|
| 0 users | error: add a user | — |
| 1 user, 0 accounts | error: add an account | — |
| 1 user, 1 account | no | no |
| 1 user, N accounts, `default_account` set | no | no (uses default) |
| 1 user, N accounts, no default | no | yes |
| N users, no `--user`, no `--account` | yes | — |
| N users, `--account=X` unique across all users | no (inferred) | no (X picks user) |
| N users, `--account=X` matches in M users | yes (ambiguous) | — |
| N users + `--user EMAIL`, that user has 1 account | needed | no |
| N users + `--user EMAIL`, that user has N accounts, default set | needed | no |
| N users + `--user EMAIL`, that user has N accounts, no default | needed | yes |

Resolution algorithm in English:

1. If `--account=X` given, search across all users for an account named X.
   - 0 matches → error.
   - 1 match → use it (user is inferred).
   - >1 matches → ambiguous, error: specify `--user`.
2. If `--account` not given, resolve user first.
   - 0 users → error.
   - 1 user → use them.
   - N users → require `--user`.
3. Once user is resolved, resolve account.
   - 0 accounts → error.
   - 1 account → use it.
   - N accounts, default set → use it.
   - N accounts, no default → require `--account`.

Local-stdio single-user installs (the common case) never see either flag.

### 6.7 Sharing state between CLI, MCP, and admin

All three surfaces read from the same `FileSystemUserDataStore("gwsa")`. There is no parallel store, no mapping layer, no "current user pointer" maintained outside the store. The pattern — a small `_load_*` helper that instantiates the framework's filesystem store and pulls the relevant field out of the resolved user record — is the same one other apps built on this framework use.

Concretely: the SDK has one credential-resolution function (something like `_resolve_account(account: str | None = None) -> GoogleAccount`) that:

1. Opens `FileSystemUserDataStore("gwsa")` — the same store the MCP server uses.
2. Calls `store.list_users()` to find users on disk.
3. Resolves the user per the rules in §6.6 (with optional `--user`).
4. Loads that user record via `store.load(user_email, "user")`.
5. Picks the account by `--account`, by `default_account`, or by being the only one.
6. Returns the `GoogleAccount` to the caller, which uses `.token` to build Google API clients.

Both CLI commands and MCP tools call this same function. They differ only in how they got there (CLI: process started, function called from a click command; MCP: `gwsa-mcp` set `current_user` from `--user` or JWT, function called from a tool). The on-disk profile is the single source of truth. Switching default via `gwsa-admin accounts use X` writes once; every subsequent CLI call and every MCP tool call sees the new default.

### 6.8 What's deliberately not in this design

- **No "current account" pointer outside the profile.** `default_account` lives on the profile. Tools and CLI honor it. No second pointer in setup.json or anywhere else.
- **No `gwsa profiles use` / `gwsa accounts use` in the domain CLI.** Profile writes belong in `gwsa-admin`.
- **No cross-user delegation.** "Different humans share each other's data" is not a goal. Each mcp-app user is isolated; the framework enforces this via JWT (HTTP) or `--user` (stdio).
- **No nicknames-as-separate-from-name field.** `name` is the user-chosen handle. Never "nickname" in field names, CLI args, or docs.
- **No multiple OAuth clients per local install.** One `client_secrets.json` per machine, shared across all OAuth-method accounts. (Cloud is different — see §5 BYOC discussion.)
- **No domain CLI access to a non-default user's data without `--user`.** Local single-user inference assumes one user per machine. Multi-user-on-one-workstation is supported but requires `--user` to disambiguate.

---

## 7. Documentation discipline

The design produces three reading surfaces. All three follow the same rule: **simplest case first, multi-account second, multi-user third (footnote for local, expected case for cloud).** A reader who only has one Google identity never sees the word "account" as a separate noun in the primary path.

### 7.1 The three surfaces

- **README.md** — narrative, structured, scannable. For humans with the repo open.
- **`--help` text on `gwsa` and `gwsa-admin`** — terse, action-oriented. For humans or coding agents without README in context who can `tool --help` their way through.
- **MCP tool docstrings** — verbose, self-contained. They drive the tool schemas the agent sees; they have to stand alone because the agent doesn't have README.

### 7.2 README structure

1. What gwsa is (one paragraph).
2. **Install.**
3. **Quick start — one Google account.** The headline path. Install OAuth client → acquire token → `gwsa-admin users add` → `gwsa-admin accounts add` → register MCP server → first command works. No `--account`, no `--user`, no multi-anything words. Reader can stop here and be done.
4. **Adding more Google accounts.** What "account" means as a concept, how to add, how `default_account` works, how `--account` overrides per-call. Reader skips this section entirely if they don't need it.
5. **Daily usage.** CLI examples, MCP via agents.
6. **Reference.** Profile schema, storage paths, env vars, full `gwsa-admin` surface.
7. **Cloud deployment.** Phase 2. Lead with the cloud-multi-user-is-expected framing (see §8 Phase 2).
8. **Multi-user on one local machine.** Rare, called out as such.
9. **Troubleshooting.**

The word "account" does not appear in the Quick Start section. Introduced in §4 of the README.

### 7.3 CLI `--help` text

Pattern for every command: one-line summary, then examples (simplest first, multi-account second), then options table.

`gwsa --help` top-of-output:
> Google Workspace CLI: mail, drive, docs, sheets, chat.
>
> First-time setup: `gwsa-admin users add <your-email>` then `gwsa-admin accounts add <name>`.
> See README or `gwsa-admin --help` for setup details.

`gwsa mail search --help`:
> Search emails. Required: QUERY.
>
> Examples:
>   gwsa mail search "from:bob"                  # uses your only/default account
>   gwsa mail search "from:bob" --account work   # uses the named account
>
> Options:
>   --account NAME  Name of the Google account. Omit if you have one,
>                   or to use the default set via `gwsa-admin accounts use`.
>   --user EMAIL    User email. Omit unless you have multiple users
>                   configured locally (rare).

`gwsa-admin accounts add --help`:
> Add a new Google account to a user's profile.
>
> Examples:
>   gwsa-admin accounts add personal --email me@example.com --token=@/tmp/t.json
>   gwsa-admin acquire-token --client-secrets ~/cs.json | gwsa-admin accounts add work --email me@example.org --token=-
>   gwsa-admin accounts add adc-account --email me@example.com --token=@~/.config/gcloud/application_default_credentials.json --quota-project my-proj
>
> Arguments:
>   NAME                        Account name (used to select it later).
>
> Options:
>   --email EMAIL                Google account email (as reported by tokeninfo).
>   --token=<- | @FILE | JSON>   Token blob. - for stdin, @path for a file, or inline.
>   --quota-project ID           GCP project for billing. Required for gcloud-issued tokens.
>   --user EMAIL                 Target user. Omit if you have one user (typical).

### 7.4 MCP tool docstrings

Every Google-touching tool follows the same pattern. The docstring is the schema; it must stand alone.

`search_emails`:
> Search emails in the user's Gmail.
>
> If the user has multiple Google accounts and the request implies a specific
> one (e.g. "check my work email"), pass `account="work"` (or
> `account="me@example.org"` — name or email both work). Otherwise omit
> `account` to use the user's default account, or the sole account when
> only one is configured. If you don't know what accounts exist, call
> `list_google_accounts` first.
>
> Args:
>     query: Gmail search query (e.g. "from:bob after:2026-01-01").
>     account: Optional account selector — name or email. Omit to use
>              the user's default account. See `list_google_accounts`
>              for available names and emails.

`list_google_accounts`:
> List the current user's Google accounts.
>
> Use this when the user references an account by context (e.g. "my work
> email", "the personal one") and you need to map their words to the
> account `name` or `email` that goes in the `account` argument of every
> other gwsa tool.

Every Google-touching tool gets the same `account` arg with the same docstring shape: "Omit to use the user's default account. Use `list_google_accounts` to discover names and emails." Consistent, learnable, and self-describing — selectors accept either form so callers don't have to guess which to use.

---

## 8. Phased migration plan

### Phase 0 — Today

FastMCP stdio, custom profile vault, single active profile, `switch_profile` tool. Working, in use, not broken. This is the starting point.

### Phase 1 — mcp-app adoption, no cloud

**Goal:** adopt mcp-app and the design in §6. Eliminate `switch_profile`. Still purely local stdio, one human, possibly multiple Google accounts.

**Concretely:**

1. Add `mcp-app` dependency; replace `setup.py` with `pyproject.toml`.
2. Declare `App` in `gwsa/__init__.py` with the Pydantic `Profile` model from §6.2 (`accounts: list[GoogleAccount]`, `default_account: str | None`).
3. Replace `gwsa/mcp/server.py` decorator-based tool registration with plain async functions in a tools module. `App` auto-registers them.
4. Implement the SDK credential resolver (§6.7) — `FileSystemUserDataStore("gwsa")` + `list_users()` + load + account pick. One function, called by both CLI and MCP code paths.
5. Every Google-touching MCP tool grows an optional `account: str | None = None` parameter. Update docstrings per §7.4.
6. Add a new MCP tool `list_google_accounts` returning the current user's accounts.
7. Drop the MCP tools `list_profiles`, `get_active_profile`, `switch_profile`. Optionally add `whoami`.
8. Extend `gwsa-admin` (via `app.admin_cli.add_command(...)`) with the custom `accounts` subgroup (§6.4) and the auxiliary subcommands (`acquire-token`, `oauth-client`, `profile-path`, `apply-system-adc`, `api-check`).
9. Strip the gwsa main CLI down to domain only. Remove `gwsa profiles`, `gwsa client`, `gwsa token`, `gwsa config`. Every Google-touching command grows optional `--account` and `--user` flags per §6.6.
10. Add `tests/framework/` and import the mcp-app testing pack for auth/admin/tool wiring coverage.
11. Write the migration script. Reads `~/.config/gworkspace-access/profiles/*`, prompts for the human's email (defaults to the email of today's active profile), creates one user record at that email, collapses all existing profiles into that user's `accounts` list (the today-active profile's name becomes `default_account`).
12. MCP client re-registration: replace any existing `gwsa` stdio entry with `claude mcp add gwsa -- gwsa-mcp stdio --user <your-email>` (etc. for Gemini CLI).
13. Update README, `--help` text, and MCP docstrings per §7.

**What's preserved:** all Google-API logic, scope management, the ADC isolation flow inside `acquire-token`, the path/apply/export/api-check utilities.

**What changes:** storage layout (under `${XDG_DATA_HOME}/gwsa/users/<email>/`); profile schema (Pydantic, single shape); MCP server registration (one entry instead of stdio per profile); domain CLI surface (account flags added, profile management removed).

**What dies:** `switch_profile`, `list_profiles`, `get_active_profile` MCP tools; the active-profile config pointer; `gwsa profiles`, `gwsa client`, `gwsa token`, `gwsa config` subcommand groups.

**What's new:** `gwsa-admin` CLI (framework-generated + custom extensions); `list_google_accounts` MCP tool; `--account` parameter on every Google-touching MCP tool; `--account` and `--user` flags on every Google-touching CLI command.

### Phase 1.5 — Optional intermediate

Add HTTP capability locally (no public deployment) so the user can serve over localhost and register via claude.ai web pointed at `http://localhost:PORT`. Provides a real test bed for Phase 2 without the deployment compliance burden. Low effort if Phase 1 is done well; code-side it's `gwsa-mcp serve` instead of `gwsa-mcp stdio`.

### Phase 2 — Cloud HTTP deployment

**Prerequisite:** Phase 1 complete and stable.

**Goal:** deploy gwsa as an HTTP MCP service. Register identities once. Connect from claude.ai web, mobile, or any machine without local credential setup.

**Multi-user is the expected case here, not an edge case.** This is the most important framing shift from Phase 1. Local stdio is single-user-per-process by design (multi-user-on-one-workstation is rare and mostly testing). Cloud HTTP is multi-user by design — that's typically *why* a person deploys it. Reasons someone goes to Phase 2:

- **Don't want to install MCP locally on every device.** Phone, second laptop, work machine — registering once against a cloud URL is far less friction than pipx + acquire-token + register MCP locally on each.
- **Don't want to sync Google tokens across machines.** Local stdio means refresh tokens live on each device's filesystem. Cloud centralizes that to one store with one rotation point.
- **claude.ai web and mobile.** No local install is possible there. Cloud HTTP is the only path.
- **Multi-human shared deployment.** Spouse, family member, second person under the same roof. Each gets their own user record, their own JWT, their own isolated profile. mcp-app's auth model handles this natively.
- **Multi-identity-under-one-human.** Same person under two different mcp-app user records — for example, you under your work email with your work Google account, and you again under your personal email with your personal Gmail + small-business Gmail accounts. Logical separation that scales naturally with mcp-app's user-per-record model rather than cramming everything into one user's `accounts` list.

A typical deployment serves anywhere from 1 to a small number of humans, each with 1+ Google accounts. The admin surface (`users add`, `accounts add`, `tokens create`) is exercised regularly, not just at first setup.

**Open design questions specific to this phase:**

- Who owns the OAuth client? BYOC vs published service client (§5).
- Refresh token storage at rest: encryption strategy? KMS-backed envelope?
- How does a user push their initial token to the cloud? Acquire-token locally + `gwsa-admin accounts add` against the connected cloud target.
- What's the refresh cadence server-side? Google refresh tokens expire after 6 months of inactivity — a daily refresh job per user keeps them alive.
- Audit logging: per-tool-call attribution by user is now mandatory.
- Quota management: ADC quota project semantics get complicated when many users share one deployment, but per-account `quota_project` plus BYOC handles most of it (each user's API calls bill to their own project).
- Operator UX for adding a new household member or a new identity: should this be self-serve via a sign-up page, or always operator-mediated via `gwsa-admin users add`? Phase 2 design.

**What changes from Phase 1:** mostly deployment config and operator workflow. Code-side, Phase 1's `App` is already HTTP-capable; flipping the switch is `gwsa-mcp serve` instead of `gwsa-mcp stdio`. The harder work is operational — secrets, refresh jobs, monitoring, the human routine of adding/rotating users.

---

## 9. Open questions

These remain unresolved and need decisions or further investigation. The architectural questions are now locked (§6 — profile shape, CLI surface split, custom admin subgroup pattern, flag resolution rules) and the documentation discipline is committed (§7). What's left is mostly Phase 2 concerns and small post-migration housekeeping.

1. **OAuth client identity in cloud (§5).** BYOC vs service-published vs hybrid. Leaning BYOC for compliance and billing-flow reasons (each user's GCP project pays for their API calls, no service-level OAuth verification burden), but the operator UX of "every user supplies their own client_secrets" is friction. Phase 2 decision.
2. **Gcloud-issued tokens in cloud.** Today some users register credentials issued by `gcloud auth application-default login` (i.e., tokens whose `client_id` is gcloud's well-known OAuth client). In a cloud deployment, there's no `gcloud` running on the server — re-acquisition (when refresh_token dies) requires the user to re-run `gcloud auth application-default login` locally and push the new blob. Need to document the re-acquisition story for cloud users with gcloud-issued tokens, or restrict cloud users to user-owned OAuth client tokens. Phase 2 design.
3. **Refresh token storage at rest in cloud.** Encryption strategy, KMS-backed envelope, key rotation cadence. Phase 2.
4. **Refresh cadence in cloud.** Google refresh tokens expire after 6 months of inactivity. A daily refresh job per user keeps them alive. Schedule, observability, failure handling all need design. Phase 2.
5. **Tool-arg reliability under multi-account.** How often will agents forget to pass `account=` or pass the wrong name? Mitigations are in place (`list_google_accounts` discovery tool, consistent docstring shape, `default_account` fallback) but reliability needs real-world testing once migrated. May surface a need for tool-call guard rails.
6. **Test migration.** Existing `tests/unit/` and `tests/integration/` cover today's gwsa-specific surface. Adding `tests/framework/` is additive (the mcp-app test pack). The question is whether to keep, rewrite, or drop the existing tests once the credential layer moves to mcp-app. Likely keep with minor adjustments; verify case-by-case.
7. **client_secrets.json location post-migration.** Stays in `~/.config/gworkspace-access/` as a server-level artifact (local install), per-user under BYOC for cloud. Small detail; document and move on.
8. **Operator UX for adding a household member (Phase 2).** Self-serve sign-up page, or operator-mediated `gwsa-admin users add` only? Affects the deployment shape.

---

## 10. Risks and non-goals

### Risks

- **Lost feature: `switch_profile` MCP tool.** Any caller (agent or script) that depends on mid-session profile switching breaks. The replacement is the per-tool-call `account=` arg. For agents this is an improvement (no global state mutation); for scripts that called `switch_profile` it's a one-time rewrite.
- **Token format drift.** mcp-app stores profiles as Pydantic-serialized JSON. The on-disk shape differs from today's `user_token.json` + `profile.yaml`. The migration script (§8 Phase 1 step 11) must convert existing users in place; bugs here are user-visible and recovery requires re-running OAuth flows.
- **Agent passes wrong `account=` or omits it when it should pass one.** Mitigations are in place (§7.4 docstring discipline, `list_google_accounts` discovery tool, `default_account` fallback), but the actual reliability needs measurement once shipped. May surface a need for additional guard rails.
- **Cloud-deployed Google credentials are higher-stakes.** Phase 2 adds operational concerns (encryption at rest, refresh token revocation handling, breach response) that Phase 1 doesn't. Phase 2 isn't a small follow-on; treat it as a separate decision.

### Non-goals (explicitly out of scope)

- Replacing Google's auth system. gwsa wraps Google OAuth; the cloud service does too. mcp-app's JWT is for *the user authenticating to gwsa*, not for *gwsa authenticating to Google*.
- Cross-user features. The cloud service is multi-tenant in the sense of "many users, each isolated." Not "users can share data."
- Supporting non-Google MCP transports or non-Workspace APIs. The framework expansion is auth + deployment, not domain expansion.

---

## 11. Next steps

Order of operations:

1. **Resolve remaining §9 questions** as they affect Phase 1 (mostly Phase 2 concerns, so most can defer). For Phase 1, just confirm: test migration strategy (q6) and client_secrets.json location (q7). Decisions go into this doc.
2. **Open a tracking issue** capturing the agreed Phase 1 deliverables (per §8 Phase 1's concrete steps). No commitment to Phase 2.
3. **Create branch `feat/use-mcp-app-framework`** and land Phase 1 in reviewable chunks matching §8 Phase 1's step numbering — likely grouped: (a) pyproject + App declaration + framework test pack, (b) profile model + SDK credential resolver, (c) MCP tools module conversion, (d) custom admin subgroup + auxiliary subcommands, (e) gwsa CLI strip-down + flag resolution, (f) migration script, (g) README and docstrings per §7.
4. **Defer Phase 2** until Phase 1 has been used long enough to surface model issues. Phase 1.5 (localhost HTTP) can be tried earlier as a low-cost test of the HTTP path.

---

## Appendix A — Quick reference: today's filesystem layout

```
~/.config/gworkspace-access/
├── config.yaml                    # { active_profile: "personal", auth: { mode: null } }
├── client_secrets.json            # OAuth client credentials (one per machine)
└── profiles/
    ├── personal/
    │   ├── user_token.json        # { token, refresh_token, scopes, ... }
    │   └── profile.yaml           # { type: oauth, email, validated_scopes, last_validated, created }
    └── work-adc/
        ├── user_token.json        # ADC-shaped, includes quota_project_id
        └── profile.yaml           # { type: adc, email, ... }
```

## Appendix B — Post-migration filesystem layout

Under the locked design (§6), one mcp-app user record per human; multiple Google accounts inside that user's profile.

```
${XDG_DATA_HOME}/gwsa/users/
└── alice~example.com/             # One dir per human; mcp-app encodes @ as ~
    └── user.json                  # UserAuthRecord + Profile { accounts: [...], default_account }

~/.config/gworkspace-access/
├── client_secrets.json            # Server-level (one OAuth client per machine for OAuth-method accounts)
└── setup.json                     # mcp-app per-app `connect` config (URL/key for admin CLI)
```

Each human's `user.json` contains their `Profile` with the `accounts` list and `default_account` pointer. The on-disk shape collapses today's `profiles/<name>/` directory tree into a single JSON file per human.
