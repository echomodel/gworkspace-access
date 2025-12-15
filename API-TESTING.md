# API Enablement Testing Plan

This document captures the testing needed to definitively determine which GCP project needs APIs enabled for each authentication method.

## Background

When calling Google Workspace APIs, you may get "API not enabled" errors. The question is: **which project needs the API enabled?**

There are several candidates:
1. **OAuth Client Project** - The project where `client_secrets.json` was created
2. **ADC Quota Project** - Set via `gcloud auth application-default set-quota-project`
3. **gcloud Config Project** - Set via `gcloud config set project`

We need to isolate which one(s) matter for each authentication method.

## Current Assumptions (Unverified)

| Auth Method | Where to Enable APIs (assumed) |
|-------------|-------------------------------|
| Token Profile | OAuth Client Project |
| ADC + `--client-id-file` | OAuth Client Project |
| Pure ADC | Quota Project |

**Open questions:**
- Does `gcloud config project` ever matter?
- Are "quota project" and "API enablement project" always the same?
- Does it differ between personal Gmail and corporate/Workspace accounts?

## Prerequisites

You need **three distinct GCP projects** where you have Owner or Editor access:
- **Project A** - Will be used as OAuth client project
- **Project B** - Will be used as ADC quota project
- **Project C** - Will be used as gcloud config project

Ensure **none of them** have the test API enabled initially. Use an API that's easy to toggle, like `docs.googleapis.com`.

## Test Setup

### Check current API state
```bash
gcloud services list --enabled --project=PROJECT_A | grep -i docs
gcloud services list --enabled --project=PROJECT_B | grep -i docs
gcloud services list --enabled --project=PROJECT_C | grep -i docs
```

### Disable the test API in all three
```bash
gcloud services disable docs.googleapis.com --project=PROJECT_A --force
gcloud services disable docs.googleapis.com --project=PROJECT_B --force
gcloud services disable docs.googleapis.com --project=PROJECT_C --force
```

### Create OAuth client in Project A
1. Go to Google Cloud Console → Project A → APIs & Services → Credentials
2. Create OAuth client ID (Desktop app)
3. Download as `client_secrets.json`

### Configure gcloud
```bash
# Set config project to C
gcloud config set project PROJECT_C

# Verify
gcloud config get-value project  # Should show PROJECT_C
```

---

## Test Matrix

Three projects involved:
- **Project A** = OAuth client project (where `client_secrets.json` was created)
- **Project B** = ADC quota project (set via `gcloud auth application-default set-quota-project`)
- **Project C** = gcloud config project (set via `gcloud config set project`)

For each auth mode, we test **all three permutations**: API enabled in only A, only B, or only C.

---

### Test 1: Token Profile (Non-ADC)

Token profiles use `client_secrets.json` directly via gwsa, not via ADC.

**One-time setup:**
```bash
gwsa client import /path/to/client_secrets.json  # Created in Project A
gwsa profiles add test-profile
gwsa profiles use test-profile

# Set gcloud config project to C (to isolate it from A)
gcloud config set project PROJECT_C

# Set ADC quota project to B (even though we're not using ADC, to ensure isolation)
gcloud auth application-default set-quota-project PROJECT_B
```

**Verify three distinct projects:**
```bash
echo "OAuth client project: PROJECT_A (from client_secrets.json)"
echo "Quota project: $(cat ~/.config/gcloud/application_default_credentials.json | jq -r '.quota_project_id')"
echo "Config project: $(gcloud config get-value project)"
```

**Scenario 1.1: API enabled ONLY in OAuth client project (A)**
```bash
# Ensure all disabled first
gcloud services disable docs.googleapis.com --project=PROJECT_A --force 2>/dev/null
gcloud services disable docs.googleapis.com --project=PROJECT_B --force 2>/dev/null
gcloud services disable docs.googleapis.com --project=PROJECT_C --force 2>/dev/null

# Enable only in A
gcloud services enable docs.googleapis.com --project=PROJECT_A

# TEST
python3 test_script.py --mode=token-profile

# Record result: PASS / FAIL
# Cleanup
gcloud services disable docs.googleapis.com --project=PROJECT_A --force
```

**Scenario 1.2: API enabled ONLY in quota project (B)**
```bash
# Ensure all disabled first
gcloud services disable docs.googleapis.com --project=PROJECT_A --force 2>/dev/null
gcloud services disable docs.googleapis.com --project=PROJECT_B --force 2>/dev/null
gcloud services disable docs.googleapis.com --project=PROJECT_C --force 2>/dev/null

# Enable only in B
gcloud services enable docs.googleapis.com --project=PROJECT_B

# TEST
python3 test_script.py --mode=token-profile

# Record result: PASS / FAIL
# Cleanup
gcloud services disable docs.googleapis.com --project=PROJECT_B --force
```

**Scenario 1.3: API enabled ONLY in gcloud config project (C)**
```bash
# Ensure all disabled first
gcloud services disable docs.googleapis.com --project=PROJECT_A --force 2>/dev/null
gcloud services disable docs.googleapis.com --project=PROJECT_B --force 2>/dev/null
gcloud services disable docs.googleapis.com --project=PROJECT_C --force 2>/dev/null

# Enable only in C
gcloud services enable docs.googleapis.com --project=PROJECT_C

# TEST
python3 test_script.py --mode=token-profile

# Record result: PASS / FAIL
# Cleanup
gcloud services disable docs.googleapis.com --project=PROJECT_C --force
```

---

### Test 2: Pure ADC (No client-id-file)

Pure ADC uses Google's built-in gcloud OAuth client. No user-controlled OAuth client project.

**Note:** Pure ADC may be blocked for Workspace scopes on personal Gmail accounts. Use a corporate/Workspace account.

**One-time setup:**
```bash
# Login with pure ADC (no --client-id-file)
gcloud auth application-default login \
  --scopes=https://www.googleapis.com/auth/documents.readonly,openid,https://www.googleapis.com/auth/userinfo.email

# Set quota project to B
gcloud auth application-default set-quota-project PROJECT_B

# Set config project to C
gcloud config set project PROJECT_C
```

**Verify:**
```bash
echo "OAuth client project: N/A (using Google's gcloud client)"
echo "Quota project: $(cat ~/.config/gcloud/application_default_credentials.json | jq -r '.quota_project_id')"
echo "Config project: $(gcloud config get-value project)"
```

**Scenario 2.1: API enabled ONLY in quota project (B)**
```bash
# Ensure all disabled first
gcloud services disable docs.googleapis.com --project=PROJECT_B --force 2>/dev/null
gcloud services disable docs.googleapis.com --project=PROJECT_C --force 2>/dev/null

# Enable only in B
gcloud services enable docs.googleapis.com --project=PROJECT_B

# TEST
python3 test_script.py --mode=adc

# Record result: PASS / FAIL
# Cleanup
gcloud services disable docs.googleapis.com --project=PROJECT_B --force
```

**Scenario 2.2: API enabled ONLY in gcloud config project (C)**
```bash
# Ensure all disabled first
gcloud services disable docs.googleapis.com --project=PROJECT_B --force 2>/dev/null
gcloud services disable docs.googleapis.com --project=PROJECT_C --force 2>/dev/null

# Enable only in C
gcloud services enable docs.googleapis.com --project=PROJECT_C

# TEST
python3 test_script.py --mode=adc

# Record result: PASS / FAIL
# Cleanup
gcloud services disable docs.googleapis.com --project=PROJECT_C --force
```

*Note: No test for "OAuth client project" because pure ADC uses Google's client, not yours.*

---

### Test 3: ADC with `--client-id-file`

Uses your own OAuth client via the ADC system. Three projects in play.

**One-time setup:**
```bash
# Login with ADC using YOUR client
gcloud auth application-default login \
  --client-id-file=/path/to/client_secrets.json \
  --scopes=https://www.googleapis.com/auth/documents.readonly,openid,https://www.googleapis.com/auth/userinfo.email

# Set quota project to B (different from OAuth client project A)
gcloud auth application-default set-quota-project PROJECT_B

# Set config project to C
gcloud config set project PROJECT_C
```

**Verify three distinct projects:**
```bash
echo "OAuth client project: PROJECT_A (from client_secrets.json)"
echo "Quota project: $(cat ~/.config/gcloud/application_default_credentials.json | jq -r '.quota_project_id')"
echo "Config project: $(gcloud config get-value project)"
```

**Scenario 3.1: API enabled ONLY in OAuth client project (A)**
```bash
# Ensure all disabled first
gcloud services disable docs.googleapis.com --project=PROJECT_A --force 2>/dev/null
gcloud services disable docs.googleapis.com --project=PROJECT_B --force 2>/dev/null
gcloud services disable docs.googleapis.com --project=PROJECT_C --force 2>/dev/null

# Enable only in A
gcloud services enable docs.googleapis.com --project=PROJECT_A

# TEST
python3 test_script.py --mode=adc

# Record result: PASS / FAIL
# Cleanup
gcloud services disable docs.googleapis.com --project=PROJECT_A --force
```

**Scenario 3.2: API enabled ONLY in quota project (B)**
```bash
# Ensure all disabled first
gcloud services disable docs.googleapis.com --project=PROJECT_A --force 2>/dev/null
gcloud services disable docs.googleapis.com --project=PROJECT_B --force 2>/dev/null
gcloud services disable docs.googleapis.com --project=PROJECT_C --force 2>/dev/null

# Enable only in B
gcloud services enable docs.googleapis.com --project=PROJECT_B

# TEST
python3 test_script.py --mode=adc

# Record result: PASS / FAIL
# Cleanup
gcloud services disable docs.googleapis.com --project=PROJECT_B --force
```

**Scenario 3.3: API enabled ONLY in gcloud config project (C)**
```bash
# Ensure all disabled first
gcloud services disable docs.googleapis.com --project=PROJECT_A --force 2>/dev/null
gcloud services disable docs.googleapis.com --project=PROJECT_B --force 2>/dev/null
gcloud services disable docs.googleapis.com --project=PROJECT_C --force 2>/dev/null

# Enable only in C
gcloud services enable docs.googleapis.com --project=PROJECT_C

# TEST
python3 test_script.py --mode=adc

# Record result: PASS / FAIL
# Cleanup
gcloud services disable docs.googleapis.com --project=PROJECT_C --force
```

---

## Test Script

Simple Python test script to check if Docs API is accessible:

```python
import google.auth
from googleapiclient.discovery import build

def test_docs_api(use_adc=False, profile=None):
    if use_adc:
        creds, project = google.auth.default()
        print(f"Using ADC, project={project}")
    else:
        from gwsa.sdk.auth import get_credentials
        creds, source = get_credentials(profile=profile)
        print(f"Using profile, source={source}")

    service = build('docs', 'v1', credentials=creds)
    try:
        # Try to get a nonexistent doc - 404 means API is enabled
        service.documents().get(documentId='nonexistent').execute()
    except Exception as e:
        error = str(e)
        if '404' in error or 'not found' in error.lower():
            print("SUCCESS: API is enabled (got 404 for nonexistent doc)")
            return True
        elif 'not been used' in error or 'disabled' in error:
            print(f"FAIL: API not enabled")
            print(f"Error: {error[:300]}")
            return False
        else:
            print(f"OTHER ERROR: {error[:300]}")
            return None

# For token profile:
# test_docs_api(profile='test-profile')

# For ADC:
# test_docs_api(use_adc=True)
```

---

## Results Template

Fill in after testing:

### Test 1: Token Profile (Non-ADC) Results

| Scenario | API Enabled In | Result | Error (if any) |
|----------|---------------|--------|----------------|
| 1.1 | OAuth client project (A) | | |
| 1.2 | Quota project (B) | | |
| 1.3 | Config project (C) | | |

**Conclusion for Token Profiles:**
- Which project(s) work? ________________
- Which project(s) fail? ________________

### Test 2: Pure ADC Results

| Scenario | API Enabled In | Result | Error (if any) |
|----------|---------------|--------|----------------|
| 2.1 | Quota project (B) | | |
| 2.2 | Config project (C) | | |

**Conclusion for Pure ADC:**
- Which project(s) work? ________________
- Which project(s) fail? ________________

### Test 3: ADC + client-id-file Results

| Scenario | API Enabled In | Result | Error (if any) |
|----------|---------------|--------|----------------|
| 3.1 | OAuth client project (A) | | |
| 3.2 | Quota project (B) | | |
| 3.3 | Config project (C) | | |

**Conclusion for ADC + client-id-file:**
- Which project(s) work? ________________
- Which project(s) fail? ________________

### Overall Summary

| Auth Mode | Project That Must Have API Enabled |
|-----------|-----------------------------------|
| Token Profile | |
| Pure ADC | |
| ADC + client-id-file | |

**Does gcloud config project ever matter?** ________________

**Is quota project and API-enabled project always the same?** ________________

---

## Partial Results (From Previous Session)

### Token Profile
- Error message explicitly named the OAuth client project number
- Suggests OAuth client project is what matters
- **Not fully isolated** - didn't test if enabling in config project also works

### ADC + client-id-file
- Test with three distinct projects:
  - Config = project with no Docs API
  - Quota = project with no Docs API
  - OAuth client = project WITH Docs API
- Result: **Docs API worked**
- **Conclusion:** OAuth client project matters for this mode
- **Not tested:** Would it also work if only quota or config project had API?

### Pure ADC
- **Could not test** - Google's gcloud OAuth client was blocked for Workspace scopes on personal Gmail accounts ("This app is blocked" error)
- Need to test with corporate/Workspace account where pure ADC is allowed

---

## Files to Update After Testing

Based on results, review and update:

1. **GOOGLE-API-ACCESS.md** - Main doc with "Where to Enable APIs" table
   - Section: "Step 2: Which Project to Enable Them In"
   - Section: "Quota Project (ADC only)"
   - Troubleshooting section

2. **README.md** - If any high-level guidance changes

3. **PROFILES.md** - If profile behavior differs from documented

Current guidance in GOOGLE-API-ACCESS.md:
```markdown
| If you use... | Enable APIs in... |
|---------------|-------------------|
| Token Profile | The OAuth client project |
| ADC with --client-id-file | The OAuth client project |
| Pure ADC | Your quota project |
```

Open questions for further testing:
- Does gcloud config project ever matter for any auth mode?
- Is quota project and API-enablement project always the same for pure ADC?
- Is the guidance different for corporate vs personal accounts?

---

## Additional Questions to Investigate

1. **Quota vs API enablement**: Are these truly the same project, or can they differ?
   - Quota = where usage is counted/billed
   - API enablement = where permission to call is checked

2. **Error messages**: Do error messages always indicate the correct project?

3. **Service accounts**: Does behavior differ for service account auth?

4. **Corporate policies**: Do org policies affect which project is checked?
