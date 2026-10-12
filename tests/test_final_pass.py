"""The final pass after streaming starts from the open sentence.

A fake Whisper model knows when each word of the recording was spoken and
returns the words in the audio it is given, recording the samples; scripted
passes stand in for the stream engine. Routes are recorded instead of
written, so nothing reaches the desktop running the tests.
"""

import argparse
import os
import queue
import time

import numpy as np
import pytest

if not os.environ.get("DISPLAY"):
    pytest.skip(
        "talktype imports pynput, which needs an X display", allow_module_level=True
    )

import replacements  # noqa: E402
import talktype as t  # noqa: E402

REAL_TRANSCRIBE_PARTIAL = t.transcribe_partial
SECONDS = 6
# The recording's words and when they start, in seconds.
SPOKEN = [("Hello", 0.0), ("there.", 0.5), ("How", 3.0), ("are", 3.3), ("you", 3.6), ("today?", 3.9)]
OPEN_SENTENCE = int(3.0 * t.SAMPLE_RATE)  # where "How" starts


def heard(samples):
    """The words in the last `samples` of the recording."""
    begin = (SECONDS * t.SAMPLE_RATE - samples) / t.SAMPLE_RATE
    return [(word, start - begin) for word, start in SPOKEN if start >= begin]


class FakeWhisper:
    """Whisper: streaming passes (beam_size=1) are answered by `stream`."""

    def __init__(self):
        self.received = []  # the audio of each final pass
        self.languages = []  # and the language it was given
        self.stream = None

    def transcribe(self, audio, language=None, beam_size=5, **kw):
        if beam_size == 1:
            return self.stream.whisper(audio, language, **kw)
        self.received.append(audio.copy())
        self.languages.append(language)
        text = " ".join(word for word, _ in heard(len(audio)))
        return [argparse.Namespace(text=text)], None


class Passes:
    """transcribe_partial with word start times, one pass per word count given."""

    def __init__(self):
        self._counts = queue.Queue()
        self.asked = 0
        self.given = 0

    def _heard(self, audio):
        self.asked += 1
        count = self._counts.get(timeout=5)
        if count is None:
            raise RuntimeError("stopped")  # the session skips a failed pass
        return heard(len(audio))[:count]

    def __call__(self, audio):
        words = self._heard(audio)
        return [w for w, _ in words], [s for _, s in words]

    def whisper(self, audio, language, word_timestamps=False):
        """The pass as faster-whisper returns it: segments, with words if asked,
        and the language given, else German as detected."""
        words = self._heard(audio)
        segment = argparse.Namespace(
            text="".join(" " + w for w, _ in words),
            words=[argparse.Namespace(word=" " + w, start=s) for w, s in words] if word_timestamps else None,
        )
        return [segment], argparse.Namespace(language=language or "de")

    def run(self, count):
        """Run one pass hearing `count` words; return once it has been written."""
        self.given += 1
        self._counts.put(count)
        wait_for(lambda: self.asked > self.given)  # the next pass has started

    def release(self):
        self._counts.put(None)


class FakeHistory:
    def __init__(self):
        self.entries = []

    def add(self, text, raw=None):
        self.entries.append(text)

    def save_pending_audio(self, wav):
        pass

    def clear_pending_audio(self):
        pass


def wait_for(condition):
    deadline = time.monotonic() + 5
    while not condition():
        assert time.monotonic() < deadline, "timed out"
        time.sleep(0.001)


@pytest.fixture
def env(monkeypatch):
    config = argparse.Namespace(
        language="en",
        stream_output="kitty",
        stream_engine="whisper",
        final_engine="whisper",
        stream_interval=0.001,
        stream_tail=False,
        api=None,
        hotkey="f9",
        record_mode="toggle",
    )
    monkeypatch.setattr(t, "config", config, raising=False)
    monkeypatch.setattr(t, "replacer", replacements.Replacer({}))
    # Every sample differs, so a slice of the recording tells where it starts.
    samples = SECONDS * t.SAMPLE_RATE
    audio = (0.1 + 0.1 * np.arange(samples) / samples).astype(np.float32).reshape(-1, 1)
    monkeypatch.setattr(t, "audio_chunks", [audio])
    whisper = FakeWhisper()
    monkeypatch.setattr(t, "whisper_model", whisper, raising=False)
    passes = Passes()
    monkeypatch.setattr(t, "transcribe_partial", passes)
    written = []
    monkeypatch.setattr(t, "choose_route", lambda: "kitty")
    monkeypatch.setattr(t, "kitty_window", lambda *a: (None, "unix:@kitty", 9))
    monkeypatch.setattr(
        t, "stream_write", lambda text, route, kitty_window=None, **kw: written.append(text)
    )
    pasted = []
    monkeypatch.setattr(t, "paste_text", lambda text, **kw: pasted.append(text))
    history = FakeHistory()
    monkeypatch.setattr(t, "history", history)
    for name in ("show_status", "set_terminal_title", "beep_success", "beep_error"):
        monkeypatch.setattr(t, name, lambda *a, **k: None)
    return argparse.Namespace(
        config=config,
        audio=audio.flatten(),
        whisper=whisper,
        passes=passes,
        written=written,
        pasted=pasted,
        history=history,
    )


def stream_past_a_sentence(env):
    """Stream until "Hello there. How" is typed and the offset is at "How"."""
    session = t.StreamingSession()
    env.passes.run(3)
    env.passes.run(4)  # agrees on the first three words
    env.passes.release()
    session.stop()
    assert session.typed == ["Hello", "there.", "How"]
    assert (session.offset, session.window) == (OPEN_SENTENCE, ["How"])
    return session


def assert_received(received, expected):
    """One final pass, given exactly the samples `expected`."""
    assert len(received) == 1
    np.testing.assert_array_equal(received[0], expected)


def finish(env, session=None):
    sleep = t.time.sleep
    t.time.sleep = lambda s: None  # the pause before READY
    try:
        t.transcribe_and_paste(env.audio, session)
    finally:
        t.time.sleep = sleep


def test_whisper_finishes_from_the_open_sentence(env, capsys):
    session = stream_past_a_sentence(env)
    finish(env, session)
    assert_received(env.whisper.received, env.audio[OPEN_SENTENCE:])
    # The same text as a pass over the whole recording gives.
    assert "".join(env.written) == " Hello there. How are you today?"
    assert env.history.entries == ["Hello there. How are you today?"]
    assert "[stream] final pass: 0.0 s for 3.0 s of audio" in capsys.readouterr().out


def test_whisper_streaming_moves_the_offset_at_a_sentence_end(env, monkeypatch):
    monkeypatch.setattr(t, "transcribe_partial", REAL_TRANSCRIBE_PARTIAL)
    env.whisper.stream = env.passes
    session = stream_past_a_sentence(env)
    finish(env, session)
    assert_received(env.whisper.received, env.audio[OPEN_SENTENCE:])
    assert "".join(env.written) == " Hello there. How are you today?"


def test_the_tail_gets_the_language_detected_while_streaming(env, monkeypatch):
    monkeypatch.setattr(t, "transcribe_partial", REAL_TRANSCRIBE_PARTIAL)
    env.whisper.stream = env.passes
    env.config.language = None
    finish(env, stream_past_a_sentence(env))
    assert env.whisper.languages == ["de"]


def test_a_configured_language_stays_for_the_tail(env, monkeypatch):
    monkeypatch.setattr(t, "transcribe_partial", REAL_TRANSCRIBE_PARTIAL)
    env.whisper.stream = env.passes
    finish(env, stream_past_a_sentence(env))
    assert env.whisper.languages == ["en"]


def test_the_whole_recording_detects_its_language_as_before(env):
    env.config.language = None
    finish(env)
    assert env.whisper.languages == [None]


def test_parakeet_finishes_from_the_open_sentence_as_before(env, monkeypatch):
    env.config.stream_engine = env.config.final_engine = "parakeet"
    received = []
    monkeypatch.setattr(t, "stream_model", object(), raising=False)
    monkeypatch.setattr(
        t.parakeet,
        "transcribe",
        lambda model, audio: received.append(audio.copy()) or " ".join(w for w, _ in heard(len(audio))),
    )
    session = stream_past_a_sentence(env)
    finish(env, session)
    assert_received(received, env.audio[OPEN_SENTENCE:])
    assert env.whisper.received == []
    assert "".join(env.written) == " Hello there. How are you today?"


def test_without_an_offset_whisper_gets_the_whole_recording(env, capsys):
    session = t.StreamingSession()
    env.passes.run(1)
    env.passes.run(2)  # "Hello" typed, no sentence end yet
    env.passes.release()
    session.stop()
    assert session.offset == 0
    finish(env, session)
    assert_received(env.whisper.received, env.audio)
    assert "".join(env.written) == " Hello there. How are you today?"
    assert "[stream] final pass: 0.0 s for 6.0 s of audio" in capsys.readouterr().out


def test_without_streaming_whisper_gets_the_whole_recording(env, capsys):
    finish(env)
    assert_received(env.whisper.received, env.audio)
    assert env.pasted == [" Hello there. How are you today?"]
    assert "[stream]" not in capsys.readouterr().out


def test_nemotron_finishes_without_a_final_pass(env, monkeypatch):
    env.config.stream_engine = env.config.final_engine = "nemotron"

    class Chunks:
        def __init__(self, engine, language):
            pass

        def feed(self, audio):
            return ""

        def flush(self):
            return " Hello there."

    monkeypatch.setattr(t, "nemotron_engine", object(), raising=False)
    monkeypatch.setattr(t.nemotron, "Stream", Chunks)
    monkeypatch.setattr(t, "audio_chunks", [])
    monkeypatch.setattr(t.nemotron, "transcribe", lambda *a: pytest.fail("no final pass"))
    finish(env, t.NemotronSession())
    assert env.whisper.received == []
    assert "".join(env.written) == " Hello there."
