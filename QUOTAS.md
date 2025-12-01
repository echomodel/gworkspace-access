# Quotas and Billing for Google Workspace APIs

This guide explains how quotas and billing work when using Google SDKs to access Google Workspace APIs (Gmail, Docs, Sheets, Drive, etc.).

## Key Concepts

### Two Types of Projects

When using Google APIs, there are potentially two different projects involved:

1. **OAuth Client Project** - The Google Cloud project where you created your OAuth client ID. This project:
   - Must have the relevant APIs enabled (Docs API, Gmail API, etc.)
   - Is checked for API enablement when you make requests
   - Is identified by the `client_id` in your token

2. **Quota Project** - The project used for quota tracking and billing (if applicable). This can be:
   - The same as your OAuth client project
   - A different project specified via `quota_project_id`
   - Unspecified (which triggers the "No project ID could be determined" warning)

### Two Types of APIs

Google Cloud has two categories of APIs with different quota behaviors:

1. **Resource-based APIs** (most Workspace APIs)
   - Quota is tied to the resource being accessed
   - Examples: Docs API, Sheets API, Drive API, Gmail API
   - The OAuth client project is used for quota tracking
   - `quota_project_id` is generally not needed

2. **Client-based APIs**
   - No specific resource context, so a quota project must be specified
   - Examples: Cloud Translation API, Cloud Vision API
   - Requires explicit `quota_project_id` or will fail

## Google Workspace APIs: Free with Generous Quotas

**Good news:** All Google Workspace APIs are free to use. There are no charges for API requests.

### Typical Quota Limits

| API | Read Requests | Write Requests |
|-----|---------------|----------------|
| Docs API | 300/min per user | 60/min per user |
| Sheets API | 300/min per user | 60/min per user |
| Gmail API | 250 quota units/sec | Varies by operation |
| Drive API | 12,000/min per user | 600/min per user |

If you exceed these limits:
- You receive HTTP `429 Too Many Requests`
- You are **not billed** - there are no charges
- Use exponential backoff and retry

### Requesting Higher Quotas

If you need higher limits:
1. Go to Google Cloud Console → APIs & Services → Quotas
2. Select the API and quota you want to increase
3. Click "Edit Quotas" and submit a request

Quota increases are not guaranteed and are reviewed by Google.

## The "No project ID" Warning

When using `google.auth.default()`, you may see:

```
WARNING - No project ID could be determined. Consider running `gcloud config set project`...
```

### Why It Appears

This warning appears when:
- Your credentials don't include a `quota_project_id`
- No `GOOGLE_CLOUD_PROJECT` environment variable is set
- gcloud doesn't have a default project configured

### When You Can Ignore It

For Google Workspace APIs (Docs, Sheets, Gmail, Drive), this warning is **safe to ignore** because:
1. These are resource-based APIs - quota is tracked on the OAuth client project
2. There's no billing - Workspace APIs are free
3. API enablement is checked on the OAuth client project, not the quota project

### When It Matters

The warning becomes important for:
- **Client-based APIs** (Translation, Vision, etc.) - requests may fail without a quota project
- **Paid APIs** - you need to specify which project to bill
- **Quota monitoring** - if you want usage to appear in a specific project's dashboard

## Token Files and the Warning

The "No project ID" warning appears because different token types contain different fields. See [AUTHENTICATION.md - Token File Formats](AUTHENTICATION.md#token-file-formats) for detailed comparison.

**Summary:**
- **gcloud ADC tokens** include `quota_project_id` → no warning
- **Google OAuth library tokens** (from `creds.to_json()`) lack this field → warning appears
- **Service account keys** include `project_id` directly → no warning

For Workspace APIs, the warning from OAuth library tokens is safe to ignore.

## Suppressing the Warning

For local batch jobs and scripts using only Workspace APIs, it's reasonable to suppress this warning. However:

> **Warning:** Do not suppress this warning in server-side applications, reusable libraries, or CLI tools intended for general use. The warning may indicate real configuration issues for users working with paid or client-based APIs.

### Recommended Approaches by Use Case

| Use Case | Recommendation |
|----------|----------------|
| Local batch script (Workspace APIs only) | Safe to suppress with code comments explaining why |
| Server-side application | Don't suppress; log at DEBUG level if noisy |
| Reusable library/CLI | Don't suppress; let users see and handle it |
| Using paid/client-based APIs | Don't suppress; fix the configuration |

### How to Suppress in Python

```python
import logging
import warnings

# Option 1: Suppress the specific warning
logging.getLogger('google.auth._default').setLevel(logging.ERROR)

# Option 2: Filter warnings module
warnings.filterwarnings('ignore', message='.*No project ID could be determined.*')
```

### How to Fix Instead of Suppress

If you need to set a quota project:

```bash
# Set for gcloud ADC
gcloud auth application-default set-quota-project PROJECT_ID

# Or set environment variable
export GOOGLE_CLOUD_PROJECT=my-project-123
```

## References

- [Quota project overview | Google Cloud](https://cloud.google.com/docs/quotas/quota-project)
- [Set the quota project | Google Cloud](https://cloud.google.com/docs/quotas/set-quota-project)
- [Google Docs API Usage Limits](https://developers.google.com/workspace/docs/api/limits)
- [Google Sheets API Usage Limits](https://developers.google.com/sheets/api/limits)
