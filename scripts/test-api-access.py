# scripts/test_script.py
"""
This script is a crucial tool for the API enablement testing plan outlined in
the root 'API-TESTING.md' document. Its primary purpose is to programmatically
check if the Google Docs API is accessible under different authentication and
project configuration scenarios.

Purpose & Methodology:
----------------------
The central question we are answering is: "When an API is not enabled, which
GCP project must the user enable it in?" This script helps answer that by
isolating three key project types:
1.  OAuth Client Project (Project A): Where a user's client_secrets.json is created.
2.  ADC Quota Project (Project B): Set via `gcloud auth application-default set-quota-project`.
3.  gcloud Config Project (Project C): The default project for the gcloud CLI.

The script is called for each scenario defined in API-TESTING.md. For example,
to test a Token Profile, we might enable the Docs API ONLY in the OAuth Client
Project (A) and disable it in B and C. If this script passes, it proves that
for Token Profiles, the OAuth Client Project is the pivotal one.

Updating Documentation:
----------------------
The findings from each run of this script are used to update the results
tables in 'API-TESTING.md'. By systematically testing each permutation, we
gather the evidence needed to create definitive, logical documentation about
how Google Cloud and Workspace APIs behave. The final, validated conclusions
will be used to update the main 'GOOGLE-API-ACCESS.md' guide, ensuring it
provides clear, proven instructions for users.

Configuration:
--------------
This script does not contain any sensitive information. All parameters, such as
project IDs, user emails, and document IDs, are loaded from a separate
'scripts/test-api-access.yaml' file, which is not checked into version control.
An example file, 'scripts/test-api-access.yaml.example', is provided to show
the required structure.
"""
import google.auth
from googleapiclient.discovery import build
import argparse
import sys
import yaml
from pathlib import Path

CONFIG_PATH = Path(__file__).parent / "test-api-access.yaml"

def load_test_config():
    """Loads test parameters from the YAML config file."""
    if not CONFIG_PATH.exists():
        print(f"FAIL: Configuration file not found at {CONFIG_PATH}")
        print("Please copy 'scripts/test-api-access.yaml.example' to 'scripts/test-api-access.yaml' and fill it out.")
        sys.exit(1)
    with open(CONFIG_PATH, 'r') as f:
        return yaml.safe_load(f)

def test_docs_api(use_adc=False, profile=None, doc_id=None):
    """
    Attempts to access the Google Docs API and returns True on success,
    False on failure.
    """
    if not doc_id:
        print("FAIL: No document ID provided for the test.")
        return False

    creds = None
    try:
        if use_adc:
            creds, project = google.auth.default()
            print(f"Using ADC, discovered project_id={project}")
        else:
            from gwsa.sdk.auth import get_credentials
            creds, source = get_credentials(profile=profile)
            print(f"Using profile '{profile}', source={source}")

    except Exception as e:
        print(f"FAIL: Could not get credentials.")
        print(f"Error: {e}")
        return False

    if not creds:
        print("FAIL: Credentials could not be loaded.")
        return False

    service = build('docs', 'v1', credentials=creds)
    try:
        doc = service.documents().get(documentId=doc_id).execute()
        print(f"SUCCESS: API is enabled and functional. Read document '{doc.get('title', 'Unknown Title')}' (ID: {doc_id})")
        return True
    except Exception as e:
        error = str(e)
        if 'not been used' in error or 'disabled' in error:
            print(f"FAIL: API not enabled")
            print(f"Error: {error[:300]}")
            return False
        elif 'PERMISSION_DENIED' in error or 'Client is not authorized' in error:
            print(f"FAIL: Permission denied to read document (API may be enabled, but user lacks access to this doc).")
            print(f"Error: {error[:300]}")
            return False
        else:
            print(f"OTHER ERROR: {error[:300]}")
            return None

if __name__ == '__main__':
    parser = argparse.ArgumentParser(
        description="Test Docs API access based on scenarios in API-TESTING.md.",
        formatter_class=argparse.RawTextHelpFormatter
    )
    parser.add_argument('--mode', choices=['token-profile', 'adc'], required=True, help="Authentication mode to test.")
    
    args = parser.parse_args()
    config = load_test_config()

    result = False
    if args.mode == 'token-profile':
        test_params = config.get('token_profile_test', {})
        profile_name = test_params.get('profile_name')
        document_id = test_params.get('doc_id')
        if not profile_name or not document_id:
            print("FAIL: 'profile_name' and 'doc_id' must be set in test-api-access.yaml for token_profile_test.")
            sys.exit(1)
        result = test_docs_api(profile=profile_name, doc_id=document_id)
    elif args.mode == 'adc':
        test_params = config.get('adc_test', {})
        document_id = test_params.get('doc_id')
        if not document_id:
            print("FAIL: 'doc_id' must be set in test-api-access.yaml for adc_test.")
            sys.exit(1)
        result = test_docs_api(use_adc=True, doc_id=document_id)

    if result is True:
        sys.exit(0)  # Success
    else:
        sys.exit(1)  # Fail or other error
