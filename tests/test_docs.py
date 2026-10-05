"""The documented setup lists what the code and CI need."""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def apt_packages(path, command):
    line = next(
        line for line in (ROOT / path).read_text().splitlines() if command in line
    )
    return set(re.split(r"\s+", line.split(command, 1)[1].strip()))


def test_claude_md_installs_what_ci_installs():
    ci = apt_packages(".github/workflows/tests.yml", "apt-get install -y")
    documented = apt_packages("CLAUDE.md", "sudo apt install")
    assert ci <= documented, ci - documented


def test_the_install_lines_have_what_terminal_paste_needs():
    for path in ("CLAUDE.md", "README.md"):
        assert {"xdotool", "xclip"} <= apt_packages(path, "sudo apt install"), path
