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
    monkeypatch.setattr(t, "set_terminal_title", lambda title: None)
    monkeypatch.setattr(t, "show_status", lambda status, detail: calls.append(status))
    return calls


def test_a_written_dictation_reports_done(shown):
    t.report_done(SimpleNamespace(route="kitty"), "hello")
    assert shown == ["success beep", "✅ DONE"]


def test_without_a_session_it_reports_done(shown):
    t.report_done(None, "hello")
    assert shown == ["success beep", "✅ DONE"]


def test_a_refused_dictation_reports_not_written_without_the_success_beep(shown):
    # #54 review: Emacs refused (route none), so the text is only in the history
    t.report_done(SimpleNamespace(route="none"), "hello")
    assert shown == ["⚠️ NOT WRITTEN"]
