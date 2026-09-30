"""How streamed words reach the window: kitty remote control, keystrokes, or paste.

subprocess.run is replaced by a recorder in every test, so no real kitten or
xdotool command runs and nothing is typed on the desktop running the tests.
"""

import argparse
import os
from types import SimpleNamespace

import pytest

if not os.environ.get("DISPLAY"):
    pytest.skip(
        "talktype imports pynput, which needs an X display", allow_module_level=True
    )

import talktype as t  # noqa: E402

KITTEN = "/opt/kitty/bin/kitten"
SOCKET = "unix:@kitty"


@pytest.fixture
def recorded(monkeypatch):
    runs, pastes, clipboard_reads = [], [], []

    def run(cmd, **kw):
        runs.append(cmd)
        return SimpleNamespace(returncode=0, stdout=b"", stderr=b"")

    monkeypatch.setattr(t.subprocess, "run", run)
    monkeypatch.setattr(t, "paste_text", lambda text, **kw: pastes.append(text))
    monkeypatch.setattr(t.pyperclip, "paste", lambda: clipboard_reads.append(1) or "")
    return runs, pastes, clipboard_reads


def use(monkeypatch, output):
    config = argparse.Namespace(
        stream_output=output, language="en", kitten=KITTEN, kitty_socket=SOCKET,
        stream_interval=0.01,
    )
    monkeypatch.setattr(t, "config", config, raising=False)


def test_kitty_route_sends_text_to_the_focused_kitty_window(monkeypatch, recorded):
    runs, pastes, _ = recorded
    use(monkeypatch, "auto")
    t.stream_write(" Grüße aus Köln", "kitty")
    assert runs == [
        [
            KITTEN,
            "@",
            "--to",
            SOCKET,
            "send-text",
            "--match",
            "state:focused",
            "--",
            " Grüße aus Köln",
        ]
    ]
    assert pastes == []


def test_kitty_route_falls_back_to_paste_when_kitty_does_not_answer(
    monkeypatch, recorded
):
    runs, pastes, _ = recorded
    use(monkeypatch, "auto")
    monkeypatch.setattr(
        t.subprocess,
        "run",
        lambda cmd, **kw: runs.append(cmd) or SimpleNamespace(returncode=1),
    )
    t.stream_write(" hallo", "kitty")
    assert pastes == [" hallo"]


def test_type_route_types_keystrokes(monkeypatch, recorded):
    runs, pastes, _ = recorded
    use(monkeypatch, "type")
    t.stream_write(" hello world", "type")
    assert runs == [
        ["xdotool", "type", "--clearmodifiers", "--delay", "4", "--", " hello world"]
    ]
    assert pastes == []


def test_auto_route_types_ascii_but_pastes_umlauts(monkeypatch, recorded):
    # xdotool loses characters that are not on the keyboard (ü, ß, €) in kitty.
    runs, pastes, _ = recorded
    use(monkeypatch, "auto")
    t.stream_write(" hello", "type-or-paste")
    t.stream_write(" Grüße", "type-or-paste")
    assert runs == [
        ["xdotool", "type", "--clearmodifiers", "--delay", "4", "--", " hello"]
    ]
    assert pastes == [" Grüße"]


def test_paste_route_pastes(monkeypatch, recorded):
    runs, pastes, _ = recorded
    use(monkeypatch, "paste")
    t.stream_write(" hello", "paste")
    assert pastes == [" hello"]
    assert runs == []


@pytest.mark.parametrize(
    "output, window, reachable, route",
    [
        ("auto", "kitty", True, "kitty"),
        ("auto", "kitty", False, "type-or-paste"),
        ("auto", "firefox", True, "type-or-paste"),
        ("kitty", "kitty", True, "kitty"),
        ("kitty", "firefox", True, "paste"),
        ("type", "kitty", True, "type"),
        ("paste", "kitty", True, "paste"),
    ],
)
def test_choose_route(monkeypatch, recorded, output, window, reachable, route):
    use(monkeypatch, output)
    monkeypatch.setattr(t, "window_is_kitty", lambda w: window == "kitty")
    monkeypatch.setattr(t, "kitty_reachable", lambda: reachable)
    assert t.choose_route() == route


def test_streaming_does_not_touch_the_clipboard_outside_paste_mode(
    monkeypatch, recorded
):
    _, _, clipboard_reads = recorded
    use(monkeypatch, "auto")
    monkeypatch.setattr(t, "audio_chunks", [])
    session = t.StreamingSession()
    session.stop()
    session.restore_clipboard()
    assert clipboard_reads == []


def test_kitty_socket_placeholder_takes_the_focused_windows_pid(monkeypatch, recorded):
    # kitty.conf: listen_on unix:${XDG_RUNTIME_DIR}/kitty-{kitty_pid}.sock
    runs, _, _ = recorded
    use(monkeypatch, "auto")
    t.config.kitty_socket = "unix:/run/user/1001/kitty-{kitty_pid}.sock"
    monkeypatch.setattr(t, "window_pid", lambda w: 4242)
    t.stream_write(" hallo", "kitty")
    assert runs[0][3] == "unix:/run/user/1001/kitty-4242.sock"
