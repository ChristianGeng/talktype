"""After a recording: DONE and the success beep only when the text was written."""

import argparse
import os
from types import SimpleNamespace

import pytest

if not os.environ.get("DISPLAY"):
    pytest.skip(
        "talktype imports pynput, which needs an X display", allow_module_level=True
    )

import talktype as t  # noqa: E402


@pytest.fixture
def shown(monkeypatch):
    calls = []
    monkeypatch.setattr(t, "config", argparse.Namespace(sounds=None), raising=False)
    monkeypatch.setattr(t, "beep_success", lambda: calls.append("success beep"))
    monkeypatch.setattr(t, "beep_error", lambda: calls.append("error beep"))
    monkeypatch.setattr(t, "set_terminal_title", lambda title: None)
    monkeypatch.setattr(t, "show_status", lambda status, detail: calls.append(status))
    return calls


def test_a_written_dictation_reports_done(shown):
    t.report_done(SimpleNamespace(route="kitty"), "hello")
    assert shown == ["success beep", "✅ DONE"]


def test_without_a_session_it_reports_done(shown):
    t.report_done(None, "hello")
    assert shown == ["success beep", "✅ DONE"]


def session():
    return SimpleNamespace(route=None, emacs_open=False, error_beeped=False)


def dictate(monkeypatch, route, takes, chunks=(" eins", " zwei")):
    """Write chunks through StreamingSession.write with emacs_call answering takes."""
    answers = iter(takes)
    monkeypatch.setattr(t, "choose_route", lambda: route)
    monkeypatch.setattr(t, "emacs_call", lambda *a: next(answers))
    monkeypatch.setattr(t, "log_stream", lambda line: None)
    live = session()
    for chunk in chunks:
        t.StreamingSession.write(live, chunk)
    return live


def test_without_an_emacs_server_the_error_beep_plays_once(monkeypatch, shown):
    # Devin Review: choose_route() gives "none" and talktype-begin never runs
    monkeypatch.setattr(t, "config", argparse.Namespace(stream_output="emacs", sounds=None))
    monkeypatch.setattr(t, "emacs_server_pid", lambda: None)
    live = session()
    for chunk in (" eins", " zwei"):
        t.StreamingSession.write(live, chunk)
    assert live.route == "none"
    t.report_done(live, "eins zwei")
    assert shown == ["error beep", "⚠️ NOT WRITTEN"]


def test_a_refused_begin_beeps_the_error_once_not_twice(monkeypatch, shown):
    live = dictate(monkeypatch, "emacs", [False])
    t.report_done(live, "eins zwei")
    assert shown == ["error beep", "⚠️ NOT WRITTEN"]


def test_a_session_without_the_flag_still_gets_the_error_beep(shown):
    t.report_done(SimpleNamespace(route="none"), "hello")
    assert shown == ["error beep", "⚠️ NOT WRITTEN"]
