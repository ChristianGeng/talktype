# CLAUDE.md

Guidance for coding agents (Claude Code, Devin) working on this fork of
TalkType. The [README](README.md) is the source of truth for user-facing
behaviour: installation, options, the config keys, streaming, Emacs, the
server and services. Link to it instead of copying it here, and update it
when behaviour changes.

## Project overview

TalkType is push-to-talk voice typing that works system-wide: press the
record key, speak, press it again, and the text lands in the focused window
(terminal, Emacs, browser, IDE). Transcription runs locally (faster-whisper,
NVIDIA Parakeet or Nemotron) or through a Whisper / OpenAI-compatible API.
With streaming, words are typed while you speak.

## Setup

The fork uses [uv](https://docs.astral.sh/uv/) only.

```bash
# System packages (Linux): xdotool and xclip type and paste (terminal-paste
# needs both), xprop (x11-utils) tells which window is focused, libportaudio2
# records; xvfb, emacs-nox and sakura run the tests. CI installs the same
# packages; tests/test_docs.py checks that this line lists them all.
sudo apt install xdotool xclip x11-utils libportaudio2 xvfb emacs-nox sakura

uv sync                       # project and the dev group (pytest)
uv sync --extra local         # plus faster-whisper for local transcription
uv sync --all-extras          # local, server, parakeet, nemotron
```

Extras are defined in `pyproject.toml`: `local`, `server`, `parakeet`,
`nemotron` (Python 3.11+), `all`.

## Running

```bash
uv run --extra local talktype                 # from the checkout
uv run --extra local talktype --help          # every flag
uv run --extra local talktype --which-key     # name of the next key pressed
uv run --extra local talktype --setup         # re-run the setup wizard

# Whisper API server (defaults to CUDA; add --device cpu without a GPU),
# and TalkType against it
uv run --extra local --extra server whisper_server.py --model base
uv run talktype --api http://localhost:8002/transcribe
```

Installed as a tool, the `talktype` command is on PATH (`~/.local/bin`):

```bash
uv tool install --force 'talktype[local] @ git+https://github.com/ChristianGeng/talktype'
talktype
```

Running TalkType and the server as systemd user services is described in
the README ([Running as a Service](README.md#running-as-a-service-linux),
[server as a service](README.md#running-the-server-as-a-service-linux)).

## Testing

Run exactly what CI runs (`.github/workflows/tests.yml`):

```bash
xvfb-run -a uv run --python 3.13 pytest -q
emacs --batch -Q -L . -l tests/talktype-test.el -f ert-run-tests-batch-and-exit
```

- `talktype` imports pynput, which needs an X display, so test modules that
  import `talktype` skip themselves without `DISPLAY`. Run pytest under
  `xvfb-run`, or a run that passes may have skipped most tests.
- With `emacs` and `emacsclient` installed, `tests/test_emacs_e2e.py` runs
  the emacs route against a throwaway headless Emacs server.
- With `sakura`, `xdotool`, `xclip` and `xprop` installed, `tests/test_terminal_paste_e2e.py`
  pastes streamed chunks into a real VTE terminal on the test's display.
- Both e2e modules skip when a tool is missing. CI sets
  `TALKTYPE_REQUIRE_E2E=1`, which makes them fail instead; set it locally
  to make sure they ran.
- `tests/talktype-test.el` holds the ERT tests for `talktype.el`.
- Tests for the optional engines (`parakeet`, `nemotron`) do not need the
  models or their extras.

## Conventions

- uv only: no other installers, virtualenv tools or bare interpreter calls,
  in code, docs or instructions. Use `uv run python -c …` for one-off
  snippets.
- Commit subjects: at most 50 characters, imperative mood ("Add …",
  "Fix …"). Explain why in the body.
- CI must stay green: both commands above pass before a PR is ready.
- New behaviour comes with tests (pytest, and ERT for `talktype.el`).
  Keep logic that can be tested without audio or X11 in its own module, as
  `streaming.py`, `replacements.py` and `hotkey.py` do.
- `requirements.txt` is the older all-in-one list: the core dependencies
  from `[project] dependencies` (platform markers included) plus the
  `local` and `server` extras, unconditionally. When a dependency changes
  in `pyproject.toml`, change it there too.
- `uv.lock` is not tracked; don't commit it.
- User-facing changes (flags, config keys, defaults) go into the README.

## Architecture

Files in the repository root:

- **`talktype.py`** — the client and the `talktype` entry point
  (`talktype:main`): argument and config parsing, hotkey listeners
  (pynput, X keysyms on Linux), recording (sounddevice), transcription
  (local faster-whisper, Parakeet, Nemotron or an HTTP API), speech and
  hallucination checks, window focus, paste and the stream routes,
  `StreamingSession` / `NemotronSession`, `TranscriptionHistory`
  (`~/.cache/talktype/history.jsonl`, pending audio in
  `~/.cache/talktype/pending.wav`), and the single-instance lock.
- **`streaming.py`** — which words of a growing transcript are safe to
  type (stable prefix, sentence cut, remainder); engine-independent.
- **`replacements.py`** — the config's `replacements:` (heard → written),
  applied to streamed and final text before it is written; `Stream` holds
  back only words that may still match.
- **`hotkey.py`** — `PressGate` (ignores key auto-repeat) and `RecordKey`
  (the record modes); no pynput or X11 dependencies.
- **`keynames.py`** — key names as `get_hotkey` accepts them
  (`hotkey_name`, X keysym names such as `XF86Tools`) and their labels;
  shared by `talktype.py` and `setup_wizard.py`, so the wizard can name a
  key without importing the app.
- **`parakeet.py`** — NVIDIA Parakeet TDT through onnx-asr (extra
  `parakeet`); re-transcribes the recording on each streaming pass.
- **`nemotron.py`** — NVIDIA Nemotron streaming through onnxruntime-genai
  (extra `nemotron`); each 560 ms chunk is decoded once, no
  re-transcription.
- **`talktype.el`** — Emacs side of the emacs route: `talktype-begin`,
  `talktype-append`, `talktype-replace-region`, `talktype-end`, called via
  `emacsclient --eval`.
- **`setup_wizard.py`** — first-run wizard (mode, hotkey by key press,
  model, language, optional systemd user service); writes the config.
- **`whisper_server.py`** — FastAPI server (extra `server`) that keeps a
  Whisper model loaded: `/health`, `/stats`, `/transcribe`, `/docs`.
- **`install.sh`** — Linux installer: system packages per distro
  (apt/dnf/pacman/zypper), uv via the official installer if missing, then
  `uv tool install --force --python 3.13 'talktype[<extras>] @ git+…'`.
  Extras from `--extras` or `TALKTYPE_EXTRAS` (default `local`);
  `INSTALL_DRY_RUN=1` prints the commands instead of running them, which
  `tests/test_install_sh.py` checks (plus `bash -n` and shellcheck).
- `tests/` — pytest suite and `talktype-test.el` (ERT).
- `assets/` — README media.

### Flow

```
record key → RECORDING → record key → TRANSCRIBING → focus original window → write text → IDLE
                ↓ (streaming)
        words written while speaking
```

State machine: `State.IDLE` → `State.RECORDING` → `State.TRANSCRIBING` →
`State.IDLE`.

### Record modes

`hotkeys.record_mode` / `--record-mode`, implemented in `hotkey.RecordKey`:

- `toggle` (default): press to start, press again to stop.
- `hold`: hold to talk, release to stop.
- `auto`: a tap toggles; holding at least `hold_ms` (default 500) stops on
  release.

### Stream routes

`transcription.stream_output` / `--stream-output`, chosen once per
recording by `choose_route()` and written by `stream_write()`:

- `auto` (default): `emacs` when the focused window is the Emacs that
  `emacsclient` reaches (a GUI frame of the server, or kitty running
  `emacsclient -nw` / the server), else `kitty` when the focused kitty
  answers on its socket, else `terminal-paste` in the terminals of
  `PASTE_TERMINALS` (Linux; WM_CLASS compared exactly, not with the
  substrings of `is_terminal_window()`), else keystrokes, pasting only chunks with non-ASCII characters.
- `emacs`: `emacsclient --eval` into `talktype.el` whenever a server
  answers; no fallback to keys (they would be commands in Emacs).
- `kitty`: `kitten @ send-text` into the focused kitty window; falls back
  to paste.
- `type`: `xdotool type` keystrokes.
- `paste`: clipboard and Ctrl+V per chunk.
- `terminal-paste` (auto only): clipboard and Ctrl+Shift+V per chunk, no
  window activation; the session saves the clipboard once when the route
  is chosen and restores it once at the end, as for `paste`.

The final (non-streamed) text is pasted through the clipboard, with
Ctrl+Shift+V in terminals and Ctrl+V elsewhere (`is_terminal_window()`).
Linux uses xdotool / xclip; Windows and macOS use pyautogui.

## Configuration

`~/.config/talktype/config.yaml`, written by the setup wizard. Command-line
flags override it. The README's
[Configuration file](README.md#configuration-file) section lists every key
with its default; `talktype --help` lists every flag. Don't duplicate either
here.

## Hotkeys

The record key defaults to F9 (`hotkeys.record`, `--hotkey`). The README
recommends Pause where F9 is taken by the focused programs, and
`talktype --which-key` to find a key's name; see
[Recovery Hotkeys](README.md#recovery-hotkeys) for the per-program table.
The re-paste (`hotkeys.recovery`) and retry (`hotkeys.retry`) keys are
unbound by default.

## Troubleshooting

See the README's [Troubleshooting](README.md#troubleshooting) first. For
development:

- **"No speech detected"**: check the input with
  `pactl get-default-source`. To measure the peak segment energy that
  `has_speech()` compares with its 0.01 threshold:

  ```bash
  uv run python -c "
  import numpy as np, sounddevice as sd
  audio = sd.rec(32000, samplerate=16000, channels=1, dtype='float32'); sd.wait()
  seg = 800  # 50 ms at 16 kHz
  peak = max(np.sqrt(np.mean(audio[i:i+seg]**2)) for i in range(0, len(audio), seg) if len(audio[i:i+seg]) >= 400)
  print(f'Peak segment energy: {peak:.4f} (threshold: 0.01)')
  "
  ```

- **Server not answering**: `curl http://localhost:8002/health`.
- **Port 8002 in use**: `lsof -i :8002`, or
  `uv run --extra local --extra server whisper_server.py --port 8003`.
- **Wayland**: pynput needs X11; use an X11 session or `GDK_BACKEND=x11`.
- **Stale environment**: `uv sync --reinstall`.
