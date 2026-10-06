"""The watchdog stops a forgotten recording through the record key's stop path."""

import argparse
import os
import threading
import time

import numpy as np
import pytest

if not os.environ.get("DISPLAY"):
    pytest.skip(
        "talktype imports pynput, which needs an X display", allow_module_level=True
    )

import talktype as t  # noqa: E402
from pynput import keyboard  # noqa: E402

KEY = keyboard.Key.f9
START, STOP, WARN, AUTO_STOP = 880, 440, 1320, 330


class FakeStream:
    """sd.InputStream without a microphone; the tests call audio_callback."""

    def __init__(self, callback, **kwargs):
        self.callback = callback

    def start(self):
        pass

    def stop(self):
        pass

    def close(self):
        pass


def until(condition, timeout=3.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if condition():
            return True
        time.sleep(0.01)
    return False


@pytest.fixture
def recorder(monkeypatch):
    """Record key handlers with fake audio; real start, stop and watchdog."""
    beeps, transcribed = [], []
    monkeypatch.setattr(t, "state", t.State.IDLE)
    monkeypatch.setattr(t, "session", None)
    monkeypatch.setattr(t, "recording_guard", None)
    monkeypatch.setattr(t, "AUTOSTOP_CHECK_S", 0.02)
    monkeypatch.setattr(t.sd, "InputStream", FakeStream)
    monkeypatch.setattr(t, "get_active_window", lambda: None)
    monkeypatch.setattr(t, "beep", lambda freq, duration, **kw: beeps.append(freq) or True)
    monkeypatch.setattr(
        t, "transcribe_and_paste", lambda audio, live: transcribed.append(audio)
    )
    handlers = []

    def make(silence_stop_s, max_s, mode="toggle"):
        monkeypatch.setattr(
            t,
            "config",
            argparse.Namespace(
                silence_stop_s=silence_stop_s,
                max_s=max_s,
                stream=False,
                sounds=dict(t.DEFAULT_SOUNDS),
                minimal=False,
            ),
            raising=False,
        )
        on_press, on_release = t.create_hotkey_handler(KEY, t.RecordKey(mode))
        handlers[:] = [on_press, on_release]

        def press(release=True):
            monkeypatch.setattr(t, "_last_hotkey_time", 0.0)  # no debounce
            on_press(KEY)
            if release:
                on_release(KEY)

        return press

    yield make, beeps, transcribed
    if handlers and t.state == t.State.RECORDING:
        monkeypatch.setattr(t, "_last_hotkey_time", 0.0)
        handlers[0](KEY)  # ends the watchdog


def test_silence_stops_once_with_the_auto_stop_tone(recorder, capsys):
    make, beeps, transcribed = recorder
    press = make(silence_stop_s=0.3, max_s=0)
    press()
    assert t.state == t.State.RECORDING
    assert until(lambda: transcribed)
    time.sleep(0.2)
    assert len(transcribed) == 1
    assert t.state == t.State.TRANSCRIBING
    assert beeps == [START, AUTO_STOP]
    out = capsys.readouterr().out
    assert "[stream] auto-stop: silence 0.3 s" in out
    assert "[stream] beep auto_stop" in out


def test_the_warning_beeps_before_the_silence_stop(recorder, monkeypatch, capsys):
    monkeypatch.setattr(t.autostop, "WARN_BEFORE_S", 0.2)
    make, beeps, transcribed = recorder
    make(silence_stop_s=0.3, max_s=0)()
    assert until(lambda: transcribed)
    assert beeps == [START, WARN, AUTO_STOP]
    assert "[stream] warn: silence 0.1 s" in capsys.readouterr().out


def test_speech_keeps_the_recording_on(recorder):
    make, _, transcribed = recorder
    make(silence_stop_s=0.3, max_s=0)()
    loud = np.full((800, 1), 0.1, np.float32)
    for _ in range(16):  # 0.8 s of speech
        t.audio_callback(loud, len(loud), None, None)
        time.sleep(0.05)
    assert t.state == t.State.RECORDING and not transcribed
    assert until(lambda: transcribed)
    assert len(transcribed[0]) == 16 * 800


def test_a_held_key_stops_only_at_the_maximum_length(recorder, capsys):
    make, beeps, transcribed = recorder
    press = make(silence_stop_s=0.2, max_s=1, mode="hold")
    press(release=False)
    time.sleep(0.6)
    assert t.state == t.State.RECORDING
    assert until(lambda: transcribed)
    assert beeps == [START, AUTO_STOP]
    assert "[stream] auto-stop: max length 1 s" in capsys.readouterr().out


def test_a_key_press_racing_the_auto_stop_stops_once(recorder):
    make, beeps, transcribed = recorder
    press = make(silence_stop_s=0.1, max_s=0)
    press()
    with t.state_lock:
        time.sleep(0.3)  # the watchdog is due and waits for the lock
        key = threading.Thread(target=press)
        key.start()
        time.sleep(0.05)  # so does the key press
    key.join()
    time.sleep(0.2)
    assert len(transcribed) == 1
    assert len([b for b in beeps if b in (STOP, AUTO_STOP)]) == 1


def test_an_old_watchdog_leaves_the_next_recording_alone(recorder):
    make, beeps, transcribed = recorder
    press = make(silence_stop_s=1, max_s=0)
    press()
    time.sleep(0.5)
    press()  # stop by key
    t.state = t.State.IDLE  # transcription done
    press()  # the next recording
    time.sleep(0.8)  # past the first recording's silence stop
    assert t.state == t.State.RECORDING
    assert len(transcribed) == 1
    assert beeps == [START, STOP, START]
