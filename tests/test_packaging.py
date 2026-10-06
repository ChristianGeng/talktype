"""Every module in the repository root is part of the installed tool.

autostop.py (#49) was missing from py-modules: the tests passed from the
checkout, but the installed `talktype` stopped at start-up with
ModuleNotFoundError. Checking pyproject.toml directly is reliable; a test
that builds a wheel is not, because setuptools reuses a stale build/ dir.
No display needed.
"""

import subprocess
from pathlib import Path

import pytest

tomllib = pytest.importorskip("tomllib")  # Python 3.11+; CI runs 3.13

ROOT = Path(__file__).resolve().parent.parent


def root_modules() -> set[str]:
    """The *.py files in the repository root that git tracks.

    Untracked files (a local config.local.py) are not meant for the wheel.
    """
    try:
        tracked = subprocess.run(
            ["git", "-C", str(ROOT), "ls-files", "--", "*.py"],
            check=True,
            capture_output=True,
            text=True,
        ).stdout.split()
    except (OSError, subprocess.CalledProcessError):
        pytest.skip("needs a git checkout")
    return {name for name in tracked if "/" not in name}


def test_every_root_module_is_in_py_modules():
    config = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    listed = {f"{name}.py" for name in config["tool"]["setuptools"]["py-modules"]}
    modules = root_modules()
    assert modules - listed == set(), "add these to [tool.setuptools] py-modules"
    assert listed - modules == set(), "py-modules lists files git doesn't track"
