"""shared exception classes for use by other modules."""
from django.core.exceptions import ValidationError


class BadURLError(ValueError):
    pass


class AlreadyLosslessError(ValidationError):
    pass


class AlreadyDeletedError(ValidationError):
    pass
