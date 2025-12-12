### Enhance 403 Error Message in MCP Server for Google Docs

**Description:**
When the `gwsa-mcp` server's `read_doc` tool encounters an `HttpError` with a 403 status code (Permission Denied) from the Google Docs API, the error message returned to the MCP client should be more informative. It should explicitly suggest that the user check their `gwsa` profile for correct permissions.

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