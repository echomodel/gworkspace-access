class GWSAError(Exception):
    """Base class for all GWSA exceptions."""
    pass

class ValidationError(GWSAError):
    """Base class for validation errors."""
    pass

class LocalPathError(ValidationError):
    """Raised when an input appears to be a local file path instead of a resource ID."""
    pass

class InvalidDocIdError(ValidationError):
    """Raised when a document ID is malformed."""
    pass
