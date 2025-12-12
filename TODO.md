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
