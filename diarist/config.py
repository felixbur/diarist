"""Configuration: package defaults, optionally overridden by a user YAML file."""

import copy
import pathlib

import yaml

DEFAULT_CONFIG = pathlib.Path(__file__).parent / "default_config.yaml"


def merge(base: dict, override: dict) -> dict:
    """Recursively merge ``override`` into a copy of ``base``; lists are replaced."""
    result = copy.deepcopy(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = merge(result[key], value)
        else:
            result[key] = value
    return result


def load_config(path: str | None = None) -> dict:
    """The default configuration, overridden by the YAML file ``path``."""
    with open(DEFAULT_CONFIG) as fp:
        config = yaml.safe_load(fp)
    if path is not None:
        with open(path) as fp:
            user = yaml.safe_load(fp) or {}
        config = merge(config, user)
    return config
