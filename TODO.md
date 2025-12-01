# TODO

## Future Enhancement: Application Default Credentials (ADC) Support

Consider adding ADC as an alternative to the current OAuth token flow. See [AUTHENTICATION.md](AUTHENTICATION.md) for detailed compatibility testing results.

### Implementation Plan

Support both paths - ADC with fallback to token file:

```python
def load_credentials(token_path=None):
    # Try explicit token file first
    if token_path and os.path.exists(token_path):
        return Credentials.from_authorized_user_file(token_path, SCOPES)

    # Fall back to ADC
    credentials, _ = google.auth.default(scopes=SCOPES)
    return credentials
```

### When to Implement

- When simplifying onboarding for new users
- When majority of users are on Workspace or regular Gmail (not APP)
- Keep `create-token` as fallback for APP users and Gmail with security keys
