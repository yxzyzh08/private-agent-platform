"""Platform custom exceptions.

All platform-specific exceptions inherit from PlatformError.
"""


class PlatformError(Exception):
    """Base exception for all platform errors."""


class ToolError(PlatformError):
    """Error during tool execution."""


class ChannelError(PlatformError):
    """Error in channel operations."""


class PermissionDeniedError(PlatformError):
    """Raised when an agent attempts to use an unauthorized tool."""


class RateLimitError(PlatformError):
    """Raised when a user exceeds the rate limit."""


class ValidationError(PlatformError):
    """Raised when input validation fails (e.g., JSON Schema)."""


class WebhookVerificationError(ChannelError):
    """Raised when webhook signature verification fails."""


class SessionRotationError(PlatformError):
    """Raised when session rotation encounters an unrecoverable error."""
