"""Exceptions raised by the Sportmonks integration."""


class SportmonksError(Exception):
    """Base class for all Sportmonks integration errors."""


class SportmonksAuthError(SportmonksError):
    """The Sportmonks API rejected the configured API token (401/403)."""


class SportmonksRateLimitError(SportmonksError):
    """Sportmonks rate limits were exceeded even after retrying."""


class SportmonksAPIError(SportmonksError):
    """A non-recoverable error occurred while calling the Sportmonks API."""
