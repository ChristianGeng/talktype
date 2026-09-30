"""The API model name comes from the config file, unless --api-model is given."""

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
