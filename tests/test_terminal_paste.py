"""The terminal-paste route: streamed chunks pasted into terminals other than kitty.

subprocess.run and the clipboard are fakes that log every call, so nothing
is typed or pasted on the desktop running the tests;
tests/test_terminal_paste_e2e.py pastes into a real VTE terminal.
"""

import argparse
import os
import time
from types import SimpleNamespace
from typing import ClassVar

import numpy as np
import pytest

if not os.environ.get("DISPLAY"):
    pytest.skip(
        "talktype imports pynput, which needs an X display", allow_module_level=True
    )

import replacements  # noqa: E402
import talktype as t  # noqa: E402

CTRL_SHIFT_V = ["xdotool", "key", "--clearmodifiers", "--delay", "50", "ctrl+shift+v"]
BEFORE = "from before the recording"


def wait_for(condition):
    deadline = time.monotonic() + 5
    while not condition():
        assert time.monotonic() < deadline, "timed out"
        time.sleep(0.01)


@pytest.fixture
def events(monkeypatch):
    """Clipboard reads and writes and commands run, in order."""
    log = []
    clipboard = [BEFORE]

    def run(cmd, **kw):
        log.append(("run", cmd))
        return SimpleNamespace(returncode=0, stdout=b"", stderr=b"")

    def copy(text):
        log.append(("copy", text))
        clipboard[0] = text

    def paste():
        log.append(("save",))
        return clipboard[0]

    monkeypatch.setattr(t.subprocess, "run", run)
    monkeypatch.setattr(t.pyperclip, "copy", copy)
    monkeypatch.setattr(t.pyperclip, "paste", paste)
    monkeypatch.setattr(t, "paste_text", lambda text, **kw: log.append(("paste_text", text)))
    return log


@pytest.fixture
def terminal(monkeypatch, events):
    """auto mode, a focused GNOME Terminal, no Emacs."""
    config = argparse.Namespace(
        language="en",
        stream_output="auto",
        stream_interval=0.01,
        final_engine="whisper",
        api=None,
        hotkey="f9",
        record_mode="toggle",
        kitten="kitten",
        kitty_socket="unix:@kitty",
    )
    monkeypatch.setattr(t, "config", config, raising=False)
    monkeypatch.setattr(t, "SYSTEM", "Linux")
    monkeypatch.setattr(t, "target_window", b"0x1")
    monkeypatch.setattr(t, "emacs_targeted", lambda: False)
    monkeypatch.setattr(t, "window_is_kitty", lambda w: False)
    monkeypatch.setattr(t, "is_terminal_window", lambda w: True)
    monkeypatch.setattr(t, "window_class_has", lambda w, names: False)
    monkeypatch.setattr(t, "replacer", replacements.Replacer({}))
    monkeypatch.setattr(t, "audio_chunks", [])
    monkeypatch.setattr(t, "history", None)
    for name in ("show_status", "set_terminal_title", "beep_success", "beep_error"):
        monkeypatch.setattr(t, name, lambda *a, **k: None)
    monkeypatch.setattr(t.time, "sleep", lambda s: None)
    return events


@pytest.mark.parametrize(
    "output, window, reachable, route",
    [
        ("auto", "kitty", True, "kitty"),
        ("auto", "kitty", False, "type-or-paste"),  # paste stalls kitty
        ("auto", "gnome-terminal", True, "terminal-paste"),
        ("auto", "xterm", True, "type-or-paste"),  # no Ctrl+Shift+V paste
        ("auto", "firefox", True, "type-or-paste"),
        ("auto", None, True, "type-or-paste"),
        ("kitty", "gnome-terminal", True, "paste"),
        ("type", "gnome-terminal", True, "type"),
        ("paste", "gnome-terminal", True, "paste"),
    ],
)
def test_choose_route(terminal, monkeypatch, output, window, reachable, route):
    t.config.stream_output = output
    monkeypatch.setattr(t, "target_window", window and window.encode())
    monkeypatch.setattr(t, "window_is_kitty", lambda w: w == b"kitty")
    monkeypatch.setattr(
        t, "is_terminal_window", lambda w: w in (b"kitty", b"gnome-terminal", b"xterm")
    )
    monkeypatch.setattr(t, "window_class_has", lambda w, names: w.decode() in names)
    monkeypatch.setattr(t, "kitty_reachable", lambda: reachable)
    assert t.choose_route() == route


def test_emacs_mode_keeps_its_route(terminal, monkeypatch):
    t.config.stream_output = "emacs"
    monkeypatch.setattr(t, "emacs_server_pid", lambda: 42)
    assert t.choose_route() == "emacs"


def test_auto_picks_emacs_before_terminal_paste(terminal, monkeypatch):
    monkeypatch.setattr(t, "emacs_targeted", lambda: True)
    assert t.choose_route() == "emacs"


@pytest.mark.parametrize("system", ["Windows", "Darwin"])
def test_terminal_paste_is_linux_only(terminal, monkeypatch, system):
    monkeypatch.setattr(t, "SYSTEM", system)
    assert t.choose_route() == "type-or-paste"


def test_terminal_paste_pastes_the_chunk_as_it_is(terminal):
    t.stream_write(" Grüße aus Köln", "terminal-paste")
    assert terminal == [("copy", " Grüße aus Köln"), ("run", CTRL_SHIFT_V)]


def check_one_save_one_paste_per_chunk_one_restore(events, text):
    wait_for(lambda: events[-1] == ("copy", BEFORE))
    assert events[0] == ("save",)
    assert events.count(("save",)) == 1
    pastes = events[1:-1]
    assert len(pastes) >= 4  # several chunks while "speaking"
    assert pastes == [
        e for chunk in pastes[::2] for e in (chunk, ("run", CTRL_SHIFT_V))
    ]
    chunks = [text for _, text in pastes[::2]]
    assert "".join(chunks) == text
    assert not any("\n" in c or "\r" in c for c in chunks)
    assert not any(e[0] == "run" and e[1][1] == "type" for e in events)
    assert not any(e[0] == "paste_text" for e in events)


class ChunkStream:
    """Fake nemotron.Stream: one chunk of text per audio chunk fed."""

    chunks: ClassVar[list[str]] = []
    fed = 0

    def __init__(self, engine, language):
        ChunkStream.fed = 0

    def feed(self, audio):
        ChunkStream.fed += 1
        return ChunkStream.chunks.pop(0) if ChunkStream.chunks else ""

    def flush(self):
        return ""


def add_audio(seconds=0.1):
    t.audio_chunks.append(np.full((int(t.SAMPLE_RATE * seconds), 1), 0.1, np.float32))


def test_nemotron_session_saves_once_pastes_each_chunk_restores_once(terminal, monkeypatch):
    chunks = [" Grüße", " aus Köln,", " wie geht's", " dir heute?"]
    ChunkStream.chunks = list(chunks)
    monkeypatch.setattr(t, "nemotron_engine", object(), raising=False)
    monkeypatch.setattr(t.nemotron, "Stream", ChunkStream)
    session = t.NemotronSession()
    for n in range(1, len(chunks) + 1):
        add_audio()
        wait_for(lambda n=n: ChunkStream.fed >= n)
        wait_for(lambda n=n: terminal.count(("run", CTRL_SHIFT_V)) >= n)
    t.transcribe_and_paste(np.zeros(0, np.float32), session)
    assert session.route == "terminal-paste"
    check_one_save_one_paste_per_chunk_one_restore(terminal, "".join(chunks))


def test_streaming_session_saves_once_pastes_each_chunk_restores_once(terminal, monkeypatch):
    words = ["ich", "diktiere", "Grüße", "aus", "Köln", "in", "das", "Terminal"]
    passes = [words[:n] for n in range(2, len(words) + 1)]
    monkeypatch.setattr(
        t, "transcribe_partial", lambda audio: (passes.pop(0) if len(passes) > 1 else passes[0], None)
    )
    monkeypatch.setattr(t, "transcribe", lambda audio, tail_from=0: " ".join(words))
    add_audio(seconds=1.5)
    session = t.StreamingSession()
    wait_for(lambda: len(session.typed) == len(words) - 1)  # all but the last word
    t.transcribe_and_paste(np.zeros(0, np.float32), session)
    assert session.route == "terminal-paste"
    check_one_save_one_paste_per_chunk_one_restore(terminal, " " + " ".join(words))


def test_sessions_outside_the_paste_routes_leave_the_clipboard_alone(terminal, monkeypatch):
    monkeypatch.setattr(t, "is_terminal_window", lambda w: False)
    ChunkStream.chunks = [" hello", " world"]
    monkeypatch.setattr(t, "nemotron_engine", object(), raising=False)
    monkeypatch.setattr(t.nemotron, "Stream", ChunkStream)
    session = t.NemotronSession()
    add_audio()
    wait_for(lambda: ChunkStream.fed >= 1)
    t.transcribe_and_paste(np.zeros(0, np.float32), session)
    assert session.route == "type-or-paste"
    assert not any(e[0] in ("save", "copy") for e in terminal)


def stream_chunks(monkeypatch, chunks, written):
    """A NemotronSession that has decoded and written each chunk in turn."""
    ChunkStream.chunks = list(chunks)
    monkeypatch.setattr(t, "nemotron_engine", object(), raising=False)
    monkeypatch.setattr(t.nemotron, "Stream", ChunkStream)
    session = t.NemotronSession()
    for n in range(1, len(chunks) + 1):
        add_audio()
        wait_for(lambda n=n: ChunkStream.fed >= n)
        wait_for(lambda n=n: written() >= n)
    return session


def typed(events):
    return [e[1][-1] for e in events if e[0] == "run" and e[1][1] == "type"]


def test_without_a_clipboard_the_recording_types_instead(terminal, monkeypatch, capsys):
    def no_clipboard(text):
        terminal.append(("copy failed", text))
        raise t.pyperclip.PyperclipException("no copy/paste mechanism")

    monkeypatch.setattr(t.pyperclip, "copy", no_clipboard)
    chunks = [" Grüße", " aus Köln,", " wie geht's"]
    session = stream_chunks(monkeypatch, chunks, lambda: len(typed(terminal)))
    t.transcribe_and_paste(np.zeros(0, np.float32), session)
    assert session.route == "type"
    assert typed(terminal) == chunks  # the failed chunk too, then the rest
    assert ("run", CTRL_SHIFT_V) not in terminal
    assert [e for e in terminal if e[0] == "copy failed"][0] == ("copy failed", chunks[0])
    out = capsys.readouterr().out
    assert out.count("[stream] clipboard unavailable; typing instead") == 1
