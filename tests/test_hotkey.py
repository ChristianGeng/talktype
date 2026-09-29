from hotkey import PressGate

F10, F11 = "f10", "f11"


def toggles(events):
    """Run key events through a gate and a record/stop toggle, as TalkType does.

    Returns how often recording started and stopped.
    """
    gate, recording, starts, stops = PressGate(), False, 0, 0
    for kind, key in events:
        if kind == "release":
            gate.release(key)
        elif gate.press(key):
            if recording:
                stops += 1
            else:
                starts += 1
            recording = not recording
    return starts, stops


def test_two_taps_start_once_and_stop_once():
    events = [("press", F10), ("release", F10), ("press", F10), ("release", F10)]
    assert toggles(events) == (1, 1)


def test_holding_the_key_does_not_toggle_again():
    # X auto-repeat: after 500 ms, 33 presses per second, no release between.
    held = [("press", F10)] * 25
    events = held + [("release", F10)] + held + [("release", F10)]
    assert toggles(events) == (1, 1)


def test_repeat_is_rejected_until_release():
    gate = PressGate()
    assert gate.press(F10) is True
    assert gate.press(F10) is False
    gate.release(F10)
    assert gate.press(F10) is True


def test_keys_are_independent():
    gate = PressGate()
    assert gate.press(F10) is True
    assert gate.press(F11) is True
    gate.release(F11)
    assert gate.press(F10) is False


def test_release_of_an_unpressed_key_is_harmless():
    gate = PressGate()
    gate.release(F10)
    assert gate.press(F10) is True
