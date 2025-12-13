### Enhance 403 Error Message in MCP Server for Google Docs

**Description:**
When the `gwsa-mcp` server's `read_doc` tool encounters an `HttpError` with a 403 status code (PermissionDenied) from the Google Docs API, the error message returned to the MCP client should be more informative. It should explicitly suggest that the user check their `gwsa` profile for correct permissions.

**Location:**
`gwsa/mcp/server.py`, within the `read_doc` async function.

**Proposed Change:**
Modify the `read_doc` function's exception handling to specifically catch `HttpError` (importing it from `googleapiclient.errors`). If the error status is 403, return a custom error message that includes a hint about checking/switching `gwsa` profiles.

**Code Snippet (to be applied in `gwsa/mcp/server.py`):**

```python
# Add this import at the top of the file
from googleapiclient.errors import HttpError
# ... other imports ...

@mcp.tool()
async def read_doc(doc_id: str, format: str = "content") -> str:
    """
    Read a Google Doc by ID.
    # ... (existing docstring) ...
    """
    try:
        if format == "text":
            text = docs.get_document_text(doc_id)
            return json.dumps({"text": text}, indent=2)
        elif format == "raw":
            doc = docs.get_document(doc_id)
            return json.dumps(doc, indent=2)
        else:
            content = docs.get_document_content(doc_id)
            return json.dumps(content, indent=2)
    except HttpError as e:
        if e.resp.status == 403:
            logger.error(f"Permission error reading doc: {e}")
            return json.dumps({
                "error": "The caller does not have permission.",
                "details": str(e),
                "hint": "The active gwsa profile may not have access to this document. "
                        "Try switching profiles with the `switch_profile` tool or "
                        "running `gwsa setup --new-user` to re-authenticate."
            })
        raise  # Re-raise other HttpErrors
    except Exception as e:
        logger.error(f"Error reading doc: {e}")
        return json.dumps({"error": str(e)})
```

**Reasoning:**
Currently, a 403 error for Google Docs results in a generic "The caller does not have permission" message. This can be unhelpful for users, as the most common cause in an MCP setup is an incorrect or unauthenticated `gwsa` profile. By adding a specific hint to check profiles, the user can more quickly diagnose and resolve the issue.

---

### Validate and Document MCP Server Behavior in Unconfigured States

**Description:**
The `gwsa-mcp` server relies on a correctly configured `gwsa` CLI environment to function. We need to validate and document the server's behavior and error handling when this underlying configuration is missing or incomplete.

**Scenarios to Validate:**

1.  **`gwsa` CLI Not Installed:**
    -   **Question:** Is it possible to install `gwsa-mcp` without the `gwsa` package? (Answer: No, it's the same package).
    -   **Action:** Confirm that since `gwsa-mcp` is an entry point of the `gwsa` package, it cannot be installed without it. This is more of a documentation note than a test case.

2.  **`gwsa` CLI Installed but Not Configured:**
    -   **Scenario:** A user has successfully run `pipx install -e .` but has **not** run `gwsa setup` to create a profile.
    -   **Action:**
        -   Start the `gwsa-mcp` server through an MCP client (e.g., `gemini mcp list`).
        -   Attempt to use a tool (e.g., `list_profiles`).
        -   Record the exact error message that is returned.
        -   **Goal:** The error should be clear and actionable, guiding the user to run `gwsa setup`. If the current error is generic or confusing, create a new task to improve it.

**Documentation Task:**
-   Update `MCP-SERVER.md` with a "Prerequisites" or "Troubleshooting" section that clearly states the dependency on a configured `gwsa` CLI.
-   Document the expected error message for an unconfigured state and provide the solution (`gwsa setup`).

**Reasoning:**
Proactively addressing these edge cases will prevent user confusion and support issues. The MCP server should fail gracefully with clear instructions if its foundational requirements are not met.

---

### Architectural Review of MCP Tool Registration

**Description:**
Investigate the best practices for structuring and registering tools with the `FastMCP` framework. Currently, all `@mcp.tool()` decorators are located in a single, monolithic `gwsa/mcp/server.py` file.

**Questions to Answer:**

1.  Does the `FastMCP` framework support a more modular approach, such as registering tools from different files or modules (e.g., a "blueprint" or "router" pattern)?
2.  What is the recommended pattern for a project with a growing number of tools to maintain code organization and separation of concerns?
3.  Would splitting the tools into logical groups (e.g., `gwsa/mcp/mail_tools.py`, `gwsa/mcp/docs_tools.py`) improve maintainability?

**Action:**
-   Review the `mcp` library's documentation and source code (if necessary) to understand its registration mechanisms.
-   Based on the findings, refactor the `gwsa/mcp/server.py` file into smaller, more focused modules if a better pattern exists.
-   If no such pattern is supported, document this limitation.

**Reasoning:**
As the number of tools for different Google Workspace services (Mail, Docs, Sheets, Calendar, etc.) grows, the single `server.py` file will become increasingly large and difficult to manage. A modular structure would improve code readability, maintainability, and scalability.

---

### Add User Identity Metadata to MCP Tool Outputs

**Description:**
To improve transparency and user trust, MCP tool operations should return the active user profile (e.g., email address) as part of their standard response. This allows the LLM/agent to confirm which identity is performing an action without requiring a separate tool call.

**Implementation:**

1.  **Identify Cached Profile Info:** The active user's profile information is available locally via the `gwsa.sdk.profiles.get_active_profile()` function. This function reads from a local cache and should not introduce network latency.

2.  **Create a Helper Function:** In `gwsa/mcp/server.py`, create a helper function that retrieves the active profile and formats a standard metadata object.
    ```python
    def _get_profile_metadata():
        profile = profiles.get_active_profile()
        if not profile:
            return {"active_profile": "unknown"}
        return {
            "active_profile": {
                "name": profile.get("name"),
                "email": profile.get("email"),
                "is_adc": profile.get("is_adc", False)
            }
        }
    ```

3.  **Update Tool Responses:** For each relevant tool (e.g., `search_emails`, `read_doc`, `list_docs`), modify the JSON response to include this metadata.
    ```python
    # Example for search_emails
    result = {
        "messages": messages,
        # ... other data ...
    }
    result.update(_get_profile_metadata()) # Add the metadata
    return json.dumps(result, indent=2)
    ```

**Reasoning:**
Returning the active user as metadata in every response is a lightweight way to provide crucial context to the LLM agent. The agent can then decide whether to surface this information to the user (e.g., "Searching for emails in your `work@company.com` account..."), improving the conversational experience and preventing actions from being performed with the wrong identity.

---

### Validate MCP Server Prerequisites in Documentation

**Description:**
Ensure that the `MCP-SERVER.md` documentation clearly specifies the prerequisite of having `gworkspace-access` / `gwsa` installed and fully configured on the machine *before* attempting to use the `gwsa-mcp` server. This is crucial to prevent users from encountering errors due to an uninitialized environment.

**Action:**
- Review the "Quick Start" and "Prerequisites" sections of `MCP-SERVER.md`.
- Explicitly add a note or a step indicating that `gwsa setup` must be successfully run to establish an active and validated profile before using `gwsa-mcp`.
- If a relevant section already exists, ensure its wording is unambiguous.

**Reasoning:**
While `gwsa-mcp` is an entry point of the `gwsa` package, its functionality depends entirely on the underlying `gwsa` configuration (active profile, credentials). Users might install `gwsa-mcp` but forget or be unaware that `gwsa setup` is a necessary first step. Clear documentation of this prerequisite will guide users to a successful setup and prevent frustration.

---

### Review CLI Command Overlap: `gwsa setup` vs `gwsa profiles`

**Description:**
Audit the overlap and potential redundancy between `gwsa setup` (with its various `--args`) and `gwsa profiles` subcommands. Both command families perform profile-related operations, which may cause user confusion about which command to use for a given task.

**Goals:**

1.  **Map Command Capabilities:** Document what each command/flag does:
    -   `gwsa setup` (default behavior)
    -   `gwsa setup --new-user`
    -   `gwsa setup --switch-user`
    -   `gwsa profiles list`
    -   `gwsa profiles switch`
    -   `gwsa profiles add` (if exists)
    -   Any other related commands

2.  **Identify Overlap:** Determine where functionality overlaps:
    -   Do `gwsa setup --switch-user` and `gwsa profiles switch` do the same thing?
    -   Is there a clear distinction between "setup" (initial config) vs "profiles" (ongoing management)?

3.  **Scenario Coverage Matrix:** Create a matrix of user scenarios and which command addresses each:
    -   **Post-install, pre-config:** First-time user, no profiles exist
    -   **Add second profile:** User has one profile, wants to add another
    -   **Switch between existing profiles:** Quick context switch
    -   **Re-authenticate expired profile:** Token refresh or re-auth
    -   **Delete/remove a profile:** Clean up unused profiles
    -   **List available profiles:** Discover what's configured
    -   **Check current active profile:** Verify context

4.  **Simplification Recommendations:** Based on findings, recommend:
    -   Consolidating commands if there's true redundancy
    -   Clarifying documentation if commands serve distinct purposes
    -   Adding aliases or deprecation warnings if needed

5.  **Unit Test Review:** Audit and update unit tests for scenario coverage:
    -   Review existing tests for `gwsa setup` and `gwsa profiles` commands
    -   Identify gaps: which scenarios from the matrix above lack test coverage?
    -   **Requires approval before changes:** Propose test additions/modifications and get user sign-off before implementing
    -   Ensure tests cover both positive paths (success) and negative paths (errors, edge cases):
        -   No config directory exists
        -   Config exists but no profiles
        -   Config exists with corrupted/invalid data
        -   Profile exists but credentials expired (mock `creds.valid=False, refresh_token=None`)
        -   Token refresh failure (mock `creds.refresh()` to raise)
        -   Switching to non-existent profile
        -   **BUG: Adding profile with duplicate name** - `create_profile()` silently overwrites!

6.  **Fix: Duplicate Profile Name Check:**
    -   `create_profile()` in `gwsa/sdk/profiles.py` does NOT check if profile already exists
    -   `mkdir(parents=True, exist_ok=True)` silently overwrites existing profile
    -   **Required fix:** Add check before line 225:
        ```python
        if profile_dir.exists():
            logger.error(f"Profile '{name}' already exists. Use a different name or delete first.")
            return False
        ```
    -   Add unit test for duplicate profile rejection
    -   Consider: Should there be an `--overwrite` flag for intentional replacement?

7.  **Clarify "default" Profile:**
    -   "default" is just a convention, not special in code
    -   Only "adc" is reserved/built-in
    -   Document this in README or help text to avoid user confusion

8.  **Profile Behavior Q&A - Status Tracker:**

    | # | Question/Scenario | Current Behavior | Status |
    |---|-------------------|------------------|--------|
    | 1 | Is ADC always configured after install? | Yes - virtual/built-in, always in list | ✅ Good |
    | 2 | Is ADC auto-activated after install? | **NO** - `active_profile` is `None` | ✅ **Decision: Keep as-is.** ADC must be explicitly activated via `gwsa profiles switch adc`. No auto-fallback. (See note on setup vs profiles below) |
    | 3 | What is "ADC no creds"? | ADC profile exists but `~/.config/gcloud/application_default_credentials.json` missing | ✅ Good |
    | 4 | Token profile with no token file? | `profile_exists()` = True but API call fails with FileNotFoundError | ⚠️ Discuss: Should profile_exists check token file? |
    | 5 | Switch to profile, can't refresh? | Switch succeeds (just config update), failure on first API call | ⚠️ Discuss: Should switch validate? |
    | 6 | When is refresh determined? | On first API call when `creds.valid` is False | ✅ Good (lazy) |
    | 7 | Refresh on switch? | NO - switch is instant config update | ✅ Good |
    | 8 | Test expired token refresh? | Mock `creds.valid=False, expired=True, refresh_token="fake"` | ⚠️ Need test |
    | 9 | Duplicate profile name check? | **MISSING** - silently overwrites | 🐛 Bug - needs fix |
    | 10 | "default" profile special? | No - just convention, only "adc" is reserved | ✅ Good |
    | 11 | What happens when active profile deleted? | Sets `active_profile` to `None`, NOT to ADC | ✅ **Decision: Keep as-is.** No auto-fallback to ADC. User must explicitly switch. |
    | 12 | Fresh install + MCP tool call? | "No active profile configured" error | ✅ Good (clear error) |
    | 13 | Where is "no active profile" error shown? | Need to audit: Which commands/tools check for active profile vs work without one? | ⚠️ Audit needed (see breakdown below) |
    | 14 | Any unrecoverable corruption scenario? | Can user always escape via CLI alone? | ⚠️ Audit: Corrupted config.yaml? Bad permissions? Is `rm -rf ~/.config/gworkspace-access` always an escape hatch? |
    | 15 | Does `gwsa profiles list` require active profile? | NO - must work gracefully, show ADC or "nothing configured" | ✅ Expected (verify works) |
    | 16 | Does `gwsa profiles switch X` require active profile? | Should work without one (setting one) | ⚠️ Verify |
    | 17 | Does `gwsa setup` require active profile? | Should work without one (creating one) | ⚠️ Verify |
    | 18 | Do read commands (mail search, docs list) require active profile? | Yes - need creds to call API | ⚠️ Verify error is clear |
    | 19 | Do write commands (label, append) require active profile? | Yes - need creds to call API | ⚠️ Verify error is clear |
    | 20 | Do all MCP tools require active profile? | All except `list_profiles`, `get_active_profile`, `switch_profile`? | ⚠️ Audit each tool |

    **Note on ADC and `gwsa setup` vs `gwsa profiles` overlap:**

    The decision that ADC must be explicitly activated raises the question: how should a user activate it?

    Current commands that could do this:
    - `gwsa profiles switch adc` - explicit, works today
    - `gwsa setup` - currently focused on OAuth token flow, not ADC

    **Ideas to clarify:**
    1. **`gwsa setup` purpose:** First-time OAuth setup (create token profile). Should NOT touch ADC.
    2. **`gwsa profiles switch adc`:** Explicit way to use ADC. Works today.
    3. **Should `gwsa setup` offer ADC as an option?** e.g., "Do you want to use OAuth (recommended) or ADC?"
    4. **Post-install flow:**
       - Fresh install → no active profile
       - User runs `gwsa profiles list` → sees ADC (unvalidated) + no user profiles
       - User chooses: `gwsa setup` (create OAuth profile) OR `gwsa profiles switch adc` (use existing gcloud creds)
    5. **Naming clarity:**
       - `gwsa setup` = "create new OAuth profile" (wizard)
       - `gwsa profiles create` = same but non-interactive?
       - `gwsa profiles switch` = activate existing profile (incl. ADC)
       - Overlap: `gwsa setup --switch-user` vs `gwsa profiles switch`?

    **Recommendation:** Audit the overlap (item 6 above) and decide if `setup` should be purely for OAuth wizard, with `profiles` handling all switching/management including ADC.

9.  **Create Permanent Auth/Profile Behavior Documentation:**
    -   Once all Q&A items above are resolved, document the finalized behavior in a dedicated `.md` file (e.g., `AUTH.md` or `PROFILES.md`)
    -   Include:
        -   Profile lifecycle: creation, switching, deletion, validation
        -   ADC vs token profiles: when each is used, limitations
        -   Error scenarios and recovery steps
        -   Edge cases and their expected behavior
    -   Cross-reference unit tests that verify each documented behavior
    -   This becomes the authoritative reference for contributors and advanced users

**Reasoning:**
A clear, non-overlapping CLI interface reduces cognitive load for users. If `gwsa setup` and `gwsa profiles` have ambiguous boundaries, users may use the wrong command, leading to confusion or unexpected behavior. This audit will ensure the CLI is intuitive, well-documented, and thoroughly tested.

---

### Refactor MCP Tools to Return Objects Instead of JSON Strings

**Description:**
The current MCP server tools manually serialize responses using `json.dumps(..., indent=2)` and return strings. This causes formatting issues in Claude (visible `\n` characters, escaped quotes) because the JSON is double-encoded. FastMCP supports returning objects directly, which it serializes properly into `structuredContent`.

**Current Pattern (problematic):**
```python
@mcp.tool()
async def search_emails(...) -> str:
    messages, metadata = mail.search_messages(...)
    return json.dumps({
        "messages": messages,
        "resultSizeEstimate": metadata.get("resultSizeEstimate", 0),
        "nextPageToken": metadata.get("nextPageToken")
    }, indent=2)  # ❌ Creates literal \n in output
```

**Recommended Pattern (per FastMCP examples):**
```python
@mcp.tool()
async def search_emails(...) -> dict:
    messages, metadata = mail.search_messages(...)
    return {
        "messages": messages,
        "resultSizeEstimate": metadata.get("resultSizeEstimate", 0),
        "nextPageToken": metadata.get("nextPageToken")
    }  # ✅ FastMCP handles serialization
```

**Optional Enhancement - Pydantic Models:**
```python
from pydantic import BaseModel, Field

class EmailSearchResult(BaseModel):
    messages: list[dict]
    resultSizeEstimate: int = Field(description="Estimated total results")
    nextPageToken: str | None = Field(description="Token for next page")

@mcp.tool()
async def search_emails(...) -> EmailSearchResult:
    messages, metadata = mail.search_messages(...)
    return EmailSearchResult(
        messages=messages,
        resultSizeEstimate=metadata.get("resultSizeEstimate", 0),
        nextPageToken=metadata.get("nextPageToken")
    )
```

**Benefits of Pydantic Models:**
- Automatic `outputSchema` generation for tool discovery
- Type validation at runtime
- Better documentation for LLM clients
- IDE autocomplete and type checking

**Files to Update:**
- `gwsa/mcp/server.py` - All tool functions currently using `json.dumps()`

**Tools Affected:**
1. `list_profiles` - returns profile list
2. `get_active_profile` - returns profile info
3. `switch_profile` - returns success/error
4. `search_emails` - returns messages + pagination
5. `read_email` - returns message content
6. `add_email_label` / `remove_email_label` - returns label status
7. `list_email_labels` - returns label list
8. `list_docs` - returns document list
9. `create_doc` - returns doc info
10. `read_doc` - returns doc content
11. `append_to_doc` / `insert_in_doc` - returns write status
12. `replace_in_doc` - returns replacement count

**Error Handling Consideration:**
For error responses, return a dict with `error` key:
```python
except HttpError as e:
    if e.resp.status == 403:
        return {
            "error": "The caller does not have permission.",
            "details": str(e),
            "hint": "Try switching profiles..."
        }
```

**Reference:**
- Official FastMCP examples: `github.com/modelcontextprotocol/python-sdk/examples/fastmcp/weather_structured.py`
- MCP specification: `modelcontextprotocol.io/specification/2025-06-18/server/tools`

**Reasoning:**
The current approach of returning JSON strings causes poor formatting in Claude's UI. By returning objects directly, FastMCP properly separates `content` (text representation) from `structuredContent` (parsed data). This improves the user experience when viewing tool results and aligns with MCP best practices.

---

### Investigate MCP Server Status/Metadata Reporting

**Description:**
Explore whether MCP provides mechanisms for servers to report status, metadata, or context information that clients (Claude, Gemini) display in their UI. This could help users see which gwsa profile is active without calling a tool.

**Current State:**
- `get_active_profile` tool exists - LLM must explicitly call it
- FastMCP `name` parameter: `mcp = FastMCP("gwsa")` - sets server name

**MCP Mechanisms to Investigate:**

1. **Server Implementation Info** (initialization handshake):
   ```python
   # FastMCP may support setting version/description
   mcp = FastMCP(
       name="gwsa",
       version="0.2.1",
       description="Google Workspace Access - Gmail, Docs"
   )
   ```

2. **Protected Resource Metadata** (2025 spec):
   - `.well-known` URLs for server discovery
   - JSON file describing purpose, endpoints, auth methods

3. **Tasks API** (2025-11-25 spec):
   - New abstraction for tracking work status
   - Clients can query task status

**Questions to Answer:**
- Does Claude/Gemini read and display server `name`/`version`/`description`?
- Can we include dynamic info (like active profile) in server metadata?
- Is there a "status" or "health" concept in MCP that clients poll?

**Action Items:**
1. Check FastMCP constructor parameters for metadata options
2. Test what Claude/Gemini display for server info
3. If dynamic status isn't supported, document that `get_active_profile` is the pattern

**Reference:**
- MCP Changelog: https://modelcontextprotocol.io/specification/2025-11-25/changelog
- Server Implementation interface in MCP spec

---

### Add Google Drive Tools to MCP Server

**Description:**
Extend the MCP server with Google Drive capabilities for file/folder management. This enables workflows like finding a folder, listing its contents, and uploading/downloading files.

**Proposed Tools:**

| Tool | Description |
|------|-------------|
| `drive_search` | Search for files/folders by name, type, or query |
| `drive_list_folder` | List contents of a folder by ID (or root) |
| `drive_get_file_info` | Get metadata for a file/folder by ID |
| `drive_create_folder` | Create a new folder (optionally in a parent folder) |
| `drive_upload` | Upload a file to a folder by ID |
| `drive_download` | Download a file by ID |

**Example Workflows:**

1. **Find and upload to a folder:**
   ```
   User: "Upload this report to my 'Project Reports' folder"
   LLM: 1. drive_search(query="name='Project Reports' and mimeType='folder'")
        2. drive_upload(folder_id="...", filename="report.txt", content="...")
   ```

2. **List and download:**
   ```
   User: "What's in my shared folder? Download the latest zip."
   LLM: 1. drive_list_folder(folder_id="...")
        2. drive_download(file_id="...")
   ```

**Implementation Notes:**

1. **SDK Layer First:** Add `gwsa/sdk/drive.py` with core functions:
   ```python
   def search_files(query: str, max_results: int = 25) -> list[dict]
   def list_folder(folder_id: str = "root") -> list[dict]
   def get_file_metadata(file_id: str) -> dict
   def create_folder(name: str, parent_id: str = None) -> dict
   def upload_file(folder_id: str, filename: str, content: bytes, mime_type: str) -> dict
   def download_file(file_id: str) -> bytes
   ```

2. **MCP Tools:** Add to `gwsa/mcp/server.py` wrapping SDK functions

3. **Supported File Types for Upload:**
   - Text files (.txt, .md, .json, .csv, etc.)
   - Binary files (.zip, .pdf, .png, etc.)
   - Content passed as base64 for binary

4. **Google Drive API Scopes:**
   - `https://www.googleapis.com/auth/drive.file` (files created/opened by app)
   - Or `https://www.googleapis.com/auth/drive` (full access)
   - May require updating `gwsa setup` to request additional scopes

5. **File Size Considerations:**
   - MCP has practical limits on response size
   - Large file downloads should return a signed URL or stream
   - Consider chunked upload for large files

**API Reference:**
- Google Drive API: https://developers.google.com/drive/api/v3/reference

**Reasoning:**
Google Drive is a core part of Google Workspace. Adding Drive tools enables powerful document management workflows directly from AI assistants - finding project folders, uploading deliverables, downloading shared files, and organizing content.
