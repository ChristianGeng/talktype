"""A slow microphone start doesn't turn a tap of the record key into a hold.

pynput calls on_press and on_release one after the other on its listener
thread. With a headset that takes 0.5 s to open (Razer Kraken V3 X), the
release of a 0.09 s tap was handled only after the start, so timed from the
press it looked like a hold and stopped the recording on release. A hold is
now timed from when the recording went live.

The tests call the handlers in sequence on one thread, as pynput does, with
a fake clock that the slow stream advances.
"""

import os

import pytest

if not os.environ.get("DISPLAY"):
    pytest.skip(
        "talktype imports pynput, which needs an X display", allow_module_level=True
    )

from test_auto_stop_recording import KEY, FakeStream, recorder  # noqa: F401

import talktype as t

OPENING_S = 0.6  # longer than hold_ms (500)


@pytest.fixture
def slow_recorder(recorder, monkeypatch):  # noqa: F811
    """An auto-mode record key whose microphone takes OPENING_S to open."""
    rec = recorder(mode="auto")
    monkeypatch.setattr(t, "hotkey_clock", lambda: rec.now)

    class SlowStream(FakeStream):
        def start(self):
            rec.now += OPENING_S

    monkeypatch.setattr(t.sd, "InputStream", SlowStream)
    return rec


def test_a_tap_released_right_after_a_slow_start_keeps_recording(slow_recorder):
    rec = slow_recorder
    rec.press(release=False)  # at 0; returns once the stream is open, at 0.6
    assert t.state == t.State.RECORDING and rec.key.held

    rec.now += 0.02  # the queued release of the tap
    rec.on_release(KEY)

    assert t.state == t.State.RECORDING  # the tap toggled: still recording
    assert rec.stops == []
    assert not rec.key.held  # the release reached RecordKey


def test_a_hold_after_a_slow_start_stops_on_release(slow_recorder):
    rec = slow_recorder
    rec.press(release=False)
    rec.now = 2.6  # held for 2 s after recording went live
    rec.on_release(KEY)

    assert rec.stops == ["beep_stop"]
    assert t.state == t.State.TRANSCRIBING
    assert not rec.key.held
    assert rec.transcribed.wait(5)
