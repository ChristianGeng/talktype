"""NemotronSession must not block the hotkey callback that creates it.

Setting up a real Nemotron stream takes about 0.5 s (it decodes a lead-in
chunk of silence). Done in __init__, that ran inside the F10 callback: the
start beep came half a second late and the keyboard listener was blocked.
A fake stream with the same set-up cost stands in for the model here.
"""

import argparse
import os
import time

import numpy as np
import pytest

if not os.environ.get("DISPLAY"):
    pytest.skip(
        "talktype imports pynput, which needs an X display", allow_module_level=True
    )

import talktype as t  # noqa: E402

SETUP_SECONDS = 0.5


class SlowStream:
    def __init__(self, engine, language):
        time.sleep(SETUP_SECONDS)
        self.fed = 0

    def feed(self, audio):
        self.fed += len(audio)
        return " word" if len(audio) else ""

    def flush(self):
        return " end"


@pytest.fixture
def session_env(monkeypatch):
    monkeypatch.setattr(t.nemotron, "Stream", SlowStream)
    monkeypatch.setattr(t, "config", argparse.Namespace(language="en"), raising=False)
    monkeypatch.setattr(t, "nemotron_engine", object(), raising=False)
    monkeypatch.setattr(t, "audio_chunks", [])
    monkeypatch.setattr(t.pyperclip, "paste", lambda: "")
    pasted = []
    monkeypatch.setattr(t, "paste_text", lambda text, **kw: pasted.append(text))
    monkeypatch.setattr(t, "show_status", lambda *a, **k: None)
    return pasted


def test_creating_a_session_does_not_wait_for_the_stream(session_env):
    start = time.monotonic()
    session = t.NemotronSession()
    elapsed = time.monotonic() - start
    session.finish()
    assert elapsed < SETUP_SECONDS / 2


def test_audio_recorded_during_setup_still_reaches_the_stream(session_env):
    session = t.NemotronSession()
    t.audio_chunks.append(np.zeros((1600, 1), dtype=np.float32))  # before set-up ends
    text = session.finish()
    assert text == "word end"
    assert "".join(session_env).strip() == "word end"
