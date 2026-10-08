"""The undo key end to end through talktype (#60), with fake commands.

kitten and emacsclient are small shell scripts that record their arguments
and answer as kitty and Emacs would, so the real subprocess calls run; no
real kitty or Emacs is involved (tests/test_emacs_e2e.py uses a real Emacs).
"""

import argparse
import json
import os
import stat
import threading

import pytest

if not os.environ.get("DISPLAY"):
    pytest.skip(
        "talktype imports pynput, which needs an X display", allow_module_level=True
    )

from pynput import keyboard

import talktype as t

SOCKET = "unix:@kitty"
X_WINDOW = b"4711"
UNDO_KEY = keyboard.Key.pause


def ls_reply(window_id):
    return json.dumps([{"is_focused": True, "tabs": [{"is_focused": True, "windows": [
        {"id": 3, "is_focused": False, "foreground_processes": []},
        {"id": window_id, "is_focused": True, "foreground_processes": []},
    ]}]}])


def fake_command(path, log, reply="", status=0, error=""):
    """A command that logs its arguments, NUL-separated, one call per line.

    It exits with the status in path.status, which a test may change.
    """
    path.write_text(
        "#!/bin/sh\n"
        f"printf '%s\\0' \"$@\" >> '{log}'\n"
        f"printf '\\n' >> '{log}'\n"
        f"[ \"$4\" = ls ] && cat '{path}.reply'\n"
        f"[ -n '{error}' ] && printf '%s' '{error}' >&2\n"
        f"exit $(cat '{path}.status')\n"
    )
    (path.parent / f"{path.name}.reply").write_text(reply)
    (path.parent / f"{path.name}.status").write_text(str(status))
    path.chmod(path.stat().st_mode | stat.S_IEXEC)


def calls(log):
    if not log.exists():
        return []
    return [line.split("\0")[:-1] for line in log.read_text().split("\n") if line]


@pytest.fixture
def env(monkeypatch, tmp_path):
    kitten, emacsclient = tmp_path / "kitten", tmp_path / "emacsclient"
    logs = SimpleLogs(tmp_path)
    fake_command(kitten, logs.kitten, reply=ls_reply(9))
    fake_command(emacsclient, logs.emacs)
    config = argparse.Namespace(
        stream_output="auto", language="en", kitten=str(kitten), kitty_socket=SOCKET,
        stream_interval=0.01, emacsclient=str(emacsclient), emacs_socket=None,
        minimal=True, undo_hotkey="pause", sounds=None,
        silence_stop_s=0, max_s=0, stream=False, record_mode="toggle", hold_ms=0,
    )
    monkeypatch.setattr(t, "config", config, raising=False)
    monkeypatch.setattr(t, "state", t.State.IDLE)
    monkeypatch.setattr(t, "last_dictation", t.undo.LastDictation())
    monkeypatch.setattr(t, "get_active_window", lambda: X_WINDOW)
    monkeypatch.setattr(t, "audio_chunks", [])
    monkeypatch.setattr(t.sd, "InputStream", FakeStream)
    for ui in ("beep_start", "set_terminal_title", "show_status"):
        monkeypatch.setattr(t, ui, lambda *a, **kw: None)
    beeps = []
    monkeypatch.setattr(t, "beep_error", lambda: beeps.append("error"))
    monkeypatch.setattr(t, "beep_success", lambda: beeps.append("success"))
    logs.beeps = beeps
    logs.kitten_path, logs.emacs_path = kitten, emacsclient
    return logs


class FakeStream:
    """sd.InputStream without a microphone."""

    def __init__(self, **kwargs):
        pass

    def start(self):
        pass


class SimpleLogs:
    def __init__(self, tmp_path):
        self.kitten = tmp_path / "kitten.log"
        self.emacs = tmp_path / "emacsclient.log"


def dictate(monkeypatch, route, chunks):
    """A recording whose streamed chunks go by route."""
    t.start_recording()
    monkeypatch.setattr(t, "choose_route", lambda: route)
    session = t.StreamingSession()
    for chunk in chunks:
        session.write(chunk)
    session.stop()
    session.end()
    return session


def press_undo(on_press=None):
    """Press the undo key and wait for the undo thread it starts."""
    started = []
    real_thread = threading.Thread

    def thread(*args, **kwargs):
        started.append(real_thread(*args, **kwargs))
        return started[-1]

    t.threading.Thread = thread
    try:
        (on_press or t.create_undo_handler(UNDO_KEY))(UNDO_KEY)
    finally:
        t.threading.Thread = real_thread
    for worker in started:
        worker.join(timeout=10)
    return len(started)


def test_kitty_undo_sends_one_del_per_character_into_the_same_window(
    monkeypatch, env, capsys
):
    dictate(monkeypatch, "kitty", [" Grüße", " aus Köln"])
    assert press_undo() == 1
    sent = calls(env.kitten)
    assert sent[0] == ["@", "--to", SOCKET, "ls"]  # the window id, when the route was chosen
    assert sent[1][-2:] == ["--", " Grüße"]
    assert sent[-1] == ["@", "--to", SOCKET, "send-text", "--match", "id:9", "--", "\x7f" * len(" Grüße aus Köln")]
    out = capsys.readouterr().out
    assert "[undo] kitty: removed 15 chars" in out
    assert env.beeps == ["success"]


def test_kitty_undo_works_once(monkeypatch, env, capsys):
    dictate(monkeypatch, "kitty", [" eins"])
    press_undo()
    press_undo()
    assert sum(c[3] == "send-text" and c[-1].startswith("\x7f") for c in calls(env.kitten)) == 1
    assert capsys.readouterr().out.endswith("[undo] nothing to undo\n")


def test_kitty_undo_refuses_after_the_focus_moved(monkeypatch, env, capsys):
    dictate(monkeypatch, "kitty", [" eins"])
    (env.kitten_path.parent / "kitten.reply").write_text(ls_reply(3))  # another kitty window
    press_undo()
    assert not any(c[-1].startswith("\x7f") for c in calls(env.kitten))
    assert "[undo] refused: another window has the focus" in capsys.readouterr().out
    assert env.beeps == ["error"]


def test_kitty_undo_refuses_after_another_key(monkeypatch, env, capsys):
    dictate(monkeypatch, "kitty", [" eins"])
    count = t.create_key_counter((keyboard.Key.f9, None, None, UNDO_KEY))
    for key in (keyboard.Key.f9, UNDO_KEY, keyboard.KeyCode.from_vk(t.FN_KEYSYM)):
        count(key)  # TalkType's own keys and Fn don't count
    press_undo()
    assert "[undo] kitty: removed 5 chars" in capsys.readouterr().out
    dictate(monkeypatch, "kitty", [" zwei"])
    count(keyboard.Key.left)
    press_undo()
    assert "[undo] refused: a key was pressed since the dictation" in capsys.readouterr().out


def test_kitty_undo_refuses_a_line_break(monkeypatch, env, capsys):
    dictate(monkeypatch, "kitty", [" eins", "\nzwei"])
    press_undo()
    assert "[undo] refused: the dictation has a line break" in capsys.readouterr().out


def test_emacs_undo_calls_talktype_undo_last(monkeypatch, env, capsys):
    dictate(monkeypatch, "emacs", [" eins"])
    press_undo()
    evals = [c[-1] for c in calls(env.emacs)]
    assert evals == ["(talktype-begin)", '(talktype-append " eins")', "(talktype-end)",
                     '(talktype-undo-last " eins")']
    assert "[undo] emacs: removed" in capsys.readouterr().out


def test_emacs_refusal_is_logged_as_emacs_says_it(monkeypatch, env, capsys):
    dictate(monkeypatch, "emacs", [" eins"])
    fake_command(env.emacs_path, env.emacs, status=1,
                 error="*ERROR*: TalkType: the dictation was edited")
    press_undo()
    assert "[undo] refused: the dictation was edited" in capsys.readouterr().out
    assert env.beeps == ["error"]


@pytest.mark.parametrize("route", ["terminal-paste", "type"])
def test_other_routes_do_nothing(monkeypatch, env, capsys, route):
    monkeypatch.setattr(t, "paste_into_terminal", lambda text: None)
    run = t.subprocess.run
    monkeypatch.setattr(t.subprocess, "run", lambda *a, **kw: None)  # xdotool
    dictate(monkeypatch, route, [" eins"])
    monkeypatch.setattr(t.subprocess, "run", run)  # the real one, for the undo
    press_undo()
    assert calls(env.kitten) == [] and calls(env.emacs) == []
    assert f"[undo] not supported for route {route}" in capsys.readouterr().out


def test_nothing_happens_while_recording(monkeypatch, env, capsys):
    dictate(monkeypatch, "kitty", [" eins"])
    monkeypatch.setattr(t, "state", t.State.RECORDING)
    before = calls(env.kitten)
    press_undo()
    assert calls(env.kitten) == before
    assert env.beeps == []
    assert "[undo] ignored: recording or transcribing" in capsys.readouterr().out


def test_the_undo_key_does_not_run_in_the_listener_thread(monkeypatch, env):
    ran_in = []
    monkeypatch.setattr(t, "undo_last", lambda: ran_in.append(threading.current_thread()))
    press_undo()
    assert ran_in and ran_in[0] is not threading.current_thread()


def test_other_keys_do_not_undo(monkeypatch, env):
    handler = t.create_undo_handler(UNDO_KEY)
    monkeypatch.setattr(t, "undo_last", lambda: pytest.fail("undid"))
    handler(keyboard.Key.f9)
    t.create_undo_handler(None)(UNDO_KEY)


def test_every_kitty_chunk_goes_to_the_window_of_the_first(monkeypatch, env):
    t.config.undo_hotkey = None  # pinned whether or not an undo key is bound
    dictate(monkeypatch, "kitty", [" eins", " zwei", " drei"])
    sends = [c for c in calls(env.kitten) if c[3] == "send-text"]
    assert [c[4:7] for c in sends] == [["--match", "id:9", "--"]] * 3
    assert [c[1:3] for c in sends] == [["--to", SOCKET]] * 3


def test_a_kitty_window_that_went_away_is_not_undone(monkeypatch, env, capsys):
    pasted = []
    monkeypatch.setattr(t, "paste_text", lambda text, **kw: pasted.append(text))
    t.last_dictation.begin()
    monkeypatch.setattr(t, "choose_route", lambda: "kitty")
    session = t.StreamingSession()
    session.write(" eins")
    (env.kitten_path.parent / "kitten.status").write_text("1")  # window closed
    session.write(" zwei")
    session.stop()
    assert pasted == [" zwei"]
    (env.kitten_path.parent / "kitten.status").write_text("0")
    press_undo()
    assert not any(c[-1].startswith("\x7f") for c in calls(env.kitten))
    assert "[undo] refused: the dictation took several routes (kitty, paste)" in capsys.readouterr().out


def test_the_whole_undo_holds_state_lock(monkeypatch, env):
    # A recording can't start halfway through: start_recording runs under state_lock.
    held = []
    run = t.subprocess.run

    def checking_run(cmd, **kw):
        held.append(t.state_lock.locked())
        return run(cmd, **kw)

    dictate(monkeypatch, "kitty", [" eins"])
    monkeypatch.setattr(t.subprocess, "run", checking_run)
    press_undo()
    assert len(held) == 2 and all(held)  # kitten @ ls, then the DELs
    dictate(monkeypatch, "emacs", [" zwei"])
    held.clear()
    press_undo()
    assert held == [True]


def test_the_undo_calls_time_out_after_a_second(monkeypatch, env):
    timeouts = []
    run = t.subprocess.run

    def timed_run(cmd, **kw):
        if cmd[-1] == "ls" or cmd[-1].startswith(("(talktype-undo-last", "\x7f")):
            timeouts.append(kw["timeout"])
        return run(cmd, **kw)

    dictate(monkeypatch, "kitty", [" eins"])
    timeouts.clear()
    monkeypatch.setattr(t.subprocess, "run", timed_run)
    press_undo()
    dictate(monkeypatch, "emacs", [" zwei"])
    press_undo()
    assert timeouts == [1, 1, 1]


def test_a_key_pressed_while_the_undo_checks_the_focus_refuses(monkeypatch, env, capsys):
    # The key count is checked again after the focus lookup, right before the DELs.
    dictate(monkeypatch, "kitty", [" eins"])
    count = t.create_key_counter((UNDO_KEY,))
    window = t.kitty_window

    def typing_meanwhile(*args):
        count(keyboard.KeyCode.from_char("x"))
        return window(*args)

    monkeypatch.setattr(t, "kitty_window", typing_meanwhile)
    press_undo()
    assert not any(c[-1].startswith("\x7f") for c in calls(env.kitten))
    assert "[undo] refused: a key was pressed since the dictation" in capsys.readouterr().out


def test_a_failed_kitty_removal_is_not_retried(monkeypatch, env, capsys):
    dictate(monkeypatch, "kitty", [" eins"])
    (env.kitten_path.parent / "kitten.status").write_text("1")
    press_undo()
    press_undo()
    dels = [c for c in calls(env.kitten) if c[-1].startswith("\x7f")]
    assert len(dels) == 1
    out = capsys.readouterr().out
    assert "[undo] failed, not retried: kitty send-text failed (exit 1)" in out
    assert out.endswith("[undo] nothing to undo\n")


def test_an_emacsclient_that_times_out_is_not_retried(monkeypatch, env, capsys):
    dictate(monkeypatch, "emacs", [" eins"])
    run = t.subprocess.run

    def slow_emacs(cmd, **kw):
        if cmd[-1].startswith("(talktype-undo-last"):
            raise t.subprocess.TimeoutExpired(cmd, kw["timeout"])
        return run(cmd, **kw)

    monkeypatch.setattr(t.subprocess, "run", slow_emacs)
    press_undo()
    press_undo()
    out = capsys.readouterr().out
    assert "[undo] failed, not retried: emacsclient could not run or timed out" in out
    assert out.endswith("[undo] nothing to undo\n")


def test_a_new_recording_forgets_the_last_dictation(monkeypatch, env, capsys):
    dictate(monkeypatch, "kitty", [" eins"])
    t.start_recording()
    press_undo()
    assert not any(c[-1].startswith("\x7f") for c in calls(env.kitten))
    assert capsys.readouterr().out.endswith("[undo] nothing to undo\n")


def test_the_key_listener_counts_keys_for_the_undo(monkeypatch, env, capsys):
    on_press, on_release = t.create_listener_handlers(keyboard.Key.f9, None, None, UNDO_KEY)
    dictate(monkeypatch, "kitty", [" eins"])
    on_press(keyboard.KeyCode.from_char("x"))
    on_release(keyboard.KeyCode.from_char("x"))
    assert press_undo(on_press) == 1
    assert not any(c[-1].startswith("\x7f") for c in calls(env.kitten))
    assert "[undo] refused: a key was pressed since the dictation" in capsys.readouterr().out


def test_the_key_listener_does_not_count_its_own_keys(monkeypatch, env, capsys):
    on_press, _ = t.create_listener_handlers(keyboard.Key.f9, None, None, UNDO_KEY)
    dictate(monkeypatch, "kitty", [" eins"])
    assert press_undo(on_press) == 1
    assert calls(env.kitten)[-1][-1] == "\x7f" * len(" eins")
