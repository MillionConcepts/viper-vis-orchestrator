"""shared exception classes for use by other modules."""
from django.core.exceptions import ValidationError


class BadURLError(ValueError):
    """the specified URL is badly-constructed."""
    pass


class AlreadyLosslessError(ValidationError):
    """product is ineligible for PL due to preexisting lossless downlink."""
    pass


class AlreadyDeletedError(ValidationError):
    """product is ineligible for PL because it no longer exists in the CCU."""
    pass
