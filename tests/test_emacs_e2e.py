"""End to end: talktype's emacs route against a headless Emacs server.

A throwaway `emacs --fg-daemon` with talktype.el loaded stands in for the
desktop Emacs; nothing touches the desktop session. The server runs with
LC_ALL=C, so umlauts have to arrive through the ASCII escapes.
"""

import argparse
import os
import shutil
import subprocess
import time
from pathlib import Path

import pytest

# CI sets TALKTYPE_REQUIRE_E2E=1: there a missing tool fails the run instead
# of skipping this module unnoticed.
REQUIRED = os.environ.get("TALKTYPE_REQUIRE_E2E") == "1"


def unavailable(reason):
    if REQUIRED:
        pytest.fail(f"{reason} (TALKTYPE_REQUIRE_E2E=1)", pytrace=False)
    pytest.skip(reason, allow_module_level=True)


if not os.environ.get("DISPLAY"):
    unavailable("talktype imports pynput, which needs an X display")
if not (shutil.which("emacs") and shutil.which("emacsclient")):
    unavailable("needs emacs and emacsclient")

import talktype as t  # noqa: E402

REPO = Path(__file__).resolve().parent.parent
BUFFER = "dictation"


@pytest.fixture
def server(tmp_path):
    socket = str(tmp_path / "server")
    env = {**os.environ, "LC_ALL": "C", "LANG": "C"}
    env.pop("DISPLAY", None)
    daemon = subprocess.Popen(
        ["emacs", "-Q", f"--fg-daemon={socket}", "-L", str(REPO), "-l", "talktype"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        env=env,
    )
    try:
        for _ in range(100):
            if Path(socket).exists() and eval_in(socket, "t").returncode == 0:
                break
            time.sleep(0.1)
        else:
            pytest.fail("the Emacs server did not start")
        yield socket
    finally:
        daemon.terminate()
        daemon.wait(timeout=10)


def eval_in(socket, expr):
    return subprocess.run(
        ["emacsclient", "-s", socket, "--eval", expr],
        capture_output=True,
        timeout=10,
    )


def buffer_text(socket, tmp_path):
    out = tmp_path / "buffer.txt"
    done = eval_in(
        socket,
        f'(let ((coding-system-for-write (quote utf-8-unix))) '
        f'(with-current-buffer "{BUFFER}" '
        f'(write-region nil nil "{out}")))',
    )
    assert done.returncode == 0, done.stderr
    return out.read_text(encoding="utf-8")


def open_buffer(socket, content, read_only=False):
    done = eval_in(
        socket,
        f"(progn (switch-to-buffer (get-buffer-create \"{BUFFER}\")) "
        f"(buffer-enable-undo) (insert \"{content}\") (undo-boundary) "
        f"(setq buffer-read-only {'t' if read_only else 'nil'}))",
    )
    assert done.returncode == 0, done.stderr


def use(monkeypatch, socket, output="emacs"):
    config = argparse.Namespace(
        stream_output=output,
        language="en",
        kitten="kitten",
        kitty_socket="unix:@kitty",
        stream_interval=0.01,
        emacsclient=shutil.which("emacsclient"),
        emacs_socket=socket,
        minimal=True,
    )
    monkeypatch.setattr(t, "config", config, raising=False)
    monkeypatch.setattr(t, "audio_chunks", [])


def dictate(socket, chunks):
    session = t.StreamingSession()
    for chunk in chunks:
        session.write(chunk)
        # Commands and undo timers put boundaries between the server calls.
        eval_in(socket, f'(with-current-buffer "{BUFFER}" (undo-boundary))')
    session.stop()
    session.end()
    return session


CHUNKS = [
    " Er sagte \"Hallo\",",
    " C:\\Pfad\\ und \\\"",
    " \") (kill-emacs) (\"",
    " (delete-file \"x\")",
    "\nGrüße aus Köln, ß € 🎤",
]


def test_dictation_arrives_as_text_and_undoes_in_one_step(
    monkeypatch, server, tmp_path
):
    use(monkeypatch, server)
    open_buffer(server, "Diktat:")
    session = dictate(server, CHUNKS)
    assert session.route == "emacs"
    assert buffer_text(server, tmp_path) == "Diktat:" + "".join(CHUNKS)
    assert eval_in(server, "(emacs-pid)").returncode == 0  # still running
    assert eval_in(server, "talktype--overlay").stdout.strip() == b"nil"

    done = eval_in(
        server,
        f'(with-current-buffer "{BUFFER}" (undo-boundary) '
        f"(let ((l buffer-undo-list)) (when (null (car l)) (setq l (cdr l))) "
        f"(primitive-undo 1 l)))",
    )
    assert done.returncode == 0, done.stderr
    assert buffer_text(server, tmp_path) == "Diktat:"


def test_auto_picks_emacs_for_a_frame_of_the_server(monkeypatch, server):
    use(monkeypatch, server, output="auto")
    monkeypatch.setattr(t, "window_is_emacs", lambda w: True)
    monkeypatch.setattr(t, "window_pid", lambda w: int(eval_in(server, "(emacs-pid)").stdout))
    assert t.choose_route() == "emacs"
    monkeypatch.setattr(t, "window_pid", lambda w: 1)
    assert t.choose_route() == "type-or-paste"


def test_read_only_buffer_gets_nothing(monkeypatch, server, tmp_path):
    use(monkeypatch, server)
    monkeypatch.setattr(t, "paste_text", lambda text, **kw: pytest.fail("pasted"))
    beeps = []
    monkeypatch.setattr(t, "beep_error", lambda: beeps.append(1))
    open_buffer(server, "nur lesen", read_only=True)
    session = dictate(server, [" eins"])
    assert session.route == "none"
    assert buffer_text(server, tmp_path) == "nur lesen"
    assert beeps == [1]
    done = eval_in(
        server,
        "(with-current-buffer (messages-buffer) "
        f'(and (search-backward "TalkType: {BUFFER} is read-only" nil t) t))',
    )
    assert done.stdout.strip() == b"t", done.stderr


def test_without_talktype_el_nothing_is_typed(monkeypatch, server, tmp_path):
    use(monkeypatch, server)
    monkeypatch.setattr(t, "paste_text", lambda text, **kw: pytest.fail("pasted"))
    open_buffer(server, "x")
    eval_in(server, "(fmakunbound (quote talktype-begin))")
    session = dictate(server, [" eins"])
    assert session.route == "none"
    assert buffer_text(server, tmp_path) == "x"


def test_replaced_words_arrive_in_emacs(monkeypatch, server, tmp_path):
    use(monkeypatch, server)
    monkeypatch.setattr(
        t, "replacer", t.replacements.Replacer({"onyx": "onnx", "cloud code": "Claude Code"})
    )
    open_buffer(server, "Diktat:")
    session = t.StreamingSession()
    session.type_words(["I", "use", "cloud"])
    session.type_words(["code", "on", "onyx."])
    session.flush()
    session.stop()
    session.end()
    assert session.route == "emacs"
    assert buffer_text(server, tmp_path) == "Diktat: I use Claude Code on onnx."


def press_undo():
    """What the undo key does, in the thread the key starts for it."""
    t.undo_last()


def test_the_undo_key_removes_the_dictation_in_emacs(monkeypatch, server, tmp_path, capsys):
    use(monkeypatch, server)
    monkeypatch.setattr(t, "state", t.State.IDLE)
    monkeypatch.setattr(t, "last_dictation", t.undo.LastDictation())
    monkeypatch.setattr(t, "beep_success", lambda: None)
    monkeypatch.setattr(t, "beep_error", lambda: None)
    open_buffer(server, "Diktat:")
    t.last_dictation.begin()
    dictate(server, [" Grüße", " aus Köln"])
    assert buffer_text(server, tmp_path) == "Diktat: Grüße aus Köln"
    press_undo()
    assert buffer_text(server, tmp_path) == "Diktat:"
    press_undo()
    out = capsys.readouterr().out
    assert "[undo] emacs: removed\n" in out
    assert out.endswith("[undo] nothing to undo\n")


def test_the_undo_key_reports_emacs_refusing(monkeypatch, server, tmp_path, capsys):
    use(monkeypatch, server)
    monkeypatch.setattr(t, "state", t.State.IDLE)
    monkeypatch.setattr(t, "last_dictation", t.undo.LastDictation())
    monkeypatch.setattr(t, "beep_error", lambda: None)
    open_buffer(server, "Diktat:")
    t.last_dictation.begin()
    dictate(server, [" eins"])
    eval_in(server, f'(with-current-buffer "{BUFFER}" (goto-char (point-max)) (insert "!"))')
    eval_in(server, f'(with-current-buffer "{BUFFER}" (goto-char (- (point-max) 2)) (insert "x"))')
    press_undo()
    assert buffer_text(server, tmp_path) == "Diktat: einxs!"
    assert "[undo] refused: the dictation was edited" in capsys.readouterr().out
    press_undo()  # one-shot: an Emacs refusal forgets it too
    assert capsys.readouterr().out.endswith("[undo] nothing to undo\n")


def test_the_undo_key_leaves_a_later_emacs_dictation_alone(monkeypatch, server, tmp_path, capsys):
    use(monkeypatch, server)
    monkeypatch.setattr(t, "state", t.State.IDLE)
    monkeypatch.setattr(t, "last_dictation", t.undo.LastDictation())
    monkeypatch.setattr(t, "beep_error", lambda: None)
    open_buffer(server, "Diktat:")
    t.last_dictation.begin()
    dictate(server, [" hello"])
    # By hand, as README suggests for trying the region: Emacs remembers this one.
    eval_in(server, f'(with-current-buffer "{BUFFER}" (talktype-begin) (talktype-append " notes") (talktype-end))')
    press_undo()
    assert buffer_text(server, tmp_path) == "Diktat: hello notes"
    assert "[undo] refused: the last dictation is another one" in capsys.readouterr().out
