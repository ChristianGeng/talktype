"""Hotkey actions are optional: only recording is bound by default."""

import os
import sys

import pytest

if not os.environ.get("DISPLAY"):
    pytest.skip(
        "talktype imports pynput, which needs an X display", allow_module_level=True
    )

import talktype as t  # noqa: E402
from pynput import keyboard  # noqa: E402


@pytest.mark.parametrize("name", [None, "", "none", "None", " null "])
def test_unbound_names_give_no_key(name):
    assert t.get_hotkey(name) is None


def test_key_names_still_resolve():
    assert t.get_hotkey("F10") == keyboard.Key.f10
    assert t.get_hotkey("pause") == keyboard.Key.pause


def test_unknown_key_name_stops():
    with pytest.raises(SystemExit):
        t.get_hotkey("fx9")


def parse(monkeypatch, file_config, argv=()):
    monkeypatch.setattr(t, "load_config_file", lambda: file_config)
    monkeypatch.setattr(sys, "argv", ["talktype", *argv])
    return t.parse_args()


@pytest.mark.parametrize("name", [None, "none"])
def test_unbound_record_key_stops(monkeypatch, name):
    with pytest.raises(SystemExit):
        parse(monkeypatch, {"hotkeys": {"record": name}})


def test_only_recording_is_bound_by_default(monkeypatch):
    config = parse(monkeypatch, {})
    assert config.hotkey == "f9"
    assert config.recovery_hotkey is None
    assert config.retry_hotkey is None


def test_null_in_the_config_file_leaves_an_action_unbound(monkeypatch):
    config = parse(
        monkeypatch, {"hotkeys": {"record": "f10", "recovery": None, "retry": None}}
    )
    assert (config.hotkey, config.recovery_hotkey, config.retry_hotkey) == (
        "f10",
        None,
        None,
    )


def test_existing_configs_keep_their_keys(monkeypatch):
    config = parse(
        monkeypatch, {"hotkeys": {"record": "f10", "recovery": "f11", "retry": "f9"}}
    )
    assert (config.recovery_hotkey, config.retry_hotkey) == ("f11", "f9")


def test_command_line_can_unbind(monkeypatch):
    config = parse(
        monkeypatch, {"hotkeys": {"retry": "f9"}}, ["--retry-hotkey", "none"]
    )
    assert t.get_hotkey(config.retry_hotkey) is None


def test_ready_message_lists_only_bound_keys(monkeypatch):
    assert t.ready_message(parse(monkeypatch, {"hotkeys": {"record": "f10"}})) == (
        "Ready! Press F10 to record."
    )
    both = parse(
        monkeypatch, {"hotkeys": {"record": "f10", "recovery": "f11", "retry": "f9"}}
    )
    assert (
        t.ready_message(both)
        == "Ready! Press F10 to record, F11 to recover, F9 to retry."
    )


def test_record_mode_defaults_to_toggle(monkeypatch):
    config = parse(monkeypatch, {})
    assert (config.record_mode, config.hold_ms) == ("toggle", 500)


def test_record_mode_and_hold_time_come_from_the_config(monkeypatch):
    config = parse(monkeypatch, {"hotkeys": {"record_mode": "auto", "hold_ms": 400}})
    assert (config.record_mode, config.hold_ms) == ("auto", 400)


@pytest.mark.parametrize("hold_ms", [-1, "long", None, True, 0.5])
def test_bad_hold_time_stops(monkeypatch, hold_ms):
    with pytest.raises(SystemExit):
        parse(monkeypatch, {"hotkeys": {"hold_ms": hold_ms}})


def test_zero_hold_time_is_allowed(monkeypatch):
    assert parse(monkeypatch, {"hotkeys": {"hold_ms": 0}}).hold_ms == 0


def test_status_line_names_the_mode(monkeypatch):
    hold = parse(monkeypatch, {"hotkeys": {"record": "f10", "record_mode": "hold"}})
    assert t.record_prompt(hold) == "Hold F10 to talk"


def test_ready_message_names_the_mode(monkeypatch):
    auto = parse(monkeypatch, {"hotkeys": {"record": "f10", "record_mode": "auto"}})
    assert t.ready_message(auto) == "Ready! Tap F10 to record, or hold it to talk."
    hold = parse(monkeypatch, {"hotkeys": {"record": "f10", "record_mode": "hold", "recovery": "f11"}})
    assert t.ready_message(hold) == "Ready! Hold F10 to talk, press F11 to recover."
