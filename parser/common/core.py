import json
from os import PathLike
from pathlib import Path

from parser.entities.default_config import DEFAULT_PARSER_CONFIG
from parser.entities.table_entities import Entities


class ParserValidationError(ValueError):
    """Raised when parser output cannot be handed to the solver."""


class ParserConfigMixin:
    def __init__(self):
        super().__init__()

    @classmethod
    def _load_config(cls, config: dict | str | PathLike | None) -> dict:
        """Load parser config.json and deep-merge it over the built-in defaults."""
        user_config: dict = {}
        if config is None:
            path = Path(Entities.config_file)
            if path.exists():
                with path.open(encoding="utf-8") as file:
                    user_config = json.load(file)
        elif isinstance(config, dict):
            user_config = config
        else:
            with Path(config).open(encoding="utf-8") as file:
                user_config = json.load(file)
        return cls._deep_merge(DEFAULT_PARSER_CONFIG, user_config)

    @classmethod
    def _deep_merge(cls, base: dict, override: dict) -> dict:
        result = {key: cls._deep_merge(value, {}) if isinstance(value, dict) else value
                  for key, value in base.items()}
        for key, value in (override or {}).items():
            if isinstance(value, dict) and isinstance(result.get(key), dict):
                result[key] = cls._deep_merge(result[key], value)
            else:
                result[key] = value
        return result

