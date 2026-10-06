"""Each feedback beep can be switched off in the config."""

import argparse
import os
import sys

import pytest

if not os.environ.get("DISPLAY"):
    pytest.skip(
        "talktype imports pynput, which needs an X display", allow_module_level=True
    )

import talktype as t  # noqa: E402

ALL = {"start": True, "stop": True, "success": True, "error": True}


DEFAULT = {**ALL, "success": False}


def test_default_is_one_beep_to_start_and_one_to_stop():
    assert t.parse_sounds(None) == DEFAULT


def test_true_and_false_switch_all():
    assert t.parse_sounds(True) == ALL
    assert t.parse_sounds(False) == dict.fromkeys(ALL, False)


def test_single_beeps_keep_the_other_defaults():
    assert t.parse_sounds({"error": False}) == {**DEFAULT, "error": False}
    assert t.parse_sounds({"success": True}) == ALL


def test_unknown_beep_name_is_rejected():
    with pytest.raises(ValueError, match="sucess"):
        t.parse_sounds({"sucess": False})


@pytest.mark.parametrize("value", [["success"], "success", 1])
def test_a_value_that_is_not_a_mapping_is_rejected(value):
    with pytest.raises(ValueError, match="mapping"):
        t.parse_sounds(value)


def test_sounds_come_from_the_config_file(monkeypatch):
    monkeypatch.setattr(t, "load_config_file", lambda: {"sounds": {"success": True}})
    monkeypatch.setattr(sys, "argv", ["talktype"])
    assert t.parse_args().sounds == ALL
    monkeypatch.setattr(t, "load_config_file", lambda: {})
    assert t.parse_args().sounds == DEFAULT


@pytest.mark.parametrize("name", list(ALL))
def test_a_switched_off_beep_stays_silent(monkeypatch, name):
    played = []
    monkeypatch.setattr(t, "beep", lambda *a, **k: played.append(a))
    monkeypatch.setattr(
        t, "config", argparse.Namespace(sounds={**ALL, name: False}), raising=False
    )
    getattr(t, f"beep_{name}")()
    assert played == []
    others = [n for n in ALL if n != name]
    for other in others:
        getattr(t, f"beep_{other}")()
    assert len(played) == len(others)


def test_a_beep_fades_in_and_out_and_keeps_its_length():
    import numpy as np

    wave = t.beep_wave(440, 0.12)
    n = int(t.SAMPLE_RATE * 0.12)
    assert len(wave) == n
    time = np.linspace(0, 0.12, n, False)
    raw = 0.12 * np.sin(2 * np.pi * 440 * time)
    fade = int(t.SAMPLE_RATE * t.BEEP_FADE_S)
    ramp = np.linspace(0.0, 1.0, fade, endpoint=False)
    assert np.allclose(wave[:fade], raw[:fade] * ramp, atol=1e-6)
    assert np.allclose(wave[-fade:], raw[-fade:] * ramp[::-1], atol=1e-6)
    assert np.allclose(wave[fade:-fade], raw[fade:-fade], atol=1e-6)


def test_only_the_stop_beep_asks_for_high_latency(monkeypatch):
    calls = []
    monkeypatch.setattr(t.sd, "play", lambda wave, rate, **kw: calls.append(kw["latency"]))
    monkeypatch.setattr(t, "config", argparse.Namespace(sounds=ALL), raising=False)
    t.beep_start()
    t.beep_stop()
    t.beep_error()
    assert calls == ["low", "high", "low"]


def test_each_beep_is_logged_by_name_unless_off(monkeypatch, capsys):
    monkeypatch.setattr(t, "beep", lambda *a, **k: True)
    monkeypatch.setattr(
        t, "config", argparse.Namespace(sounds={**ALL, "error": False}), raising=False
    )
    t.beep_stop()
    t.beep_error()
    out = capsys.readouterr().out
    assert "[stream] beep stop" in out
    assert "beep error" not in out


def test_a_beep_that_failed_is_logged_as_such(monkeypatch, capsys):
    def broken(*a, **k):
        raise OSError("no audio device")

    monkeypatch.setattr(t.sd, "play", broken)
    monkeypatch.setattr(t, "config", argparse.Namespace(sounds=ALL), raising=False)
    t.beep_stop()
    assert "[stream] beep stop failed to play" in capsys.readouterr().out


def test_a_closed_stdout_does_not_break_a_beep(monkeypatch):
    monkeypatch.setattr(t, "beep", lambda *a, **k: True)
    monkeypatch.setattr(t, "config", argparse.Namespace(sounds=ALL), raising=False)

    def closed(message):
        raise BrokenPipeError

    monkeypatch.setattr(t, "log_stream", closed)
    t.beep_stop()  # must not raise
