"""The watchdog stops a forgotten recording through the record key's stop path.

Fake audio and a fake clock: the tests step the watchdog one check at a
time, so nothing waits for real time to pass.
"""

import argparse
import os
import threading

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
LOUD = np.full((800, 1), 0.1, np.float32)


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


class Recorder:
    """The record key's handlers with fake audio, a fake clock and a stepped watchdog."""

    def __init__(self, monkeypatch, silence_stop_s, max_s, mode, threads):
        self.monkeypatch = monkeypatch
        self.now = 0.0
        self.beeps, self.stops, self.watchdogs, self.threads = [], [], [], []
        self.transcribed = threading.Event()
        monkeypatch.setattr(t, "state", t.State.IDLE)
        monkeypatch.setattr(t, "session", None)
        monkeypatch.setattr(t, "recording_guard", None)
        monkeypatch.setattr(t, "autostop_clock", lambda: self.now)
        monkeypatch.setattr(t.sd, "InputStream", FakeStream)
        monkeypatch.setattr(t, "get_active_window", lambda: None)
        monkeypatch.setattr(t, "beep", lambda freq, duration, **kw: self.beeps.append(freq) or True)
        monkeypatch.setattr(t, "transcribe_and_paste", lambda audio, live: self.done(audio))
        stop_recording = t.stop_recording

        def counted_stop(sound):
            self.stops.append(sound.__name__)
            return stop_recording(sound)

        monkeypatch.setattr(t, "stop_recording", counted_stop)
        if threads:
            start_watchdog = t.start_watchdog
            monkeypatch.setattr(
                t, "start_watchdog", lambda *a: self.threads.append(start_watchdog(*a))
            )
        else:
            monkeypatch.setattr(t, "start_watchdog", lambda *a: self.watchdogs.append(a))
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
        self.on_press, self.on_release = t.create_hotkey_handler(KEY, t.RecordKey(mode))

    def done(self, audio):
        self.audio = audio
        self.transcribed.set()

    def press(self, release=True):
        self.monkeypatch.setattr(t, "_last_hotkey_time", 0.0)  # no debounce
        self.on_press(KEY)
        if release:
            self.on_release(KEY)

    def check(self, at, recording=-1):
        """One check of a recording's watchdog (the latest by default) at time `at`."""
        self.now = at
        waits = iter([False, True])
        t.watch_recording(*self.watchdogs[recording], wait=lambda: next(waits))


@pytest.fixture
def recorder(monkeypatch):
    made = []

    def make(silence_stop_s=60, max_s=600, mode="toggle", threads=False):
        made.append(Recorder(monkeypatch, silence_stop_s, max_s, mode, threads))
        return made[-1]

    yield make
    for rec in made:
        if t.state == t.State.RECORDING:
            rec.press()  # ends a watchdog thread
        for thread in rec.threads:
            thread.join(timeout=2)


def test_silence_stops_once_with_the_auto_stop_tone_after_a_warning(recorder, capsys):
    rec = recorder()
    rec.press()
    for at in (1, 49):
        rec.check(at)
    assert rec.beeps == [START]
    rec.check(50)
    assert rec.beeps == [START, WARN]
    rec.check(59)
    assert t.state == t.State.RECORDING and rec.beeps == [START, WARN]
    rec.check(60)
    assert t.state == t.State.TRANSCRIBING
    assert rec.stops == ["beep_auto_stop"]
    assert rec.beeps == [START, WARN, AUTO_STOP]
    assert rec.transcribed.wait(2)
    out = capsys.readouterr().out
    assert "[stream] warn: silence 50 s" in out
    assert "[stream] auto-stop: silence 60 s" in out
    assert "[stream] beep auto_stop" in out


def test_speech_restarts_the_silence(recorder):
    rec = recorder()
    rec.press()
    rec.now = 55
    t.audio_callback(LOUD, len(LOUD), None, None)
    rec.check(60)
    assert t.state == t.State.RECORDING and rec.beeps == [START]
    rec.check(105)
    assert rec.beeps == [START, WARN]
    rec.check(115)
    assert rec.stops == ["beep_auto_stop"]
    assert rec.transcribed.wait(2)
    assert len(rec.audio) == len(LOUD)


def test_a_held_key_stops_only_at_the_maximum_length(recorder, capsys):
    rec = recorder(mode="hold")
    rec.press(release=False)
    for at in (50, 60, 300, 599):
        rec.check(at)
    assert t.state == t.State.RECORDING and rec.beeps == [START]
    rec.check(600)
    assert rec.stops == ["beep_auto_stop"]
    assert "[stream] auto-stop: max length 600 s" in capsys.readouterr().out


def test_a_key_press_before_the_watchdog_stops_once(recorder):
    rec = recorder()
    rec.press()
    rec.now = 60
    rec.press()  # the key is first
    rec.check(60)
    assert rec.stops == ["beep_stop"]
    assert rec.beeps == [START, STOP]


def test_a_key_press_after_the_auto_stop_stops_nothing(recorder):
    rec = recorder()
    rec.press()
    rec.check(60)  # the watchdog is first
    rec.press()
    assert rec.stops == ["beep_auto_stop"]
    assert rec.beeps == [START, AUTO_STOP]


def test_an_old_watchdog_leaves_the_next_recording_alone(recorder):
    rec = recorder()
    rec.press()
    rec.now = 30
    rec.press()  # stop by key
    t.state = t.State.IDLE  # transcription done
    rec.press()  # the next recording, from 30 s
    rec.check(70, recording=0)  # past the first recording's silence stop
    assert t.state == t.State.RECORDING
    rec.check(90, recording=1)
    assert rec.stops == ["beep_stop", "beep_auto_stop"]


def test_both_limits_off_start_no_watchdog(recorder):
    rec = recorder(silence_stop_s=0, max_s=0)
    rec.press()
    assert t.state == t.State.RECORDING and rec.watchdogs == []


def test_the_watchdog_thread_stops_the_recording(recorder, monkeypatch):
    monkeypatch.setattr(t, "AUTOSTOP_CHECK_S", 0.001)
    rec = recorder(threads=True)
    rec.press()
    (thread,) = rec.threads
    rec.now = 60
    assert rec.transcribed.wait(2)
    thread.join(timeout=2)
    assert not thread.is_alive()
    assert rec.stops == ["beep_auto_stop"]


def test_the_watchdog_thread_ends_with_the_recording(recorder):
    rec = recorder(threads=True)  # checks once a second, as in use
    rec.press()
    (thread,) = rec.threads
    rec.press()
    thread.join(timeout=0.5)  # well before its next check
    assert not thread.is_alive()
    assert rec.stops == ["beep_stop"]
