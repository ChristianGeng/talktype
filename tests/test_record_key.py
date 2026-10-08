"""What a press or a release of the record key does, per mode."""

import pytest

from hotkey import RecordKey

HOLD = 0.5


def run(mode, events):
    """Feed (kind, time) events; return the actions taken, tracking the state."""
    key, recording, actions = RecordKey(mode, HOLD), False, []
    for kind, now in events:
        action = (
            key.press(now, recording)
            if kind == "press"
            else key.release(now, recording)
        )
        if action:
            actions.append(action)
            recording = action == "start"
    return actions


TAP_TAP = [("press", 0.0), ("release", 0.1), ("press", 3.0), ("release", 3.1)]
HOLD_1S = [("press", 0.0), ("release", 1.0)]


def test_toggle_starts_and_stops_on_presses():
    assert run("toggle", TAP_TAP) == ["start", "stop"]


def test_toggle_ignores_a_long_hold():
    assert run("toggle", HOLD_1S) == ["start"]


def test_hold_stops_on_release():
    assert run("hold", HOLD_1S) == ["start", "stop"]


def test_hold_stops_even_after_a_short_press():
    assert run("hold", [("press", 0.0), ("release", 0.1)]) == ["start", "stop"]


def test_auto_tap_keeps_recording_until_the_next_press():
    assert run("auto", TAP_TAP) == ["start", "stop"]


def test_auto_long_hold_stops_on_release():
    assert run("auto", HOLD_1S) == ["start", "stop"]


def test_auto_threshold_is_inclusive():
    assert run("auto", [("press", 0.0), ("release", HOLD)]) == ["start", "stop"]


@pytest.mark.parametrize("mode", ["toggle", "hold", "auto"])
def test_release_after_the_stopping_press_does_nothing(mode):
    # tap to start, then a long press to stop: its release must not restart
    events = [("press", 0.0), ("release", 0.1), ("press", 2.0), ("release", 3.0)]
    expected = (
        ["start", "stop"] if mode != "hold" else ["start", "stop", "start", "stop"]
    )
    assert run(mode, events) == expected


def test_unknown_mode_is_rejected():
    with pytest.raises(ValueError):
        RecordKey("sometimes", HOLD)


@pytest.mark.parametrize("mode", ["toggle", "hold", "auto"])
def test_the_key_is_held_from_its_press_to_its_release(mode):
    key = RecordKey(mode, HOLD)
    assert not key.held
    key.press(0.0, recording=False)
    assert key.held
    key.release(0.1, recording=True)
    assert not key.held
    key.press(5.0, recording=True)
    assert key.held
    key.release(5.1, recording=False)
    assert not key.held


@pytest.mark.parametrize("mode", ["hold", "auto"])
def test_holding_the_key_is_talking_in_hold_and_auto(mode):
    key = RecordKey(mode, HOLD)
    key.press(0.0, recording=False)
    assert key.talking
    key.release(0.1, recording=True)
    assert not key.talking


def test_holding_a_toggle_key_is_not_talking():
    key = RecordKey("toggle", HOLD)
    key.press(0.0, recording=False)
    assert key.held and not key.talking


SLOW, FAST = 0.6, 0.01  # when recording went live after the press at 0


def tap_or_hold(mode, started, released):
    """Press at 0, recording live at `started`; what the release does."""
    key = RecordKey(mode, HOLD)
    assert key.press(0.0, recording=False) == "start"
    key.started(started)
    return key.release(released, recording=True)


@pytest.mark.parametrize("started", [SLOW, FAST])
def test_auto_tap_is_timed_from_the_recording_start(started):
    # the listener handles the release right after the start returns
    assert tap_or_hold("auto", started, started + 0.02) is None


@pytest.mark.parametrize("started", [SLOW, FAST])
def test_auto_hold_of_2s_stops_on_release(started):
    assert tap_or_hold("auto", started, 2.0) == "stop"


def test_auto_slow_start_tap_released_at_0_62_keeps_recording():
    # 0.62 s after the press, but only 0.02 s after the slow start
    assert tap_or_hold("auto", SLOW, 0.62) is None


def test_auto_fast_start_release_at_0_62_is_a_hold():
    assert tap_or_hold("auto", FAST, 0.62) == "stop"


@pytest.mark.parametrize("started", [SLOW, FAST])
@pytest.mark.parametrize("released", [0.62, 2.0])
def test_hold_and_toggle_ignore_the_recording_start(started, released):
    assert tap_or_hold("hold", started, released) == "stop"
    assert tap_or_hold("toggle", started, released) is None


def test_started_without_a_starting_press_does_nothing():
    # a stopping press, then a late started(): its release must not stop again
    key = RecordKey("auto", HOLD)
    assert key.press(0.0, recording=True) == "stop"
    key.started(0.6)
    assert key.release(2.0, recording=False) is None
