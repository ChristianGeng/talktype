"""A tap whose release arrives while recording is still starting keeps recording.

With a headset that takes 0.5 s to open, the release of a short tap waited
for state_lock while the press started recording. The release was timed
after that wait, so a 0.09 s tap looked like a 0.5 s hold and stopped the
recording on release (2026-10-08, Razer Kraken V3 X).
"""

import os
import threading

import pytest

if not os.environ.get("DISPLAY"):
    pytest.skip(
        "talktype imports pynput, which needs an X display", allow_module_level=True
    )

from test_auto_stop_recording import KEY, FakeStream, recorder  # noqa: E402,F401

import talktype as t  # noqa: E402


class SlowStream(FakeStream):
    """Opening the microphone takes a while, as with some USB headsets."""

    opening = threading.Event()
    go_on = threading.Event()

    def start(self):
        SlowStream.opening.set()
        assert SlowStream.go_on.wait(5)


def test_a_tap_released_while_recording_starts_keeps_recording(recorder, monkeypatch):
    rec = recorder(mode="auto")  # hold_s 0.5: a tap toggles, a hold stops on release
    SlowStream.opening.clear()
    SlowStream.go_on.clear()
    monkeypatch.setattr(t.sd, "InputStream", SlowStream)
    monkeypatch.setattr(t, "_last_hotkey_time", 0.0)

    clock = [0.0]
    reads = []
    read_twice = threading.Event()

    def fake_clock():
        reads.append(clock[0])
        if len(reads) == 2:
            read_twice.set()
        return clock[0]

    monkeypatch.setattr(t, "hotkey_clock", fake_clock)

    press = threading.Thread(target=rec.on_press, args=(KEY,))
    press.start()  # reads 0.0, then holds state_lock while the stream opens
    assert SlowStream.opening.wait(5)

    clock[0] = 0.09  # the key comes up after a short tap
    release = threading.Thread(target=rec.on_release, args=(KEY,))
    release.start()  # must read the clock now, before waiting for state_lock
    assert read_twice.wait(5)

    clock[0] = 0.6  # the stream took 0.6 s to open
    SlowStream.go_on.set()
    press.join(5)
    release.join(5)

    assert reads == [0.0, 0.09]
    assert t.state == t.State.RECORDING  # the tap toggled: still recording
    assert rec.stops == []
