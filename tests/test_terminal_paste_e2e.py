"""End to end: the terminal-paste route into a real VTE terminal (sakura).

sakura runs on the test's X display (Xvfb in CI) with a small program that
turns on bracketed paste and logs every read from the terminal with its
time. TalkType chooses the route from the real window and pastes through
the real clipboard (xclip) and xdotool, while a fake Nemotron stream
delivers a chunk every 560 ms, as the model does while you speak.

This measures the caveat of #41: per-chunk pasting blocked kitty until
the recording stopped. Here every chunk has to reach the program before
the next one is pasted, and a key typed afterwards has to arrive at once.
"""

import argparse
import os
import shutil
import subprocess
import sys
import time

import numpy as np
import pytest

if not os.environ.get("DISPLAY"):
    pytest.skip(
        "talktype imports pynput, which needs an X display", allow_module_level=True
    )
if not all(shutil.which(c) for c in ("sakura", "xdotool", "xclip", "xprop")):
    pytest.skip("needs sakura, xdotool, xclip and xprop", allow_module_level=True)

import replacements  # noqa: E402
import talktype as t  # noqa: E402

CHUNKS = [" Grüße aus", " Köln, wie", " geht's dir", " heute?"]
CHUNK_SECONDS = 0.56

CAPTURE = r"""
import os, sys, time, tty
log = open(sys.argv[1], "ab", buffering=0)
tty.setraw(0)
os.write(1, b"\x1b[?2004h")  # bracketed paste, as Claude Code and shells use
open(sys.argv[2], "w").close()
while True:
    data = os.read(0, 4096)
    if not data:
        break
    log.write(b"%.3f %s\n" % (time.monotonic(), data.hex().encode()))
"""


def reads(log):
    """(time, bytes) for each read the program in the terminal made."""
    if not log.exists():
        return []
    return [
        (float(when), bytes.fromhex(data))
        for when, data in (line.split() for line in log.read_text().splitlines())
    ]


def wait_for(condition, seconds=10):
    deadline = time.monotonic() + seconds
    while not condition():
        assert time.monotonic() < deadline, "timed out"
        time.sleep(0.02)


@pytest.fixture
def terminal(tmp_path):
    script, log, ready = tmp_path / "capture.py", tmp_path / "reads.log", tmp_path / "ready"
    script.write_text(CAPTURE)
    env = {**os.environ, "XDG_CONFIG_HOME": str(tmp_path / "config")}
    sakura = subprocess.Popen(
        ["sakura", "-x", f"{sys.executable} {script} {log} {ready}"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        env=env,
    )
    try:
        wait_for(ready.exists, 20)
        window = subprocess.check_output(
            ["xdotool", "search", "--sync", "--pid", str(sakura.pid)], timeout=20
        ).split()[-1]
        # No window manager on Xvfb: give the window the input focus directly.
        subprocess.run(["xdotool", "windowfocus", "--sync", window], check=True, timeout=10)
        yield window, log
    finally:
        sakura.terminate()
        sakura.wait(timeout=10)


class ChunkStream:
    """Fake nemotron.Stream: one chunk of text per audio chunk fed."""

    def __init__(self, engine, language):
        self.chunks = list(CHUNKS)

    def feed(self, audio):
        return self.chunks.pop(0) if self.chunks else ""

    def flush(self):
        return ""


def test_streamed_chunks_reach_a_vte_terminal_while_speaking(monkeypatch, terminal):
    window, log = terminal
    config = argparse.Namespace(
        stream_output="auto", language="de", kitten="kitten",
        kitty_socket="unix:@kitty", emacsclient="emacsclient", emacs_socket=None,
    )
    monkeypatch.setattr(t, "config", config, raising=False)
    monkeypatch.setattr(t, "target_window", window)
    monkeypatch.setattr(t, "replacer", replacements.Replacer({}))
    monkeypatch.setattr(t, "audio_chunks", [])
    monkeypatch.setattr(t, "nemotron_engine", object(), raising=False)
    monkeypatch.setattr(t.nemotron, "Stream", ChunkStream)
    monkeypatch.setattr(t, "show_status", lambda *a, **k: None)
    pasted = []
    paste = t.paste_into_terminal

    def timed_paste(text):
        pasted.append((time.monotonic(), text))
        paste(text)

    monkeypatch.setattr(t, "paste_into_terminal", timed_paste)
    t.pyperclip.copy("from before the recording")

    session = t.NemotronSession()
    for _ in CHUNKS:
        t.audio_chunks.append(np.zeros((int(t.SAMPLE_RATE * CHUNK_SECONDS), 1), np.float32))
        time.sleep(CHUNK_SECONDS)
    assert session.finish() == "".join(CHUNKS).strip()
    session.restore_clipboard()

    assert session.route == "terminal-paste"
    assert [text for _, text in pasted] == CHUNKS  # one paste per chunk, in time
    wait_for(lambda: b"".join(d for _, d in reads(log)).count(b"\x1b[201~") == len(CHUNKS))
    received = b"".join(data for _, data in reads(log))
    assert received == b"".join(
        b"\x1b[200~" + chunk.encode() + b"\x1b[201~" for chunk in CHUNKS
    )
    assert b"\r" not in received and b"\n" not in received  # nothing submitted

    # Each chunk reached the program within a second of its paste starting, so the
    # terminal kept up while "speaking" and was not blocked until the end.
    ends, seen = [], b""
    for when, data in reads(log):
        seen += data
        ends += [when] * (seen.count(b"\x1b[201~") - len(ends))
    delays = [end - when for end, (when, _) in zip(ends, pasted)]
    assert max(delays) < 1.0, delays

    typed = time.monotonic()
    subprocess.run(["xdotool", "type", "--window", window, "x"], check=True, timeout=10)
    wait_for(lambda: reads(log)[-1][1] == b"x", 5)
    assert reads(log)[-1][0] - typed < 1.0  # input is not frozen

    wait_for(lambda: t.pyperclip.paste() == "from before the recording", 5)
