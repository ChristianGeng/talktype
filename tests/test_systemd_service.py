"""The setup wizard writes and starts the systemd user unit."""

import io
import os
import subprocess
import sys

import pytest

if not os.environ.get("DISPLAY"):
    pytest.skip(
        "setup_wizard imports pynput, which needs an X display", allow_module_level=True
    )

from rich.console import Console  # noqa: E402

import setup_wizard as sw  # noqa: E402

SYSTEMCTL_CALLS = [
    ["systemctl", "--user", "daemon-reload"],
    ["systemctl", "--user", "reenable", "talktype.service"],
    ["systemctl", "--user", "restart", "talktype.service"],
]


@pytest.fixture
def home(monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path))
    out = io.StringIO()
    monkeypatch.setattr(
        sw,
        "console",
        Console(file=out, width=80, color_system=None, force_terminal=False),
    )
    return tmp_path


@pytest.fixture
def systemctl(monkeypatch):
    """Records the subprocess.run calls; set .error to make the first one raise."""

    class Recorder:
        def __init__(self):
            self.calls = []
            self.error = None

        def run(self, args, **kwargs):
            self.calls.append(args)
            if self.error:
                raise self.error
            return subprocess.CompletedProcess(args, 0)

    recorder = Recorder()
    monkeypatch.setattr(sw.subprocess, "run", recorder.run)
    return recorder


def unit_text(home):
    return (home / ".config" / "systemd" / "user" / "talktype.service").read_text()


def exec_start(text):
    return next(line for line in text.splitlines() if line.startswith("ExecStart="))


def test_unit_starts_with_the_desktop(home, systemctl, monkeypatch):
    monkeypatch.setattr(sw.shutil, "which", lambda cmd: "/usr/bin/talktype")
    sw.install_systemd_service({})
    assert (
        unit_text(home)
        == """[Unit]
Description=TalkType Voice Typing
After=graphical-session.target
PartOf=graphical-session.target

[Service]
Type=simple
ExecStart=/usr/bin/talktype
Restart=on-failure
RestartSec=5
Environment=PYTHONUNBUFFERED=1

[Install]
WantedBy=graphical-session.target
"""
    )


def test_systemctl_reloads_reenables_and_restarts(home, systemctl, monkeypatch):
    monkeypatch.setattr(sw.shutil, "which", lambda cmd: "/usr/bin/talktype")
    sw.install_systemd_service({})
    assert systemctl.calls == SYSTEMCTL_CALLS


def test_without_talktype_on_path_runs_talktype_py(home, systemctl, monkeypatch):
    monkeypatch.setattr(sw.shutil, "which", lambda cmd: None)
    monkeypatch.setattr(sys, "executable", "/opt/py/bin/python3")
    monkeypatch.setattr(sw, "__file__", "/src/talktype/setup_wizard.py")
    sw.install_systemd_service({})
    assert exec_start(unit_text(home)) == (
        "ExecStart=/opt/py/bin/python3 /src/talktype/talktype.py"
    )


def test_paths_with_a_space_are_quoted(home, systemctl, monkeypatch):
    monkeypatch.setattr(sw.shutil, "which", lambda cmd: None)
    monkeypatch.setattr(sys, "executable", "/home/me/My Tools/bin/python3")
    monkeypatch.setattr(sw, "__file__", "/home/me/My Code/talktype/setup_wizard.py")
    sw.install_systemd_service({})
    assert exec_start(unit_text(home)) == (
        'ExecStart="/home/me/My Tools/bin/python3" "/home/me/My Code/talktype/talktype.py"'
    )


def test_talktype_command_with_a_space_is_quoted(home, systemctl, monkeypatch):
    monkeypatch.setattr(sw.shutil, "which", lambda cmd: "/home/me/my bin/talktype")
    sw.install_systemd_service({})
    assert exec_start(unit_text(home)) == 'ExecStart="/home/me/my bin/talktype"'


@pytest.mark.parametrize(
    "arg, quoted",
    [
        ("/usr/bin/talktype", "/usr/bin/talktype"),
        ("/a b/c", '"/a b/c"'),
        ('/a"b', '"/a\\"b"'),
        ("/a\\b", '"/a\\\\b"'),
        ("/100%/x", "/100%%/x"),
        ("/$HOME/x", "/$$HOME/x"),
        ("/it's", '"/it\'s"'),
    ],
)
def test_systemd_quote(arg, quoted):
    assert sw.systemd_quote(arg) == quoted


@pytest.mark.parametrize(
    "error",
    [subprocess.CalledProcessError(1, ["systemctl"]), FileNotFoundError("systemctl")],
)
def test_systemctl_failure_still_leaves_the_unit_written(
    home, systemctl, monkeypatch, error
):
    monkeypatch.setattr(sw.shutil, "which", lambda cmd: "/usr/bin/talktype")
    systemctl.error = error
    sw.install_systemd_service({})
    assert "WantedBy=graphical-session.target" in unit_text(home)
    assert systemctl.calls == SYSTEMCTL_CALLS[:1]
    assert "talktype.service" in sw.console.file.getvalue()
