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

if not os.environ.get("DISPLAY"):
    pytest.skip(
        "talktype imports pynput, which needs an X display", allow_module_level=True
    )
if not (shutil.which("emacs") and shutil.which("emacsclient")):
    pytest.skip("needs emacs and emacsclient", allow_module_level=True)

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
    open_buffer(server, "nur lesen", read_only=True)
    session = dictate(server, [" eins"])
    assert session.route == "none"
    assert buffer_text(server, tmp_path) == "nur lesen"


def test_without_talktype_el_nothing_is_typed(monkeypatch, server, tmp_path):
    use(monkeypatch, server)
    monkeypatch.setattr(t, "paste_text", lambda text, **kw: pytest.fail("pasted"))
    open_buffer(server, "x")
    eval_in(server, "(fmakunbound (quote talktype-begin))")
    session = dictate(server, [" eins"])
    assert session.route == "none"
    assert buffer_text(server, tmp_path) == "x"
