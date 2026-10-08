"""Replacements reach every engine's text and every route, exactly once.

Fake engines stand in for the models, and the routes are recorded instead
of typing, so nothing reaches the desktop running the tests.
"""

import argparse
import json
import os
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

LIST = {"onyx": "onnx", "cloud code": "Claude Code"}
STREAM_WRITE = t.stream_write


class FakeHistory:
    def __init__(self):
        self.entries = []

    def add(self, text, raw=None):
        self.entries.append((text, raw))

    def save_pending_audio(self, wav):
        pass

    def clear_pending_audio(self):
        pass


class ChunkStream:
    """Nemotron's stream: each feed returns the next chunk's text."""

    chunks: list[str] = []
    fed = 0

    def __init__(self, engine, language):
        ChunkStream.fed = 0

    def feed(self, audio):
        ChunkStream.fed += 1
        return self.chunks.pop(0) if self.chunks else ""

    def flush(self):
        return ""


def wait_for(condition):
    deadline = time.monotonic() + 5
    while not condition():
        assert time.monotonic() < deadline, "timed out"
        time.sleep(0.01)


@pytest.fixture
def env(monkeypatch):
    config = argparse.Namespace(
        language="en",
        stream_output="auto",
        stream_interval=0.01,
        final_engine="whisper",
        api=None,
        hotkey="f9",
        record_mode="toggle",
    )
    monkeypatch.setattr(t, "config", config, raising=False)
    monkeypatch.setattr(t, "replacer", replacements.Replacer(LIST))
    monkeypatch.setattr(t, "audio_chunks", [])
    monkeypatch.setattr(t, "nemotron_engine", object(), raising=False)
    monkeypatch.setattr(t.nemotron, "Stream", ChunkStream)
    written = []
    monkeypatch.setattr(t, "choose_route", lambda: "kitty")
    monkeypatch.setattr(t, "kitty_window", lambda *a: (None, "unix:@kitty", 9))
    monkeypatch.setattr(
        t, "stream_write", lambda text, route, kitty_window=None: written.append((text, route))
    )
    pasted = []
    monkeypatch.setattr(t, "paste_text", lambda text, **kw: pasted.append(text))
    history = FakeHistory()
    monkeypatch.setattr(t, "history", history)
    for name in ("show_status", "set_terminal_title", "beep_success", "beep_error"):
        monkeypatch.setattr(t, name, lambda *a, **k: None)
    monkeypatch.setattr(t.time, "sleep", lambda s: None)  # the pause before READY
    return argparse.Namespace(
        config=config, written=written, pasted=pasted, history=history
    )


def add_audio(seconds=0.1):
    t.audio_chunks.append(np.full((int(t.SAMPLE_RATE * seconds), 1), 0.1, np.float32))


def nemotron_dictation(chunks):
    ChunkStream.chunks = list(chunks)
    session = t.NemotronSession()
    for n in range(1, len(chunks) + 1):
        add_audio()
        wait_for(lambda n=n: ChunkStream.fed >= n)
    t.transcribe_and_paste(np.zeros(0, np.float32), session)
    return session


def test_nemotron_types_a_word_split_across_chunks_once(env):
    nemotron_dictation([" on", "yx is fast"])
    assert "".join(text for text, _ in env.written) == " onnx is fast"
    assert env.history.entries == [("onnx is fast", "onyx is fast")]


def test_nemotron_waits_for_a_phrase_split_across_chunks(env):
    nemotron_dictation([" I use cloud", " code daily"])
    assert "".join(text for text, _ in env.written) == " I use Claude Code daily"
    assert env.history.entries == [("I use Claude Code daily", "I use cloud code daily")]


def test_nemotron_types_words_that_cannot_change_before_the_stop(env):
    # #25: nothing in " hello world how are you" can become a listed word,
    # so all of it is typed while recording, none of it after the release
    ChunkStream.chunks = [" hello world", " how are you"]
    session = t.NemotronSession()
    for n in (1, 2):
        add_audio()
        wait_for(lambda n=n: ChunkStream.fed >= n)
    wait_for(lambda: "".join(text for text, _ in env.written) == " hello world how are you")
    t.transcribe_and_paste(np.zeros(0, np.float32), session)
    assert "".join(text for text, _ in env.written) == " hello world how are you"


@pytest.mark.parametrize("route", ["kitty", "type", "paste", "type-or-paste", "emacs"])
def test_every_route_gets_the_replaced_text(env, monkeypatch, route):
    monkeypatch.setattr(t, "choose_route", lambda: route)
    monkeypatch.setattr(t, "emacs_call", lambda *a: True)
    nemotron_dictation([" on", "yx is fast"])
    assert env.written and {r for _, r in env.written} == {route}
    assert "".join(text for text, _ in env.written) == " onnx is fast"


def test_kitty_receives_the_replaced_text(env, monkeypatch):
    runs = []
    monkeypatch.setattr(t, "stream_write", STREAM_WRITE)
    monkeypatch.setattr(t, "kitty_window", lambda *a: (None, "unix:@kitty", 9))
    env.config.kitten, env.config.kitty_socket = "kitten", "unix:@kitty"
    monkeypatch.setattr(
        t.subprocess,
        "run",
        lambda cmd, **kw: runs.append(cmd) or argparse.Namespace(returncode=0),
    )
    nemotron_dictation([" on", "yx is fast"])
    assert "".join(cmd[-1] for cmd in runs) == " onnx is fast"
    assert all(cmd[:5] == ["kitten", "@", "--to", "unix:@kitty", "send-text"] for cmd in runs)


@pytest.mark.parametrize("engine", ["whisper", "parakeet"])
def test_re_transcribing_streams_get_the_replacements(env, monkeypatch, engine):
    env.config.stream_engine = env.config.final_engine = engine
    passes = ["I use cloud", "I use cloud code", "I use cloud code on onyx"]
    monkeypatch.setattr(
        t, "transcribe_partial", lambda audio: ((passes.pop(0) if len(passes) > 1 else passes[0]).split(), None)
    )
    monkeypatch.setattr(t, "transcribe", lambda audio, tail_from=0: "I use cloud code on onyx")
    add_audio(seconds=1.5)
    session = t.StreamingSession()
    wait_for(lambda: len(session.typed) == 5)  # all but the last word
    t.transcribe_and_paste(np.zeros(0, np.float32), session)
    assert "".join(text for text, _ in env.written) == " I use Claude Code on onnx"
    assert env.history.entries == [
        ("I use Claude Code on onnx", "I use cloud code on onyx")
    ]


def test_the_final_text_is_replaced_without_streaming(env, monkeypatch):
    monkeypatch.setattr(t, "transcribe", lambda audio, tail_from=0: "Onyx, and cloud code.")
    t.transcribe_and_paste(np.zeros(0, np.float32))
    assert env.pasted == [" onnx, and Claude Code."]
    assert env.history.entries == [("onnx, and Claude Code.", "Onyx, and cloud code.")]


def test_history_file_keeps_the_raw_text_when_it_differs(monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path))
    history = t.TranscriptionHistory()
    history.add("onnx is fast", raw="onyx is fast")
    history.add("it is fast", raw="it is fast")
    lines = history.history_file.read_text(encoding="utf-8").splitlines()
    entries = [json.loads(line) for line in lines]
    assert entries[0]["text"] == "onnx is fast" and entries[0]["raw"] == "onyx is fast"
    assert entries[1]["text"] == "it is fast" and "raw" not in entries[1]
    assert history.get_last() == "it is fast"


def test_replacements_come_from_the_config_file(monkeypatch):
    monkeypatch.setattr(sys, "argv", ["talktype"])
    monkeypatch.setattr(t, "load_config_file", lambda: {"replacements": {"Onyx": "onnx"}})
    assert t.parse_args().replacements == {"onyx": "onnx"}
    monkeypatch.setattr(t, "load_config_file", dict)
    assert t.parse_args().replacements == {}


@pytest.mark.parametrize("value", [["onyx"], {"onyx": None}, {"onyx": 1}])
def test_a_malformed_list_stops_with_a_config_error(monkeypatch, capsys, value):
    monkeypatch.setattr(sys, "argv", ["talktype"])
    monkeypatch.setattr(t, "load_config_file", lambda: {"replacements": value})
    with pytest.raises(SystemExit):
        t.parse_args()
    assert "Config error: replacements" in capsys.readouterr().out
