"""Why a recording gave no text (#80). No display needed."""

import numpy as np
import pytest

import autostop

RATE = 16000


def tone(seconds, level):
    """A recording whose 50 ms segments all have RMS `level`."""
    return np.full(int(RATE * seconds), level, np.float32)


def test_too_short():
    assert autostop.silence_reason(tone(0.3, 0.2)) == "too short (0.3 s)"


def test_too_quiet_names_the_loudest_segment():
    # 2026-11-16, Razer Kraken: a voice that didn't reach the microphone.
    quiet = tone(3.0, 0.0001)
    quiet[16000:16800] = 0.0004
    assert autostop.silence_reason(quiet) == (
        "too quiet: loudest 0.0004, speech from 0.01 (microphone muted?)"
    )


def test_loud_enough_but_no_words():
    assert autostop.silence_reason(tone(2.0, 0.05)) == (
        "loud enough (loudest 0.0500), but no words heard"
    )


def test_a_two_dimensional_recording_counts_the_same():
    # sounddevice records (n, 1).
    assert autostop.silence_reason(tone(2.0, 0.05).reshape(-1, 1)).startswith(
        "loud enough"
    )


@pytest.mark.parametrize(
    "samples, peak",
    [
        (np.zeros(0, np.float32), 0.0),
        (np.full(300, 0.5, np.float32), 0.0),  # under half a segment: left out
        (np.full(400, 0.5, np.float32), 0.5),  # half a segment: counted
        (np.concatenate([np.zeros(800), np.full(800, 0.3)]).astype(np.float32), 0.3),
    ],
)
def test_peak_level(samples, peak):
    assert autostop.peak_level(samples) == pytest.approx(peak)
