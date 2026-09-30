"""The emacs route: streamed words go to Emacs through emacsclient and talktype.el.

subprocess.run is replaced by a recorder, so no real emacsclient, kitten or
xdotool command runs here; tests/test_emacs_e2e.py talks to a real, headless
Emacs server.
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

EMACSCLIENT = "/usr/bin/emacsclient"


@pytest.fixture
def recorded(monkeypatch):
    runs, pastes = [], []

    def run(cmd, **kw):
        runs.append(cmd)
        return SimpleNamespace(returncode=0, stdout=b"", stderr=b"")

    monkeypatch.setattr(t.subprocess, "run", run)
    monkeypatch.setattr(t, "paste_text", lambda text, **kw: pastes.append(text))
    return runs, pastes


def use(monkeypatch, output, emacs_socket=None):
    config = argparse.Namespace(
        stream_output=output,
        language="en",
        kitten="kitten",
        kitty_socket="unix:@kitty",
        stream_interval=0.01,
        emacsclient=EMACSCLIENT,
        emacs_socket=emacs_socket,
        minimal=True,
    )
    monkeypatch.setattr(t, "config", config, raising=False)


@pytest.mark.parametrize(
    "text, literal",
    [
        ('say "hi"', r'"say \"hi\""'),
        (r"C:\temp\ and \"", r'"C:\\temp\\ and \\\""'),
        ('") (kill-emacs) ("', r'"\") (kill-emacs) (\""'),
        ("(progn (delete-file x))", '"(progn (delete-file x))"'),
        ("eins\nzwei", r'"eins\nzwei"'),
        ("Grüße, Köln ß €", r'"Gr\u00fc\u00dfe, K\u00f6ln \u00df \u20ac"'),
        ("tab\there", r'"tab\u0009here"'),
        ("🎤", r'"\U0001f3a4"'),
        ("", '""'),
    ],
)
def test_lisp_string_escapes_the_transcript_as_data(text, literal):
    assert t.lisp_string(text) == literal
    assert t.lisp_string(text).isascii()


def test_emacs_route_appends_through_emacsclient(monkeypatch, recorded):
    runs, pastes = recorded
    use(monkeypatch, "emacs")
    t.stream_write(' "Grüße" (aus) Köln\\', "emacs")
    assert runs == [
        [
            EMACSCLIENT,
            "--eval",
            r'(talktype-append " \"Gr\u00fc\u00dfe\" (aus) K\u00f6ln\\")',
        ]
    ]
    assert pastes == []


def test_emacs_route_passes_the_socket(monkeypatch, recorded):
    runs, _ = recorded
    use(monkeypatch, "emacs", emacs_socket="/run/user/1000/emacs/server")
    t.stream_write(" hallo", "emacs")
    assert runs[0][:3] == [EMACSCLIENT, "-s", "/run/user/1000/emacs/server"]


def test_emacs_route_never_falls_back_to_keys_or_paste(monkeypatch, recorded):
    # In Emacs, keys and Ctrl+V are commands (evil normal state: C-v is visual block).
    runs, pastes = recorded
    use(monkeypatch, "emacs")
    monkeypatch.setattr(
        t.subprocess,
        "run",
        lambda cmd, **kw: runs.append(cmd) or SimpleNamespace(returncode=1),
    )
    t.stream_write(" hallo", "emacs")
    assert [cmd[0] for cmd in runs] == [EMACSCLIENT]
    assert pastes == []


def test_none_route_writes_nothing(monkeypatch, recorded):
    runs, pastes = recorded
    use(monkeypatch, "auto")
    t.stream_write(" hallo", "none")
    assert runs == [] and pastes == []


def emacs_client(pid=None, cmdline=("emacs", "-nw")):
    return {"pid": pid, "cmdline": list(cmdline)}


@pytest.mark.parametrize(
    "output, window, window_pid, kitty_procs, server, route",
    [
        # GUI Emacs frames: WM_CLASS "emacs", "Emacs".
        ("auto", "emacs", 100, [], 100, "emacs"),
        ("auto", "emacs", None, [], 100, "emacs"),
        ("auto", "emacs", 200, [], 100, "type-or-paste"),  # another Emacs
        ("auto", "emacs", 100, [], None, "type-or-paste"),  # no server
        # emacs -nw or emacsclient -nw in kitty.
        ("auto", "kitty", 1, [emacs_client(100)], 100, "emacs"),
        ("auto", "kitty", 1, [emacs_client(300, ["emacsclient", "-nw"])], 100, "emacs"),
        (
            "auto",
            "kitty",
            1,
            [emacs_client(300, ["/usr/bin/emacsclient", "-t"])],
            100,
            "emacs",
        ),
        # emacsclient -nw on another server's socket.
        (
            "auto",
            "kitty",
            1,
            [emacs_client(300, ["emacsclient", "-s", "work", "-nw"])],
            100,
            "kitty",
        ),
        (
            "auto",
            "kitty",
            1,
            [emacs_client(300, ["emacsclient", "-f", "~/.emacs.d/server/tcp", "-nw"])],
            100,
            "kitty",
        ),
        ("auto", "kitty", 1, [emacs_client(200)], 100, "kitty"),  # own Emacs
        ("auto", "kitty", 1, [emacs_client(200)], None, "kitty"),  # no server
        ("auto", "kitty", 1, [emacs_client(5, ["zsh"])], 100, "kitty"),
        ("auto", "firefox", 1, [], 100, "type-or-paste"),
        # Asked for emacs: whenever a server answers.
        ("emacs", "firefox", 1, [], 100, "emacs"),
        ("emacs", "emacs", 1, [], None, "none"),  # never keys into Emacs
        ("emacs", "firefox", 1, [], None, "none"),
        # The other modes do not look at Emacs.
        ("kitty", "kitty", 1, [emacs_client(100)], 100, "kitty"),
        ("type", "emacs", 100, [], 100, "type"),
        ("paste", "emacs", 100, [], 100, "paste"),
    ],
)
def test_choose_route_with_emacs(
    monkeypatch, recorded, output, window, window_pid, kitty_procs, server, route
):
    use(monkeypatch, output)
    monkeypatch.setattr(t, "window_is_emacs", lambda w: window == "emacs")
    monkeypatch.setattr(t, "window_is_kitty", lambda w: window == "kitty")
    monkeypatch.setattr(t, "kitty_reachable", lambda: True)
    monkeypatch.setattr(t, "window_pid", lambda w: window_pid)
    monkeypatch.setattr(t, "kitty_foreground_processes", lambda: kitty_procs)
    monkeypatch.setattr(t, "emacs_server_pid", lambda: server)
    assert t.choose_route() == route


@pytest.mark.parametrize(
    "ours, cmdline, route",
    [
        (None, ["emacsclient", "-nw"], "emacs"),
        (None, ["emacsclient", "-s", "server", "-nw"], "emacs"),
        (None, ["emacsclient", "-s", "work", "-nw"], "kitty"),
        ("work", ["emacsclient", "-nw"], "kitty"),
        ("work", ["emacsclient", "-s", "work", "-nw"], "emacs"),
        ("work", ["emacsclient", "-swork", "-nw"], "emacs"),
        ("work", ["emacsclient", "--socket-name=work", "-t"], "emacs"),
        ("work", ["emacsclient", "--socket-name", "/run/user/1000/emacs/work", "-t"], "emacs"),
        ("/run/user/1000/emacs/work", ["emacsclient", "-s", "work", "-nw"], "emacs"),
        ("work", ["emacsclient", "-s", "play", "-nw"], "kitty"),
    ],
)
def test_emacsclient_in_kitty_must_use_our_socket(
    monkeypatch, recorded, ours, cmdline, route
):
    use(monkeypatch, "auto", emacs_socket=ours)
    monkeypatch.setattr(t, "window_is_emacs", lambda w: False)
    monkeypatch.setattr(t, "window_is_kitty", lambda w: True)
    monkeypatch.setattr(t, "kitty_reachable", lambda: True)
    monkeypatch.setattr(
        t, "kitty_foreground_processes", lambda: [emacs_client(300, cmdline)]
    )
    monkeypatch.setattr(t, "emacs_server_pid", lambda: 100)
    assert t.choose_route() == route


def test_kitty_foreground_processes_of_the_focused_window(monkeypatch, recorded):
    use(monkeypatch, "auto")
    ls = b"""[{"is_focused": true, "tabs": [{"is_focused": true, "windows": [
        {"is_focused": false, "foreground_processes": [{"pid": 1, "cmdline": ["zsh"]}]},
        {"is_focused": true, "foreground_processes": [{"pid": 2, "cmdline": ["emacs", "-nw"]}]}
    ]}]}]"""
    monkeypatch.setattr(
        t.subprocess, "run", lambda cmd, **kw: SimpleNamespace(returncode=0, stdout=ls)
    )
    assert t.kitty_foreground_processes() == [{"pid": 2, "cmdline": ["emacs", "-nw"]}]


def test_emacs_server_pid_parses_emacsclient_output(monkeypatch, recorded):
    runs, _ = recorded
    use(monkeypatch, "auto")
    monkeypatch.setattr(
        t.subprocess,
        "run",
        lambda cmd, **kw: runs.append(cmd) or SimpleNamespace(returncode=0, stdout=b"4242\n"),
    )
    assert t.emacs_server_pid() == 4242
    assert runs == [[EMACSCLIENT, "--eval", "(emacs-pid)"]]


def test_emacs_server_pid_is_none_without_emacsclient(monkeypatch):
    use(monkeypatch, "auto")
    t.config.emacsclient = "/nonexistent/emacsclient"
    assert t.emacs_server_pid() is None


def evals(runs):
    return [cmd[-1] for cmd in runs if cmd[0] == EMACSCLIENT]


def test_session_opens_writes_and_closes_the_emacs_region(monkeypatch, recorded):
    runs, pastes = recorded
    use(monkeypatch, "emacs")
    monkeypatch.setattr(t, "choose_route", lambda: "emacs")
    monkeypatch.setattr(t, "audio_chunks", [])
    session = t.StreamingSession()
    session.write(" eins")
    session.write(" zwei")
    session.stop()
    session.end()
    assert evals(runs) == [
        "(talktype-begin)",
        '(talktype-append " eins")',
        '(talktype-append " zwei")',
        "(talktype-end)",
    ]
    assert pastes == []


def test_session_writes_nothing_when_emacs_refuses(monkeypatch, recorded):
    # talktype-begin signals a user-error in read-only buffers and the minibuffer.
    runs, pastes = recorded
    use(monkeypatch, "emacs")
    monkeypatch.setattr(t, "choose_route", lambda: "emacs")
    monkeypatch.setattr(t, "audio_chunks", [])
    monkeypatch.setattr(
        t.subprocess,
        "run",
        lambda cmd, **kw: runs.append(cmd) or SimpleNamespace(returncode=1),
    )
    session = t.StreamingSession()
    session.write(" eins")
    session.stop()
    session.end()
    assert evals(runs) == ["(talktype-begin)"]
    assert pastes == []


def test_nemotron_session_closes_the_emacs_region(monkeypatch, recorded):
    runs, _ = recorded
    use(monkeypatch, "emacs")
    monkeypatch.setattr(t, "choose_route", lambda: "emacs")
    monkeypatch.setattr(t, "audio_chunks", [])
    monkeypatch.setattr(t, "nemotron_engine", object(), raising=False)
    monkeypatch.setattr(
        t.nemotron,
        "Stream",
        lambda engine, language: type(
            "S", (), {"feed": lambda self, a: "", "flush": lambda self: "hallo"}
        )(),
    )
    session = t.NemotronSession()
    session.finish()
    session.end()
    assert evals(runs) == [
        "(talktype-begin)",
        '(talktype-append " hallo")',
        "(talktype-end)",
    ]


def test_session_without_words_leaves_emacs_alone(monkeypatch, recorded):
    runs, _ = recorded
    use(monkeypatch, "emacs")
    monkeypatch.setattr(t, "audio_chunks", [])
    session = t.StreamingSession()
    session.stop()
    session.end()
    assert runs == []


def failing_after(runs, successes):
    """subprocess.run that succeeds for the first `successes` calls, then fails."""

    def run(cmd, **kw):
        runs.append(cmd)
        return SimpleNamespace(returncode=0 if len(runs) <= successes else 1)

    return run


def test_session_stops_writing_when_emacs_fails_mid_dictation(monkeypatch, recorded):
    runs, pastes = recorded
    use(monkeypatch, "emacs")
    monkeypatch.setattr(t, "choose_route", lambda: "emacs")
    monkeypatch.setattr(t, "audio_chunks", [])
    monkeypatch.setattr(t.time, "sleep", lambda s: None)
    monkeypatch.setattr(t.subprocess, "run", failing_after(runs, 2))
    session = t.StreamingSession()
    session.write(" eins")
    session.write(" zwei")  # fails
    session.write(" drei")  # not sent: it would leave a gap
    session.stop()
    session.end()
    assert evals(runs) == [
        "(talktype-begin)",
        '(talktype-append " eins")',
        '(talktype-append " zwei")',
        "(talktype-end)",
        "(talktype-end)",
        "(talktype-end)",
    ]
    assert pastes == []


def test_session_retries_closing_the_region(monkeypatch, recorded):
    runs, _ = recorded
    use(monkeypatch, "emacs")
    monkeypatch.setattr(t, "choose_route", lambda: "emacs")
    monkeypatch.setattr(t, "audio_chunks", [])
    monkeypatch.setattr(t.time, "sleep", lambda s: None)
    calls = []

    def run(cmd, **kw):
        runs.append(cmd)
        calls.append(cmd[-1])
        # The first talktype-end fails, the second succeeds.
        fail = cmd[-1] == "(talktype-end)" and calls.count("(talktype-end)") == 1
        return SimpleNamespace(returncode=1 if fail else 0)

    monkeypatch.setattr(t.subprocess, "run", run)
    session = t.StreamingSession()
    session.write(" eins")
    session.stop()
    session.end()
    session.end()  # already closed: nothing more
    assert evals(runs) == [
        "(talktype-begin)",
        '(talktype-append " eins")',
        "(talktype-end)",
        "(talktype-end)",
    ]
