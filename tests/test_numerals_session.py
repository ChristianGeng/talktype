"""Spoken numbers reach every engine's text as digits (#70), before replacements."""

import os
import sys

import numpy as np
import pytest

if not os.environ.get("DISPLAY"):
    pytest.skip(
        "talktype imports pynput, which needs an X display", allow_module_level=True
    )

from test_replacements_session import (  # noqa: E402,F401
    ChunkStream,
    add_audio,
    env,
    nemotron_dictation,
    wait_for,
)

import numerals  # noqa: E402
import talktype as t  # noqa: E402


@pytest.fixture
def on(env, monkeypatch):  # noqa: F811
    monkeypatch.setattr(t, "numbers", numerals.Numerals("en"))
    return env


def typed(env):
    return "".join(text for text, _ in env.written)


def test_nemotron_writes_a_number_split_across_chunks_as_digits(on):
    nemotron_dictation([" we need ninety", " nine samp", "les"])
    assert typed(on) == " we need 99 samples"
    assert on.history.entries == [("we need 99 samples", "we need ninety nine samples")]


def test_nemotron_numbers_come_before_replacements(on):
    nemotron_dictation([" ninety nine on", "yx models"])
    assert typed(on) == " 99 onnx models"


def test_nemotron_writes_words_before_a_number_while_recording(on):
    # Only the number words wait for the next chunk; "we need" is typed at once.
    ChunkStream.chunks = [" we need ninety"]
    session = t.NemotronSession()
    add_audio()
    wait_for(lambda: typed(on) == " we need")
    t.transcribe_and_paste(np.zeros(0, np.float32), session)
    assert typed(on) == " we need 90"


@pytest.mark.parametrize("engine", ["whisper", "parakeet"])
def test_re_transcribing_streams_write_digits(on, monkeypatch, engine):
    on.config.stream_engine = on.config.final_engine = engine
    passes = ["we need ninety", "we need ninety nine", "we need ninety nine onyx runs"]
    monkeypatch.setattr(
        t,
        "transcribe_partial",
        lambda audio: ((passes.pop(0) if len(passes) > 1 else passes[0]).split(), None),
    )
    monkeypatch.setattr(
        t,
        "transcribe",
        lambda audio, tail_from=0, language=None: "we need ninety nine onyx runs",
    )
    add_audio(seconds=1.5)
    session = t.StreamingSession()
    wait_for(lambda: len(session.typed) == 5)
    t.transcribe_and_paste(np.zeros(0, np.float32), session)
    assert typed(on) == " we need 99 onnx runs"
    assert on.history.entries == [
        ("we need 99 onnx runs", "we need ninety nine onyx runs")
    ]


def test_the_final_text_without_streaming_gets_digits(on, monkeypatch):
    monkeypatch.setattr(
        t,
        "transcribe",
        lambda audio, tail_from=0, language=None: "Ninety nine onyx runs.",
    )
    t.transcribe_and_paste(np.zeros(0, np.float32))
    assert on.pasted == [" 99 onnx runs."]


def test_numbers_off_leaves_the_words(env, monkeypatch):  # noqa: F811
    monkeypatch.setattr(t, "numbers", numerals.Numerals("en", enabled=False))
    nemotron_dictation([" we need ninety nine samples"])
    assert typed(env) == " we need ninety nine samples"


def test_numbers_default_on_and_come_from_the_config(monkeypatch):
    monkeypatch.setattr(sys, "argv", ["talktype"])
    monkeypatch.setattr(t, "load_config_file", dict)
    assert t.parse_args().numbers is True
    monkeypatch.setattr(t, "load_config_file", lambda: {"text": {"numbers": False}})
    assert t.parse_args().numbers is False
    monkeypatch.setattr(sys, "argv", ["talktype", "--numbers"])
    assert t.parse_args().numbers is True


@pytest.mark.parametrize("value", [{"numbers": "yes"}, ["numbers"]])
def test_a_malformed_text_section_stops(monkeypatch, capsys, value):
    monkeypatch.setattr(sys, "argv", ["talktype"])
    monkeypatch.setattr(t, "load_config_file", lambda: {"text": value})
    with pytest.raises(SystemExit):
        t.parse_args()
    out = capsys.readouterr()
    assert "text" in out.out + out.err
