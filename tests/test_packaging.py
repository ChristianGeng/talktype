"""Every module in the repository root is part of the installed tool.

autostop.py (#49) was missing from py-modules: the tests passed from the
checkout, but the installed `talktype` stopped at start-up with
ModuleNotFoundError. Checking pyproject.toml directly is reliable; a test
that builds a wheel is not, because setuptools reuses a stale build/ dir.
No display needed.
"""

import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def test_every_root_module_is_in_py_modules():
    config = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    listed = {f"{name}.py" for name in config["tool"]["setuptools"]["py-modules"]}
    modules = {path.name for path in ROOT.glob("*.py")}
    assert modules - listed == set(), "add these to [tool.setuptools] py-modules"
    assert listed - modules == set(), "py-modules lists files that don't exist"
