"""The unsettled tail of a re-transcribing stream reaches Emacs and only Emacs.

Scripted passes stand in for Whisper and Parakeet, and the routes are
recorded instead of written, so nothing reaches the desktop running the
tests. A pass runs only when the test hands it its words, so each write is
checked between passes, without sleeping.
"""

import argparse
import os
import queue
import sys
import time

import numpy as np
import pytest

if not os.environ.get("DISPLAY"):
    pytest.skip(
        "talktype imports pynput, which needs an X display", allow_module_level=True
    )

import replacements  # noqa: E402
import talktype as t  # noqa: E402


class Passes:
    """transcribe_partial that returns the words the test gives it, one pass each."""

    def __init__(self):
        self._words = queue.Queue()
        self.asked = 0
        self.given = 0

    def __call__(self, audio):
        self.asked += 1
        words = self._words.get(timeout=5)
        if words is None:
            raise RuntimeError("stopped")  # the session skips a failed pass
        return words.split(), None

    def run(self, words):
        """Run one pass with these words; return once it has been written."""
        self.given += 1
        self._words.put(words)
        wait_for(lambda: self.asked > self.given)  # the next pass has started

    def release(self):
        self._words.put(None)


def wait_for(condition):
    deadline = time.monotonic() + 5
    while not condition():
        assert time.monotonic() < deadline, "timed out"
        time.sleep(0.001)


@pytest.fixture
def env(monkeypatch):
    config = argparse.Namespace(
        language="en",
        stream_output="auto",
        stream_engine="whisper",
        final_engine="whisper",
        stream_interval=0.001,
        stream_tail=True,
        api=None,
    )
    monkeypatch.setattr(t, "config", config, raising=False)
    monkeypatch.setattr(t, "replacer", replacements.Replacer({}))
    monkeypatch.setattr(
        t, "audio_chunks", [np.full((int(t.SAMPLE_RATE * 1.5), 1), 0.1, np.float32)]
    )
    monkeypatch.setattr(t, "emacs_call", lambda *a: True)
    calls = []
    monkeypatch.setattr(
        t,
        "stream_write",
        # Emacs takes text and tail: True, as emacs_tail() returns.
        lambda text, route, kitty_window=None, **kw: calls.append((text, route, *kw.values()))
        or (True if kw else None),
    )
    routes = []

    def choose_route():
        routes.append(len(calls))
        return env.route

    monkeypatch.setattr(t, "choose_route", choose_route)
    monkeypatch.setattr(t, "kitty_window", lambda *a: (None, "unix:@kitty", 9))
    monkeypatch.setattr(t, "save_clipboard", lambda route: None)
    for name in ("show_status", "beep_error"):
        monkeypatch.setattr(t, name, lambda *a, **k: None)
    passes = Passes()
    monkeypatch.setattr(t, "transcribe_partial", passes)
    env = argparse.Namespace(
        config=config, calls=calls, routes=routes, passes=passes, route="emacs"
    )
    return env


def dictate(env, passes, final):
    """Stream the passes, then write the final transcript as transcribe_and_paste does."""
    session = t.StreamingSession()
    for words in passes:
        env.passes.run(words)
    env.passes.release()
    session.stop()
    session.type_words(t.streaming.remainder(session.typed, final.split()))
    session.flush()
    return session


PASSES = ["hello world", "hello world how", "hello world how are you"]


def test_emacs_shows_each_pass_beyond_the_settled_words(env):
    session = t.StreamingSession()
    env.passes.run(PASSES[0])
    assert env.calls == [("", "emacs", " hello world")]
    env.passes.run(PASSES[1])
    assert env.calls[1:] == [(" hello world", "emacs", " how")]
    env.passes.run(PASSES[2])
    assert env.calls[2:] == [(" how", "emacs", " are you")]
    env.passes.release()
    session.stop()
    session.type_words(["are", "you"])
    session.flush()
    # The final words replace the tail in the same call.
    assert env.calls[3:] == [(" are you", "emacs", "")]
    assert session.tail == ""
    assert "".join(c[0] for c in env.calls) == " hello world how are you"


def test_an_unchanged_tail_is_not_sent_again(env):
    dictate(env, ["nice weather", "nice weather", "nice weather"], "nice weather")
    assert env.calls == [
        ("", "emacs", " nice weather"),
        (" nice", "emacs", " weather"),
        (" weather", "emacs", ""),
    ]


def test_a_pass_that_settles_everything_removes_the_tail(env):
    session = t.StreamingSession()
    env.passes.run("one two")
    env.passes.run("one two three")
    env.passes.run("one two")
    assert env.calls[2:] == [("", "emacs", "")]
    env.passes.release()
    session.stop()


def test_without_a_final_write_end_leaves_the_tail_to_talktype_end(env, monkeypatch):
    ended = []
    monkeypatch.setattr(t, "emacs_call", lambda f, *a: ended.append(f) or True)
    session = dictate(env, ["hello world"], "")
    session.end()
    assert env.calls == [("", "emacs", " hello world")]
    assert ended == ["talktype-begin", "talktype-end"]


def test_the_tail_gets_the_replacements(env, monkeypatch):
    monkeypatch.setattr(t, "replacer", replacements.Replacer({"cloud code": "Claude Code"}))
    dictate(env, ["I use cloud", "I use cloud code on"], "I use cloud code on onyx")
    assert env.calls[:2] == [
        ("", "emacs", " I use cloud"),
        (" I use", "emacs", " Claude Code on"),
    ]
    assert "".join(c[0] for c in env.calls) == " I use Claude Code on onyx"


def test_a_hallucinated_first_pass_shows_no_tail(env):
    dictate(env, ["Thank you."], "")
    assert env.calls == []


def test_no_stream_tail_writes_emacs_as_before(env):
    env.config.stream_tail = False
    dictate(env, PASSES, "hello world how are you")
    assert env.calls == [(" hello world", "emacs"), (" how", "emacs"), (" are you", "emacs")]


@pytest.mark.parametrize("route", ["kitty", "type", "paste", "type-or-paste", "terminal-paste"])
@pytest.mark.parametrize("output", ["auto", "kitty"])
def test_other_routes_never_get_a_tail(env, route, output):
    env.route = route
    env.config.stream_output = output
    dictate(env, PASSES, "hello world how are you")
    with_tail = list(env.calls)
    env.calls.clear()
    env.config.stream_tail = False
    dictate(env, PASSES, "hello world how are you")
    assert with_tail == env.calls
    assert with_tail == [(" hello world", route), (" how", route), (" are you", route)]


def test_a_route_set_in_the_config_is_chosen_at_the_first_settled_words(env):
    env.route = env.config.stream_output = "kitty"
    dictate(env, PASSES, "hello world how are you")
    # As without the tail: no call before the route, chosen by the second pass.
    assert env.routes == [0]
    assert env.passes.asked >= 2


def test_nemotron_never_gets_a_tail(env, monkeypatch):
    env.config.stream_engine = env.config.final_engine = "nemotron"

    class Chunks:
        def __init__(self, engine, language):
            self.chunks = [" hello world", " how are you"]

        def feed(self, audio):
            return self.chunks.pop(0) if self.chunks else ""

        def flush(self):
            return ""

    monkeypatch.setattr(t, "nemotron_engine", object(), raising=False)
    monkeypatch.setattr(t.nemotron, "Stream", Chunks)
    monkeypatch.setattr(t, "audio_chunks", [])
    session = t.NemotronSession()
    for n in (1, 2):
        t.audio_chunks.append(np.full((int(t.SAMPLE_RATE * 0.6), 1), 0.1, np.float32))
        wait_for(lambda n=n: len(env.calls) == n)
    session.finish()
    assert env.calls == [(" hello world", "emacs"), (" how are you", "emacs")]


def test_a_failed_tail_keeps_the_old_one_and_the_route(env, monkeypatch):
    def failing(text, route, kitty_window=None, tail=None):
        env.calls.append((text, route, tail))
        return bool(text)

    monkeypatch.setattr(t, "stream_write", failing)
    session = t.StreamingSession()
    env.passes.run("hello world")
    assert session.tail == "" and session.route == "emacs"
    env.passes.release()
    session.stop()


def parse(monkeypatch, file_config, argv=()):
    monkeypatch.setattr(t, "load_config_file", lambda: file_config)
    monkeypatch.setattr(sys, "argv", ["talktype", *argv])
    return t.parse_args()


def test_stream_tail_is_on_by_default_and_has_flags(monkeypatch):
    assert parse(monkeypatch, {}).stream_tail is True
    assert parse(monkeypatch, {}, ["--no-stream-tail"]).stream_tail is False
    off = {"transcription": {"stream_tail": False}}
    assert parse(monkeypatch, off).stream_tail is False
    assert parse(monkeypatch, off, ["--stream-tail"]).stream_tail is True


def test_emacs_tail_sends_one_call_that_catches_tail_errors(monkeypatch):
    exprs = []
    out = {"stdout": b"t\n"}
    monkeypatch.setattr(
        t,
        "emacsclient",
        lambda expr, capture=False: exprs.append((expr, capture))
        or argparse.Namespace(returncode=0, **out),
    )
    assert t.stream_write(" eins", "emacs", tail=' "zwei"') is True
    assert t.stream_write("", "emacs", tail="") is True
    assert exprs == [
        (
            (
                '(progn (talktype-append " eins") '
                '(ignore-errors (talktype-set-tail " \\"zwei\\"")))'
            ),
            True,
        ),
        ('(ignore-errors (talktype-set-tail ""))', True),
    ]
    out["stdout"] = b"nil\n"  # the tail failed, the text arrived
    assert t.stream_write(" drei", "emacs", tail=" vier") is None


def test_a_tail_emacs_did_not_take_is_sent_again(env, monkeypatch):
    results = [None, True]

    def write(text, route, kitty_window=None, tail=None):
        env.calls.append((text, route, tail))
        return results.pop(0) if results else True

    monkeypatch.setattr(t, "stream_write", write)
    session = t.StreamingSession()
    env.passes.run("nice weather")
    assert session.tail == ""
    env.passes.run("nice weather")
    assert env.calls == [("", "emacs", " nice weather"), (" nice", "emacs", " weather")]
    assert session.tail == " weather"
    env.passes.run("nice weather")
    env.passes.run("nice weather")
    assert env.calls[2:] == []  # unchanged and delivered
    env.passes.release()
    session.stop()
