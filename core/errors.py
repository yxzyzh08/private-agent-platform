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


# Phase 1C: Task Planning errors


class TaskPlanError(PlatformError):
    """Base error for task plan operations."""


class TaskExecutionError(PlatformError):
    """Error during subtask execution."""


class SubtaskTimeoutError(TaskExecutionError):
    """Raised when a subtask exceeds its timeout."""


class DirtyGitStateError(TaskExecutionError):
    """Raised when git working tree is not clean before execution."""


class SensitiveFileError(TaskExecutionError):
    """Raised when a subtask modifies sensitive files."""


class CyclicDependencyError(TaskPlanError):
    """Raised when task dependencies contain a cycle."""


class PhaseParseError(TaskPlanError):
    """Raised when a phase markdown file cannot be parsed."""
