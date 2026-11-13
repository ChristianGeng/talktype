"""The vocabulary reaches Whisper as hotwords, in every Whisper call (#72)."""

import argparse
import io
import os
import re
import sys
from pathlib import Path

import numpy as np
import pytest
from scipy.io import wavfile

if not os.environ.get("DISPLAY"):
    pytest.skip(
        "talktype imports pynput, which needs an X display", allow_module_level=True
    )

import talktype as t  # noqa: E402


class RecordingWhisper:
    """faster-whisper's model: records the keyword arguments of every call."""

    def __init__(self):
        self.calls = []

    def transcribe(self, audio, **kw):
        self.calls.append(kw)
        words = [argparse.Namespace(word=" hello", start=0.0)]
        return [argparse.Namespace(text=" hello", words=words)], argparse.Namespace(
            language="en"
        )


class Tokens:
    """hf_tokenizer stand-in: one token per word."""

    def encode(self, text, add_special_tokens=False):
        return argparse.Namespace(ids=text.split())


def speech(seconds=1.0):
    return np.full(int(t.SAMPLE_RATE * seconds), 0.1, np.float32)


@pytest.fixture
def whisper(monkeypatch):
    model = RecordingWhisper()
    monkeypatch.setattr(t, "whisper_model", model)
    monkeypatch.setattr(t, "hotwords", "ONNX LiveKit")
    monkeypatch.setattr(
        t,
        "config",
        argparse.Namespace(
            api=None, final_engine="whisper", language="en", stream_engine="whisper"
        ),
        raising=False,
    )
    monkeypatch.setattr(t, "history", None)
    return model


def test_the_final_pass_gets_the_hotwords(whisper):
    t.transcribe(speech())
    assert whisper.calls[-1]["hotwords"] == "ONNX LiveKit"


def test_streaming_passes_get_the_hotwords(whisper):
    t.transcribe_partial(speech())
    assert whisper.calls[-1]["hotwords"] == "ONNX LiveKit"


@pytest.mark.parametrize("words", ["ONNX LiveKit", None])
def test_retry_gets_the_hotwords(whisper, monkeypatch, words):
    monkeypatch.setattr(t, "hotwords", words)
    buffer = io.BytesIO()
    wavfile.write(buffer, t.SAMPLE_RATE, (speech() * 32767).astype(np.int16))

    class History:
        def get_pending_audio(self):
            return buffer.getvalue()

        def add(self, text, raw=None):
            pass

        def clear_pending_audio(self):
            pass

    monkeypatch.setattr(t, "history", History())
    monkeypatch.setattr(t, "state", t.State.IDLE)
    for name in (
        "get_active_window",
        "set_terminal_title",
        "show_status",
        "beep_success",
        "beep_error",
        "paste_text",
    ):
        monkeypatch.setattr(t, name, lambda *a, **k: None)
    t.create_retry_handler("f7")("f7")
    assert whisper.calls and whisper.calls[-1]["hotwords"] == words


def test_every_whisper_call_in_the_code_passes_hotwords():
    # A new call site must not forget them.
    source = Path(t.__file__).read_text(encoding="utf-8")
    calls = re.findall(r"whisper_model\.transcribe\((.*?)\n\s*\)", source, re.S)
    calls += re.findall(r"whisper_model\.transcribe\(([^\n]*)\)\n", source)
    assert len(calls) >= 3
    assert all("hotwords=hotwords" in call for call in calls), calls


@pytest.fixture
def loading(monkeypatch):
    model = RecordingWhisper()
    model.hf_tokenizer = Tokens()
    monkeypatch.setattr(t, "whisper_model", model)
    monkeypatch.setattr(t, "hotwords", "stale")

    def load(vocabulary, hotwords=True):
        monkeypatch.setattr(
            t,
            "config",
            argparse.Namespace(vocabulary=vocabulary, hotwords=hotwords),
            raising=False,
        )
        t.load_hotwords()
        return t.hotwords

    return load


def test_loading_takes_the_vocabulary(loading, capsys):
    assert loading(["ONNX", "LiveKit"]) == "ONNX LiveKit"
    assert "Whisper hotwords: 2 vocabulary terms" in capsys.readouterr().out


def test_loading_says_when_terms_do_not_fit(loading, capsys, monkeypatch):
    monkeypatch.setattr(t.engines, "WHISPER_HOTWORD_TOKENS", 2)
    assert loading(["ONNX", "LiveKit", "Parakeet"]) == "ONNX LiveKit"
    assert "the other 1 don't fit" in capsys.readouterr().out


@pytest.mark.parametrize("vocabulary, on", [([], True), (["ONNX"], False)])
def test_no_hotwords_without_vocabulary_or_when_off(loading, vocabulary, on):
    assert loading(vocabulary, on) is None


def test_hotwords_default_on_and_come_from_the_config(monkeypatch):
    monkeypatch.setattr(sys, "argv", ["talktype"])
    monkeypatch.setattr(t, "load_config_file", dict)
    assert t.parse_args().hotwords is True
    monkeypatch.setattr(t, "load_config_file", lambda: {"text": {"hotwords": False}})
    assert t.parse_args().hotwords is False
    monkeypatch.setattr(t, "load_config_file", lambda: {"text": {"hotwords": "yes"}})
    with pytest.raises(SystemExit):
        t.parse_args()
def test_without_hotwords_whisper_gets_none(whisper, monkeypatch):
    monkeypatch.setattr(t, "hotwords", None)
    t.transcribe(speech())
    t.transcribe_partial(speech())
    assert [call["hotwords"] for call in whisper.calls] == [None, None]


@pytest.mark.parametrize("engine", ["parakeet", "nemotron", "api"])
def test_other_final_engines_do_not_call_whisper(whisper, monkeypatch, engine):
    if engine == "api":
        t.config.api = "http://localhost:8002/transcribe"
        monkeypatch.setattr(t, "transcribe_api", lambda wav: "hello")
    else:
        t.config.final_engine = engine
    monkeypatch.setattr(t.parakeet, "transcribe", lambda model, audio: "hello")
    monkeypatch.setattr(t.nemotron, "transcribe", lambda model, audio, language: "hello")
    assert t.transcribe(speech()) == "hello"
    assert whisper.calls == []
