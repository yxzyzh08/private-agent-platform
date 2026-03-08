"""Base tool interface and result dataclass.

All platform tools must inherit from BaseTool and implement execute().
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field

import jsonschema

from core.errors import ValidationError


@dataclass
class ToolResult:
    """Result returned by tool execution."""

    success: bool
    data: dict | None = None
    error: str | None = None


class BaseTool(ABC):
    """Abstract base class for all platform tools.

    Subclasses must set name, description, input_schema and implement execute().
    """

    name: str = ""
    description: str = ""
    input_schema: dict = field(default_factory=dict)

    async def validate_input(self, params: dict) -> bool:
        """Validate params against input_schema using JSON Schema.

        Args:
            params: The parameters to validate.

        Returns:
            True if validation passes.

        Raises:
            ValidationError: If validation fails.
        """
        if not self.input_schema:
            return True

        try:
            jsonschema.validate(instance=params, schema=self.input_schema)
        except jsonschema.ValidationError as e:
            raise ValidationError(f"Input validation failed for {self.name}: {e.message}") from e

        return True

    @abstractmethod
    async def execute(self, params: dict) -> ToolResult:
        """Execute the tool with validated parameters.

        Args:
            params: Validated input parameters.

        Returns:
            ToolResult with success status and data or error.
        """

    async def cleanup(self) -> None:
        """Release resources. Override in subclasses if needed."""
