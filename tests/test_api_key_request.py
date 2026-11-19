"""transcribe_api sends the API key (#87)."""

import argparse
import io
import os

import pytest

if not os.environ.get("DISPLAY"):
    pytest.skip(
        "talktype imports pynput, which needs an X display", allow_module_level=True
    )

import apikey  # noqa: E402
import talktype as t  # noqa: E402

SECRET = "sk-test-0123456789"


class Response:
    def __init__(self, status=200):
        self.status_code = status

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")

    def json(self):
        return {"text": "hello"}


@pytest.fixture
def api(monkeypatch):
    monkeypatch.setattr(
        t,
        "config",
        argparse.Namespace(
            api="https://api.mistral.ai/v1/audio/transcriptions",
            api_model="voxtral-mini-latest",
            language="en",
        ),
        raising=False,
    )
    sent = argparse.Namespace(headers=[], response=Response())

    def post(url, files, data, timeout, auth=None):
        request = argparse.Namespace(headers={})
        if auth is not None:
            auth(request)
        sent.headers.append(request.headers)
        return sent.response

    monkeypatch.setattr(t.requests, "post", post)
    return sent


def test_the_key_goes_as_a_bearer_header(api, monkeypatch):
    monkeypatch.setenv("TT_TEST_KEY", SECRET)
    monkeypatch.setattr(t, "api_key", apikey.ApiKey(env="TT_TEST_KEY"))
    assert t.transcribe_api(io.BytesIO(b"RIFF")) == "hello"
    assert api.headers == [{"Authorization": f"Bearer {SECRET}"}]


def test_no_key_configured_sends_no_header(api, monkeypatch):
    monkeypatch.setattr(t, "api_key", apikey.ApiKey())
    t.transcribe_api(io.BytesIO(b"RIFF"))
    assert api.headers == [{}]


def test_a_refused_key_names_the_setting_and_is_read_again(api, monkeypatch):
    monkeypatch.setenv("TT_TEST_KEY", SECRET)
    key = apikey.ApiKey(env="TT_TEST_KEY")
    monkeypatch.setattr(t, "api_key", key)
    api.response = Response(401)
    with pytest.raises(RuntimeError) as e:
        t.transcribe_api(io.BytesIO(b"RIFF"))
    assert "HTTP 401" in str(e.value) and "TT_TEST_KEY" in str(e.value)
    assert SECRET not in str(e.value)
    assert key._key is None


def test_a_missing_key_fails_the_request_with_a_reason(api, monkeypatch):
    monkeypatch.delenv("TT_TEST_KEY", raising=False)
    monkeypatch.setattr(t, "api_key", apikey.ApiKey(env="TT_TEST_KEY"))
    with pytest.raises(RuntimeError, match="API key: environment variable TT_TEST_KEY"):
        t.transcribe_api(io.BytesIO(b"RIFF"))
    assert api.headers == []  # nothing sent


def test_the_settings_come_from_the_config(monkeypatch):
    import sys

    monkeypatch.setattr(sys, "argv", ["talktype"])
    monkeypatch.setattr(
        t,
        "load_config_file",
        lambda: {
            "transcription": {
                "api_key_command": "gopass show -o personal/api/mistral/mistral_api_key"
            }
        },
    )
    args = t.parse_args()
    assert args.api_key_command == "gopass show -o personal/api/mistral/mistral_api_key"
    assert args.api_key_env is None
    monkeypatch.setattr(
        t, "load_config_file", lambda: {"transcription": {"api_key_env": ""}}
    )
    with pytest.raises(SystemExit):
        t.parse_args()
