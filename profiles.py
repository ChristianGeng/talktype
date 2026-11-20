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

import os
import stat
from pathlib import Path
from typing import NamedTuple

import yaml

# Config sections that must stay mappings after the merge.
SECTIONS = (
    "hotkeys",
    "transcription",
    "ui",
    "history",
    "recording",
    "text",
    "replacements",
)


class ProfileError(Exception):
    """The profile can't be read, or isn't a valid profile."""


class Profile(NamedTuple):
    name: str  # the file's name without .yaml: the link target's, for a link
    data: dict


def merge(base: dict, overlay: dict) -> dict:
    """`base` with `overlay` on top, deep for mappings; neither is changed."""
    merged = dict(base)
    for key, value in overlay.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = merge(merged[key], value)
        else:
            merged[key] = value
    return merged


def read(path: Path) -> Profile | None:
    """The profile at `path`, None if there is none (a dangling link counts).

    A link is resolved once, so the name and the data come from the same
    file even if the link changes meanwhile.
    """
    target = path.resolve()
    try:
        mode = os.stat(target).st_mode
    except FileNotFoundError:
        return None
    except OSError as e:
        raise ProfileError(
            f"profile {path} can't be checked: {e.strerror or e}"
        ) from None
    if not stat.S_ISREG(mode):
        raise ProfileError(f"profile {path} is not a regular file")
    try:
        text = target.read_text(encoding="utf-8")
        data = yaml.safe_load(text)
    except (OSError, UnicodeError, yaml.YAMLError) as e:
        raise ProfileError(f"profile {path} can't be read: {e}") from None
    if data is None:
        if any(
            line.strip() and not line.lstrip().startswith("#")
            for line in text.splitlines()
        ):
            raise ProfileError(f"profile {path} must be a mapping, got null")
        data = {}
    if not isinstance(data, dict):
        raise ProfileError(
            f"profile {path} must be a mapping, got {type(data).__name__}"
        )
    for section in SECTIONS:
        if (
            section in data
            and data[section] is not None
            and not isinstance(data[section], dict)
        ):
            raise ProfileError(
                f"profile {path}: {section} must be a mapping, got {type(data[section]).__name__}"
            )
    return Profile(target.stem, data)
