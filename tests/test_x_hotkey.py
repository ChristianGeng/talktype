"""X key names as hotkeys: matching, `--which-key` and the real X listener."""

import os
import sys
import threading
import time

import pytest

if not os.environ.get("DISPLAY"):
    pytest.skip(
        "talktype imports pynput, which needs an X display", allow_module_level=True
    )

import talktype as t  # noqa: E402
from pynput import keyboard  # noqa: E402

XF86_TOOLS = 0x1008FF81


@pytest.fixture
def recorder(monkeypatch):
    """The record key's handlers with recording and transcription stubbed out."""
    events = []
    monkeypatch.setattr(t, "state", t.State.IDLE)
    monkeypatch.setattr(t, "session", None)
    monkeypatch.setattr(t, "start_recording", lambda: events.append("start"))
    monkeypatch.setattr(t, "stop_recording", lambda: events.append("stop"))
    monkeypatch.setattr(t, "transcribe_and_paste", lambda audio, live: None)
    hotkey = t.get_hotkey("XF86Tools")
    on_press, on_release = t.create_hotkey_handler(hotkey, t.RecordKey("toggle"))

    def press(key):
        monkeypatch.setattr(t, "_last_hotkey_time", 0.0)  # no debounce
        on_press(key)
        on_release(key)
        if t.state == t.State.TRANSCRIBING:
            t.state = t.State.IDLE

    return press, events


def test_handler_starts_and_stops_on_the_x_key(recorder):
    press, events = recorder
    press(keyboard.KeyCode.from_vk(XF86_TOOLS))
    press(keyboard.KeyCode.from_vk(XF86_TOOLS))
    assert events == ["start", "stop"]


def test_handler_ignores_other_keys(recorder):
    press, events = recorder
    for key in (
        keyboard.Key.f10,
        keyboard.KeyCode.from_vk(0x1008FF19),  # XF86Mail
        keyboard.KeyCode.from_char("a", vk=0x61),
        None,
    ):
        press(key)
    assert events == []


def test_printable_x_names_match_the_listener_key():
    # the listener reports printable keys with their character as well
    assert t.get_hotkey("a") == keyboard.KeyCode.from_char("a", vk=0x61)
    assert t.get_hotkey("semicolon") == keyboard.KeyCode.from_char(";", vk=0x3B)


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


@pytest.mark.parametrize(
    "key, name",
    [
        (keyboard.KeyCode.from_vk(XF86_TOOLS), "XF86Tools"),
        (keyboard.Key.f10, "f10"),
        (keyboard.Key.media_play_pause, "media_play_pause"),
    ],
)
def test_which_key_prints_a_name_get_hotkey_accepts(monkeypatch, capsys, key, name):
    monkeypatch.setattr(FakeListener, "keys", [None, key])  # None: unknown keycode
    monkeypatch.setattr(t.keyboard, "Listener", FakeListener)
    assert t.run_which_key() == 0
    assert capsys.readouterr().out == name + "\n"
    assert t.get_hotkey(name) == key


def test_which_key_rejects_keys_without_a_name(monkeypatch, capsys):
    monkeypatch.setattr(FakeListener, "keys", [keyboard.KeyCode.from_char("1")])
    monkeypatch.setattr(t.keyboard, "Listener", FakeListener)
    assert t.run_which_key() == 1
    assert capsys.readouterr().out == ""


def test_which_key_runs_before_anything_else(monkeypatch, capsys):
    monkeypatch.setattr(FakeListener, "keys", [keyboard.KeyCode.from_vk(XF86_TOOLS)])
    monkeypatch.setattr(t.keyboard, "Listener", FakeListener)
    monkeypatch.setattr(t, "load_config_file", lambda: {})
    monkeypatch.setattr(sys, "argv", ["talktype", "--which-key"])

    def must_not_run():
        raise AssertionError("--which-key went past the key prompt")

    monkeypatch.setattr(t, "acquire_instance_lock", must_not_run)
    with pytest.raises(SystemExit) as stopped:
        t.main()
    assert stopped.value.code == 0
    assert capsys.readouterr().out == "XF86Tools\n"


def test_which_key_with_a_bad_option_stops_without_listening(monkeypatch):
    def must_not_listen(*args, **kwargs):
        raise AssertionError("listened for a key despite the bad option")

    monkeypatch.setattr(t.keyboard, "Listener", must_not_listen)
    monkeypatch.setattr(t, "load_config_file", lambda: {})
    monkeypatch.setattr(sys, "argv", ["talktype", "--which-key", "--unknown"])
    with pytest.raises(SystemExit) as stopped:
        t.main()
    assert stopped.value.code == 2


def test_which_key_ignores_a_bad_record_key_in_the_config(monkeypatch, capsys):
    monkeypatch.setattr(FakeListener, "keys", [keyboard.Key.f10])
    monkeypatch.setattr(t.keyboard, "Listener", FakeListener)
    monkeypatch.setattr(t, "load_config_file", lambda: {"hotkeys": {"record": "none"}})
    monkeypatch.setattr(sys, "argv", ["talktype", "--which-key"])
    with pytest.raises(SystemExit) as stopped:
        t.main()
    assert stopped.value.code == 0
    assert capsys.readouterr().out == "f10\n"


def test_x_listener_reports_the_keysym_as_vk():
    """A real XF86Tools press through X reaches the handler as get_hotkey's key."""
    from Xlib import X, display
    from Xlib.ext import xtest

    d = display.Display()
    keycode = d.display.info.max_keycode  # usually unused; borrowed for the test
    saved = d.get_keyboard_mapping(keycode, 1)
    d.change_keyboard_mapping(keycode, [(XF86_TOOLS,)])
    d.sync()

    pressed, released = threading.Event(), threading.Event()
    got = []

    def on_press(key):
        got.append(key)
        pressed.set()

    def on_release(key):
        released.set()

    listener = keyboard.Listener(on_press=on_press, on_release=on_release)
    listener.start()
    try:
        # pynput's wait() returns just before the listener enables its XRecord
        # context, so a key sent at once can go unrecorded: resend until seen.
        listener.wait()
        deadline = time.monotonic() + 5
        while not pressed.is_set() and time.monotonic() < deadline:
            xtest.fake_input(d, X.KeyPress, keycode)
            xtest.fake_input(d, X.KeyRelease, keycode)
            d.sync()
            pressed.wait(0.1)
        assert pressed.is_set() and released.wait(5)
    finally:
        listener.stop()
        d.change_keyboard_mapping(keycode, saved)
        d.sync()
        d.close()
    assert got[0] == t.get_hotkey("XF86Tools")
    assert t.hotkey_name(got[0]) == "XF86Tools"
