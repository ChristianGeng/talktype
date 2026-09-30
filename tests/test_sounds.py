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


def test_all_beeps_by_default():
    assert t.parse_sounds(None) == ALL


def test_true_and_false_switch_all():
    assert t.parse_sounds(True) == ALL
    assert t.parse_sounds(False) == dict.fromkeys(ALL, False)


def test_single_beeps_can_be_switched_off():
    assert t.parse_sounds({"success": False}) == {**ALL, "success": False}


def test_unknown_beep_name_is_rejected():
    with pytest.raises(ValueError, match="sucess"):
        t.parse_sounds({"sucess": False})


def test_sounds_come_from_the_config_file(monkeypatch):
    monkeypatch.setattr(t, "load_config_file", lambda: {"sounds": {"success": False}})
    monkeypatch.setattr(sys, "argv", ["talktype"])
    assert t.parse_args().sounds == {**ALL, "success": False}


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
