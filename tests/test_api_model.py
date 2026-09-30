"""The API model name comes from the config file, unless --api-model is given."""

import io
import os
import sys

import pytest

if not os.environ.get("DISPLAY"):
    pytest.skip(
        "talktype imports pynput, which needs an X display", allow_module_level=True
    )

import talktype as t  # noqa: E402


def parse(monkeypatch, file_config, argv=()):
    monkeypatch.setattr(t, "load_config_file", lambda: file_config)
    monkeypatch.setattr(sys, "argv", ["talktype", *argv])
    return t.parse_args()


def test_api_model_comes_from_the_config_file(monkeypatch):
    config = parse(monkeypatch, {"transcription": {"api_model": "whisper-large-v3"}})
    assert config.api_model == "whisper-large-v3"


def test_api_model_flag_wins_over_the_config_file(monkeypatch):
    config = parse(
        monkeypatch,
        {"transcription": {"api_model": "whisper-large-v3"}},
        ["--api-model", "whisper-1"],
    )
    assert config.api_model == "whisper-1"


def test_api_model_is_unset_without_config(monkeypatch):
    assert parse(monkeypatch, {}).api_model is None


class FakeResponse:
    def raise_for_status(self):
        pass

    def json(self):
        return {"text": "hello"}


def sent_model(monkeypatch, file_config):
    """The model field transcribe_api posts for this config file."""
    monkeypatch.setattr(t, "config", parse(monkeypatch, file_config))
    sent = {}

    def post(url, files, data, timeout):
        sent.update(data)
        return FakeResponse()

    monkeypatch.setattr(t.requests, "post", post)
    assert t.transcribe_api(io.BytesIO(b"RIFF")) == "hello"
    return sent.get("model")


GROQ = "https://api.groq.com/openai/v1/audio/transcriptions"


def test_configured_api_model_reaches_the_request(monkeypatch):
    file_config = {"transcription": {"mode": "api", "api_url": GROQ,
                                     "api_model": "whisper-large-v3"}}
    assert sent_model(monkeypatch, file_config) == "whisper-large-v3"


def test_request_falls_back_to_whisper_1(monkeypatch):
    file_config = {"transcription": {"mode": "api", "api_url": GROQ}}
    assert sent_model(monkeypatch, file_config) == "whisper-1"
