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
        stream_output=output, language="en", kitten=KITTEN, kitty_socket=SOCKET, stream_interval=0.01
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


def test_kitty_route_pinned_to_a_window_sends_there(monkeypatch, recorded):
    runs, pastes, _ = recorded
    use(monkeypatch, "auto")
    t.stream_write(" hallo", "kitty", (b"4711", "unix:@other", 7))
    assert runs == [
        [KITTEN, "@", "--to", "unix:@other", "send-text", "--match", "id:7", "--", " hallo"]
    ]
    assert pastes == []


def test_kitty_route_without_a_window_id_pastes(monkeypatch, recorded, capsys):
    # state:focused would send later chunks to whatever tab has the focus then.
    runs, pastes, _ = recorded
    use(monkeypatch, "auto")
    t.stream_write(" hallo", "kitty", (b"4711", SOCKET, None))
    assert not any("send-text" in cmd for cmd in runs)
    assert pastes == [" hallo"]
    assert "[stream] kitty window unknown; pasting instead" in capsys.readouterr().out


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


def test_kitty_fallback_says_why(monkeypatch, recorded, capsys):
    use(monkeypatch, "auto")

    def timeout(cmd, **kw):
        raise t.subprocess.TimeoutExpired(cmd, 2)

    monkeypatch.setattr(t.subprocess, "run", timeout)
    t.stream_write(" hallo", "kitty")
    assert "[stream] kitty send-text timed out after 2 s; pasting instead" in capsys.readouterr().out


def test_a_slow_write_is_logged_with_its_route(monkeypatch, recorded, capsys):
    use(monkeypatch, "auto")
    # route choice 0.0-0.01, first write 0.01-0.81, second write 1.0-1.1
    clock = iter([0.0, 0.01, 0.01, 0.81, 1.0, 1.1])
    monkeypatch.setattr(t.time, "monotonic", lambda: next(clock))
    monkeypatch.setattr(t, "choose_route", lambda: "kitty")
    session = SimpleNamespace(route=None, emacs_open=False)
    t.StreamingSession.write(session, " slow")  # 0.8 s
    t.StreamingSession.write(session, " fast")  # 0.1 s
    out = capsys.readouterr().out
    assert "[stream] route kitty, chosen in" in out
    assert "[stream] slow write: 0.80 s for 5 chars by kitty" in out
    assert out.count("slow write") == 1


def test_the_logged_route_says_when_emacs_refused(monkeypatch, recorded, capsys):
    use(monkeypatch, "auto")
    monkeypatch.setattr(t, "choose_route", lambda: "emacs")
    monkeypatch.setattr(t, "emacs_call", lambda *a: False)
    session = SimpleNamespace(route=None, emacs_open=False)
    t.StreamingSession.write(session, " text")
    assert "[stream] route none (Emacs refused talktype-begin)" in capsys.readouterr().out
    assert session.route == "none"


@pytest.fixture
def beeps(monkeypatch):
    played = []
    monkeypatch.setattr(t, "beep", lambda *a, **k: played.append(a) or True)
    return played


def fake_emacs(monkeypatch, takes):
    """emacs_call answering talktype-begin and each talktype-append from takes."""
    answers, calls = iter(takes), []

    def emacs_call(function, *args):
        calls.append((function, *args))
        return next(answers)

    monkeypatch.setattr(t, "emacs_call", emacs_call)
    monkeypatch.setattr(t, "show_status", lambda *a: None)
    return calls


def test_a_refused_begin_beeps_the_error_once_and_writes_nothing(
    monkeypatch, recorded, beeps, capsys
):
    runs, pastes, _ = recorded
    use(monkeypatch, "auto")
    monkeypatch.setattr(t, "choose_route", lambda: "emacs")
    calls = fake_emacs(monkeypatch, [False])
    session = SimpleNamespace(route=None, emacs_open=False)
    for chunk in (" eins", " zwei", " drei"):
        t.StreamingSession.write(session, chunk)
    assert calls == [("talktype-begin",)]
    assert runs == [] and pastes == []
    assert capsys.readouterr().out.count("[stream] beep error") == 1
    assert len(beeps) == 1


def test_emacs_stopping_midway_beeps_the_error_once(
    monkeypatch, recorded, beeps, capsys
):
    runs, pastes, _ = recorded
    use(monkeypatch, "auto")
    monkeypatch.setattr(t, "choose_route", lambda: "emacs")
    calls = fake_emacs(monkeypatch, [True, True, False])
    session = SimpleNamespace(route=None, emacs_open=False)
    for chunk in (" eins", " zwei", " drei", " vier"):
        t.StreamingSession.write(session, chunk)
    assert calls == [
        ("talktype-begin",),
        ("talktype-append", " eins"),
        ("talktype-append", " zwei"),
    ]
    assert session.route == "none"
    assert runs == [] and pastes == []
    assert capsys.readouterr().out.count("[stream] beep error") == 1
    assert len(beeps) == 1


def test_emacs_taking_every_word_plays_no_error_beep(monkeypatch, recorded, beeps):
    use(monkeypatch, "auto")
    monkeypatch.setattr(t, "choose_route", lambda: "emacs")
    fake_emacs(monkeypatch, [True, True, True])
    session = SimpleNamespace(route=None, emacs_open=False)
    for chunk in (" eins", " zwei"):
        t.StreamingSession.write(session, chunk)
    assert session.route == "emacs"
    assert beeps == []


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


def test_nemotron_session_does_not_touch_the_clipboard_outside_paste_mode(
    monkeypatch, recorded
):
    _, _, clipboard_reads = recorded
    use(monkeypatch, "auto")
    monkeypatch.setattr(t, "audio_chunks", [])
    monkeypatch.setattr(t, "nemotron_engine", object(), raising=False)
    monkeypatch.setattr(
        t.nemotron,
        "Stream",
        lambda engine, language: type(
            "S", (), {"feed": lambda self, a: "", "flush": lambda self: ""}
        )(),
    )
    session = t.NemotronSession()
    session.finish()
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
