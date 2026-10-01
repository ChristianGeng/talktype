"""The setup wizard names the pressed record key as get_hotkey accepts it."""

import io
import os
import sys
import termios
import tty

import pytest

if not os.environ.get("DISPLAY"):
    pytest.skip(
        "talktype imports pynput, which needs an X display", allow_module_level=True
    )

import setup_wizard as sw  # noqa: E402
import talktype as t  # noqa: E402
import yaml  # noqa: E402
from pynput import keyboard  # noqa: E402
from rich.console import Console  # noqa: E402

XF86_TOOLS = 0x1008FF81


class FakeListener:
    """Stands in for keyboard.Listener: delivers the given presses on join()."""

    keys = []

    def __init__(self, on_press=None, **kwargs):
        self.on_press = on_press

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def join(self):
        for key in self.keys:
            if self.on_press(key) is False:
                return


class FakeStdin:
    def fileno(self):
        return 0


@pytest.fixture
def press(monkeypatch):
    """Make the wizard's key capture see the given key, without a terminal."""
    monkeypatch.setattr(sw.keyboard, "Listener", FakeListener)
    monkeypatch.setattr(sys, "stdin", FakeStdin())
    monkeypatch.setattr(termios, "tcgetattr", lambda fd: None)
    monkeypatch.setattr(termios, "tcsetattr", lambda fd, when, attrs: None)
    monkeypatch.setattr(tty, "setraw", lambda fd: None)
    out = io.StringIO()
    monkeypatch.setattr(sw, "console", Console(file=out, width=80))

    def press(key):
        monkeypatch.setattr(FakeListener, "keys", [key])
        return out

    return press


@pytest.mark.parametrize(
    "key, name",
    [
        (keyboard.KeyCode.from_vk(XF86_TOOLS), "XF86Tools"),
        (keyboard.Key.f10, "f10"),
        (keyboard.Key.pause, "pause"),
        (keyboard.KeyCode.from_char("a", vk=0x61), "a"),
        (keyboard.KeyCode.from_char("A", vk=0x41), "a"),
    ],
)
def test_wizard_names_the_key_as_get_hotkey_accepts_it(press, key, name):
    press(key)
    assert sw.capture_hotkey("Press your RECORD hotkey:", "f9") == name
    assert t.get_hotkey(name) is not None


def test_wizard_saves_an_x_key_that_get_hotkey_turns_back_into_it(press):
    key = keyboard.KeyCode.from_vk(XF86_TOOLS)
    press(key)
    assert t.get_hotkey(sw.capture_hotkey("Press your RECORD hotkey:", "f9")) == key


@pytest.mark.parametrize("key", [keyboard.Key.enter, keyboard.Key.esc])
def test_enter_and_esc_confirm_the_default(press, key):
    press(key)
    assert sw.capture_hotkey("Press your RECORD hotkey:", "f9") == "f9"


def test_keys_without_a_name_give_the_default(press):
    press(keyboard.KeyCode())
    assert sw.capture_hotkey("Press your RECORD hotkey:", "f9") == "f9"


def test_set_to_line_uses_the_ready_message_label(press):
    out = press(keyboard.KeyCode.from_vk(XF86_TOOLS))
    sw.capture_hotkey("Press your RECORD hotkey:", "f9")
    assert "Set to XF86Tools" in out.getvalue()
    assert "XF86TOOLS" not in out.getvalue()


def test_summary_and_config_use_the_x_key_name(press, monkeypatch, tmp_path):
    out = press(keyboard.KeyCode.from_vk(XF86_TOOLS))
    monkeypatch.setattr(sw, "CONFIG_PATH", tmp_path / "config.yaml")
    monkeypatch.setattr(sw, "select_option", lambda title, options, cursor_index=0: 0)
    monkeypatch.setattr(sw.shutil, "which", lambda cmd: "/usr/bin/talktype")
    monkeypatch.setattr(sw.time, "sleep", lambda s: None)

    config, run_now = sw.run_wizard()

    assert run_now
    saved = yaml.safe_load((tmp_path / "config.yaml").read_text())
    assert saved["hotkeys"]["record"] == config["hotkeys"]["record"] == "XF86Tools"
    assert t.get_hotkey(saved["hotkeys"]["record"]) == keyboard.KeyCode.from_vk(XF86_TOOLS)
    assert "Record:   XF86Tools" in out.getvalue()
    assert "XF86TOOLS" not in out.getvalue()


def test_hotkey_name_is_still_exported_by_talktype():
    assert t.hotkey_name(keyboard.KeyCode.from_vk(XF86_TOOLS)) == "XF86Tools"
    assert t.hotkey_label("XF86Tools") == "XF86Tools"
    assert t.hotkey_label("f10") == "F10"
