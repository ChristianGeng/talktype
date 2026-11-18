"""Failed Nemotron recordings are kept for the retry key (#82)."""

import argparse
import os

import numpy as np
import pytest

if not os.environ.get("DISPLAY"):
    pytest.skip(
        "talktype imports pynput, which needs an X display", allow_module_level=True
    )

from test_replacements_session import ChunkStream, add_audio, env, wait_for  # noqa: E402,F401

import talktype as t  # noqa: E402

LOUD = np.full(t.SAMPLE_RATE * 2, 0.05, np.float32)
QUIET = np.full(t.SAMPLE_RATE * 2, 0.0004, np.float32)


class PendingHistory:
    """TranscriptionHistory's pending audio, in memory."""

    def __init__(self):
        self.pending = None
        self.entries = []

    def save_pending_audio(self, wav):
        self.pending = wav.read()

    def clear_pending_audio(self):
        self.pending = None

    def get_pending_audio(self):
        return self.pending

    def add(self, text, raw=None):
        self.entries.append((text, raw))


@pytest.fixture
def run(env, monkeypatch):  # noqa: F811
    history = PendingHistory()
    monkeypatch.setattr(t, "history", history)
    shown = []
    monkeypatch.setattr(
        t, "show_status", lambda status, detail="": shown.append((status, detail))
    )

    def dictate(audio, chunks=(), retry_key="scroll_lock"):
        env.config.retry_hotkey = retry_key
        ChunkStream.chunks = list(chunks)
        session = t.NemotronSession()
        for n in range(1, len(chunks) + 1):
            add_audio()
            wait_for(lambda n=n: ChunkStream.fed >= n)
        t.transcribe_and_paste(audio, session)
        return argparse.Namespace(history=history, shown=shown)

    return dictate


def no_speech(shown):
    return [detail for status, detail in shown if status == "❌ NO SPEECH"]


def test_written_text_leaves_nothing_to_retry(run):
    result = run(LOUD, [" hello world"])
    assert result.history.entries and result.history.pending is None


def test_sound_without_words_is_kept_for_retry(run):
    result = run(LOUD)
    assert result.history.pending is not None
    assert result.history.pending.startswith(b"RIFF")
    assert no_speech(result.shown) == [
        "loud enough (loudest 0.0500), but no words heard; scroll_lock retries it"
    ]


def test_without_a_retry_key_the_line_has_no_hint(run):
    result = run(LOUD, retry_key=None)
    assert result.history.pending is not None
    assert no_speech(result.shown) == [
        "loud enough (loudest 0.0500), but no words heard"
    ]


def test_silence_is_not_kept(run):
    result = run(QUIET)
    assert result.history.pending is None
    assert no_speech(result.shown)[0].startswith("too quiet")


def test_a_short_recording_is_not_saved(run):
    result = run(np.full(t.SAMPLE_RATE // 4, 0.05, np.float32))
    assert result.history.pending is None


def test_retry_transcribes_the_kept_recording_with_whisper(run, monkeypatch):
    result = run(LOUD)
    heard = []

    class Whisper:
        def transcribe(self, audio, **kw):
            heard.append(len(audio))
            return [argparse.Namespace(text=" hello again")], None

    pasted = []
    monkeypatch.setattr(t, "whisper_model", Whisper())
    monkeypatch.setattr(t, "state", t.State.IDLE)
    monkeypatch.setattr(t, "get_active_window", lambda: None)
    monkeypatch.setattr(t, "paste_text", lambda text, **kw: pasted.append(text))
    t.create_retry_handler("scroll_lock")("scroll_lock")
    assert heard == [len(LOUD)]
    assert pasted == [" hello again"]
    assert result.history.pending is None
