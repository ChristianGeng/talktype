"""The NO SPEECH line says why, on every path (#80)."""

import io
import os

import numpy as np
import pytest
from scipy.io import wavfile

if not os.environ.get("DISPLAY"):
    pytest.skip(
        "talktype imports pynput, which needs an X display", allow_module_level=True
    )

from test_replacements_session import ChunkStream, env  # noqa: E402,F401

import talktype as t  # noqa: E402

QUIET = np.full(t.SAMPLE_RATE * 2, 0.0004, np.float32)
LOUD = np.full(t.SAMPLE_RATE * 2, 0.05, np.float32)


@pytest.fixture
def statuses(env, monkeypatch):  # noqa: F811
    shown = []
    monkeypatch.setattr(
        t, "show_status", lambda status, detail="": shown.append((status, detail))
    )
    return shown


@pytest.mark.parametrize(
    "audio",
    [
        QUIET,
        LOUD,
        np.zeros(100, np.float32),
        np.concatenate([np.zeros(16000), np.full(800, 0.011)]).astype(np.float32),
        np.concatenate([np.zeros(16000), np.full(800, 0.009)]).astype(np.float32),
    ],
)
def test_peak_level_agrees_with_has_speech(audio):
    assert t.has_speech(audio) == (t.autostop.peak_level(audio, t.SAMPLE_RATE) > 0.01)


def test_the_final_pass_says_too_quiet(statuses, monkeypatch):
    monkeypatch.setattr(t, "transcribe", lambda audio, tail_from=0, language=None: "")
    t.transcribe_and_paste(QUIET)
    assert (
        "❌ NO SPEECH",
        "too quiet: loudest 0.0004, speech from 0.01 (microphone muted?)",
    ) in statuses


def test_the_final_pass_says_loud_but_no_words(statuses, monkeypatch):
    monkeypatch.setattr(t, "transcribe", lambda audio, tail_from=0, language=None: "")
    t.transcribe_and_paste(LOUD)
    assert (
        "❌ NO SPEECH",
        "loud enough (loudest 0.0500), but no words heard",
    ) in statuses


def test_nemotron_says_why(statuses):
    ChunkStream.chunks = []
    session = t.NemotronSession()
    t.transcribe_and_paste(QUIET, session)
    reasons = [detail for status, detail in statuses if status == "❌ NO SPEECH"]
    assert len(reasons) == 1 and reasons[0].startswith("too quiet: loudest 0.0004")


def test_retry_says_why(statuses, monkeypatch):
    buffer = io.BytesIO()
    wavfile.write(buffer, t.SAMPLE_RATE, (QUIET * 32767).astype(np.int16))

    class History:
        def get_pending_audio(self):
            return buffer.getvalue()

        def clear_pending_audio(self):
            pass

    class Whisper:
        def transcribe(self, audio, **kw):
            return [], None

    monkeypatch.setattr(t, "history", History())
    monkeypatch.setattr(t, "whisper_model", Whisper())
    monkeypatch.setattr(t, "state", t.State.IDLE)
    monkeypatch.setattr(t, "get_active_window", lambda: None)
    t.create_retry_handler("f7")("f7")
    assert statuses[-1][0] == "❌ NO SPEECH"
    assert statuses[-1][1].startswith("too quiet: loudest 0.0004")
