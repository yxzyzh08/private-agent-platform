"""Platform configuration loader.

Reads config/platform.yaml and provides a singleton access interface.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from core.errors import PlatformError

_config: dict[str, Any] | None = None
_DEFAULT_CONFIG_PATH = Path(__file__).resolve().parent.parent / "config" / "platform.yaml"


class ConfigError(PlatformError):
    """Configuration loading or validation error."""


def load_config(path: str | Path | None = None) -> dict[str, Any]:
    """Load and parse the platform YAML configuration file.

    Args:
        path: Path to the YAML config file. Defaults to config/platform.yaml.

    Returns:
        Parsed configuration dictionary.

    Raises:
        ConfigError: If the file does not exist or contains invalid YAML.
    """
    global _config

    config_path = Path(path) if path else _DEFAULT_CONFIG_PATH

    if not config_path.exists():
        raise ConfigError(f"Config file not found: {config_path}")

    try:
        with open(config_path) as f:
            config = yaml.safe_load(f)
    except yaml.YAMLError as e:
        raise ConfigError(f"Invalid YAML in {config_path}: {e}") from e

    if not isinstance(config, dict):
        raise ConfigError(f"Config must be a YAML mapping, got {type(config).__name__}")

    _config = config
    return config


def get_config() -> dict[str, Any]:
    """Get the loaded configuration singleton.

    Loads from the default path if not yet loaded.

    Returns:
        The platform configuration dictionary.
    """
    global _config
    if _config is None:
        _config = load_config()
    return _config


def reset_config() -> None:
    """Reset the config singleton. Useful for testing."""
    global _config
    _config = None
