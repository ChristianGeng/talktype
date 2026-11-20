"""Profiles: a small YAML file merged on top of the config.

A profile holds only what differs from the config, typically the few
transcription keys that make up a setup (local Nemotron, the API only, …).
`~/.config/talktype/profile.yaml`, usually a symlink to one of several
profile files, is read after `config.yaml`; switching setups is changing
the link and restarting.

Mappings merge key by key, at every depth; any other value, lists
included, replaces the config's. No audio or X11 dependencies, so it can be
tested on its own.
"""

from pathlib import Path

import yaml


class ProfileError(Exception):
    """The profile can't be read or isn't a mapping."""


def merge(base: dict, overlay: dict) -> dict:
    """`base` with `overlay` on top, deep for mappings; neither is changed."""
    merged = dict(base)
    for key, value in overlay.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = merge(merged[key], value)
        else:
            merged[key] = value
    return merged


def load(path: Path) -> dict:
    """The profile at `path`; {} if there is none (a dangling link counts)."""
    if not path.exists():
        return {}
    try:
        with open(path, encoding="utf-8") as f:
            data = yaml.safe_load(f)
    except (OSError, yaml.YAMLError) as e:
        raise ProfileError(f"profile {path} can't be read: {e}") from None
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise ProfileError(
            f"profile {path} must be a mapping, got {type(data).__name__}"
        )
    return data


def name(path: Path) -> str:
    """The profile's name: the file a symlink points to, without .yaml."""
    return path.resolve().stem if path.is_symlink() else path.stem
