"""When a recording stops by itself: silence, maximum length, held key."""

import numpy as np
import pytest

from autostop import AutoStop, LoudnessMeter

RATE = 16000


def run(auto, speech=(), until=700, held=lambda now: False):
    """Check once a second on a fake clock; return (time, verdict) pairs up to the stop."""
    verdicts = []
    for now in range(1, until + 1):
        if now in speech:
            auto.heard(now)
        verdict = auto.check(now, held(now))
        if verdict:
            verdicts.append((now, verdict))
            if verdict.startswith("stop"):
                break
    return verdicts


def test_silence_for_60_s_stops_after_a_warning_at_50_s():
    assert run(AutoStop(60, 600)) == [(50, "warn"), (60, "stop-silence")]


def test_speech_at_55_s_resets_the_timer():
    verdicts = run(AutoStop(60, 600), speech={55})
    assert (60, "stop-silence") not in verdicts
    assert verdicts == [(50, "warn"), (105, "warn"), (115, "stop-silence")]


def test_the_warning_plays_once_per_silence():
    verdicts = run(AutoStop(60, 600), until=59)
    assert verdicts == [(50, "warn")]


def test_steady_speech_runs_into_the_maximum_length():
    verdicts = run(AutoStop(60, 600), speech=set(range(1, 701, 5)))
    assert verdicts == [(600, "stop-max")]


def test_a_held_key_prevents_the_silence_stop_but_not_the_maximum():
    assert run(AutoStop(60, 600), held=lambda now: True) == [(600, "stop-max")]


def test_releasing_the_key_lets_the_silence_stop_again():
    verdicts = run(AutoStop(60, 600), held=lambda now: now < 100)
    assert verdicts == [(100, "stop-silence")]


def test_zero_turns_the_silence_stop_and_its_warning_off():
    assert run(AutoStop(0, 600)) == [(600, "stop-max")]


def test_zero_turns_the_maximum_length_off():
    speech = set(range(1, 2001, 5))
    assert run(AutoStop(60, 0), speech=speech, until=2000) == []


def test_both_off_never_stops():
    assert run(AutoStop(0, 0), until=2000) == []


def test_the_warning_comes_10_s_before_the_stop():
    assert run(AutoStop(30, 600)) == [(20, "warn"), (30, "stop-silence")]


def test_a_short_silence_stop_has_no_warning():
    assert run(AutoStop(10, 600)) == [(10, "stop-silence")]


def test_the_clock_starts_at_the_start_of_the_recording():
    auto = AutoStop(60, 600, now=1000)
    assert auto.check(1049) is None
    assert auto.check(1060) == "stop-silence"


def test_the_log_names_the_limit():
    auto = AutoStop(60, 600)
    assert auto.describe("stop-silence") == "silence 60 s"
    assert auto.describe("stop-max") == "max length 600 s"


def tone(seconds, amplitude):
    t = np.arange(int(RATE * seconds)) / RATE
    return (amplitude * np.sin(2 * np.pi * 220 * t)).astype(np.float32)


def heard(audio, frames):
    """Feed audio to a LoudnessMeter in blocks; True if any block counted as speech."""
    meter = LoudnessMeter(RATE)
    return any(
        meter.feed(audio[i:i + frames].reshape(-1, 1)) for i in range(0, len(audio), frames)
    )


@pytest.mark.parametrize("frames", [256, 512, 1024, 8000])
def test_silence_and_quiet_noise_are_not_speech(frames):
    rng = np.random.default_rng(0)
    assert not heard(np.zeros(RATE, np.float32), frames)
    assert not heard(rng.normal(0, 0.005, RATE).astype(np.float32), frames)


@pytest.mark.parametrize("frames", [256, 512, 1024, 8000])
def test_speech_is_heard_whatever_the_block_size(frames):
    assert heard(tone(0.1, 0.1), frames)


def test_one_loud_50_ms_segment_is_enough():
    audio = np.zeros(RATE, np.float32)
    audio[8000:8800] = tone(0.05, 0.1)
    assert heard(audio, 1024)


def test_speech_across_a_block_boundary_is_heard():
    audio = np.zeros(2048, np.float32)
    audio[640:1440] = 0.013  # 640 samples in the 800-1599 segment, as has_speech() sees it
    meter = LoudnessMeter(RATE)
    assert not meter.feed(audio[:1024])  # its segment isn't complete yet
    assert meter.feed(audio[1024:])


def test_segments_run_from_the_start_of_the_recording():
    meter = LoudnessMeter(RATE)
    meter.feed(np.zeros(500, np.float32))
    block = np.zeros(800, np.float32)
    block[:300] = 0.015  # ends segment 0-799 at 0.0092 RMS
    block[300:] = 0.006  # 0.0103 RMS if the block were a segment of its own
    assert not meter.feed(block)
