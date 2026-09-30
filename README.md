# TalkType

**Push-to-talk voice typing for your terminal.**

Press a hotkey, speak, press again — your words appear wherever you're
typing. Works with any terminal, IDE, or text field. Local transcription,
no cloud services required.

![Demo](assets/demo.gif)

> This is [ChristianGeng/talktype](https://github.com/ChristianGeng/talktype),
> a fork of [lmacan1/talktype](https://github.com/lmacan1/talktype). It adds:
>
> - **Streaming**: words appear while you are still speaking, with Whisper,
>   NVIDIA Parakeet, or the natively streaming NVIDIA Nemotron.
> - **Text straight into kitty** via `kitten @ send-text`: no clipboard,
>   Unicode intact, and it passes through SSH to remote hosts.
> - **Text straight into Emacs** via `emacsclient` and `talktype.el`: the
>   buffer is edited by position, so evil's normal state or the minibuffer
>   cannot turn words into commands, and one undo removes a dictation.
> - **Any key as hotkey** (`pause`, `menu`, `f13`, …), with held keys no
>   longer toggling recording on auto-repeat.
> - A setup wizard and systemd service that work in more setups, and tests
>   in CI.

## Why TalkType?

When you type, you self-edit and truncate. When you speak, you explain
naturally and fully. TalkType bridges that gap — letting you talk to your
terminal, your AI assistant, or any app, and have your words appear
instantly.

Built for developers who want:
- **Voice input for CLI tools** like Claude Code, aider, or any terminal app
- **System-wide dictation** that works anywhere — terminals, IDEs, browsers
- **Local, private transcription** — your voice never leaves your machine
- **Low latency** — with streaming, text follows your speech

## Features

- **Push-to-talk**: press F9 to start, speak, press F9 to stop
- **Streaming**: optionally type while you speak (Whisper, Parakeet,
  Nemotron)
- **Works everywhere**: browsers, IDEs, terminals, and kitty directly
- **Cross-platform**: Linux, Windows, macOS
- **Local models**: faster-whisper, Parakeet and Nemotron run on your machine
- **API mode**: connect to any Whisper-compatible API server
- **Smart paste**: detects terminals vs other apps (Ctrl+Shift+V vs Ctrl+V)
- **Window focus**: remembers where you started — switch apps while speaking
- **Configurable**: hotkeys, model, language, streaming engine and route

## Installation

TalkType is installed as a [uv](https://docs.astral.sh/uv/) tool straight
from the fork; this puts the `talktype` command on your PATH
(`~/.local/bin`). The `local` extra brings faster-whisper for local
transcription.

### Linux (Ubuntu/Debian)

```bash
sudo apt install xdotool xclip libportaudio2
uv tool install 'talktype[local] @ git+https://github.com/ChristianGeng/talktype'
talktype  # the setup wizard runs on first start
```

Optional engines for streaming (see [Streaming](#streaming-type-while-you-speak)):

```bash
uv tool install --force 'talktype[local,parakeet] @ git+https://github.com/ChristianGeng/talktype'
uv tool install --force 'talktype[local,nemotron] @ git+https://github.com/ChristianGeng/talktype'
```

The `nemotron` extra needs Python 3.11 or newer (onnxruntime-genai has no
3.10 wheels); on 3.10 it installs nothing.

### Windows

```powershell
uv tool install "talktype[local] @ git+https://github.com/ChristianGeng/talktype"
talktype  # the setup wizard runs on first start
```

### macOS

```bash
brew install portaudio
uv tool install 'talktype[local] @ git+https://github.com/ChristianGeng/talktype'
talktype  # the setup wizard runs on first start
```

### From a clone (development)

```bash
git clone https://github.com/ChristianGeng/talktype.git && cd talktype
uv run --extra local talktype      # run from the checkout
xvfb-run -a uv run pytest -q       # tests (talktype imports pynput, which needs X)
emacs --batch -Q -L . -l tests/talktype-test.el -f ert-run-tests-batch-and-exit   # talktype.el
```

With `emacs` and `emacsclient` installed, pytest also runs an end-to-end test
against a throwaway headless Emacs server.

## Usage

### First Run — Setup Wizard

On first launch in a terminal, TalkType runs an interactive setup wizard:

```bash
talktype
```

The wizard lets you:
- Choose transcription mode (local server, cloud API, or local model)
- Set the hotkey by pressing it (Enter keeps the default)
- Select Whisper model and language
- Optionally install a systemd user service (runs on login)

Config is saved to `~/.config/talktype/config.yaml`. Re-run it with
`talktype --setup`. `talktype --help` and starts without a terminal (e.g.
under systemd) skip the wizard.

### Basic Usage

```bash
talktype  # uses the saved config
```

1. Press **F9** to start recording (beep)
2. Speak your text
3. Press **F9** again to stop (beep)
4. Your words appear in the focused window

### Recovery Hotkeys

| Key | What it does |
|-----|-------------|
| **F9** | Record / Stop & Paste |
| unbound | Re-paste last transcription (if paste failed): `hotkeys.recovery` |
| unbound | Retry transcription (if API timed out): `hotkeys.retry` |

The record key has three modes (`hotkeys.record_mode`, or `--record-mode`):

- `toggle` (default): press to start, press again to stop.
- `hold`: hold the key to talk, release to stop (push-to-talk).
- `auto`: a tap toggles as above; holding the key for at least `hold_ms`
  (default 500) records until you let go. Recording starts at the press, so
  there is no delay either way.

Use a key that does not type (a function key, Pause, Scroll Lock, Right
Ctrl): holding a typing key such as Space would put repeated characters into
the focused window.

Only recording has a key by default; every bound key is taken away from the
focused window. Give the other two a key in the config file if you want
them, and use `null` to leave any action unbound:

```yaml
hotkeys:
  record: f9
  record_mode: auto  # toggle | hold | auto
  hold_ms: 500
  recovery: f8       # default: null
  retry: null
```

### Sounds

TalkType can beep on four events: `start` (recording starts), `stop` (it
stops), `success` (the text is in) and `error` (no speech, or a failure).
By default you hear one beep to start and one to stop: `success` is off,
since it followed `stop` a moment later and sounded like a double beep, and
`error` only plays when something went wrong. Switch single beeps on or
off, all of them with `sounds: true` / `sounds: false`:

```yaml
sounds:
  success: true   # the others keep their defaults
```

### Options

```bash
# Use a different model (tiny, base, small, medium, large-v3)
talktype --model small

# Use a different hotkey: any key name pynput knows, e.g. f10, pause, scroll_lock, menu
talktype --hotkey pause

# Connect to a Whisper API server (if you have one running)
talktype --api http://localhost:8002/transcribe

# Change language
talktype --language es  # Spanish

# Type while you are still speaking (see Streaming below)
talktype --stream
```

Every option can also be set in the config file; command-line flags win.
`talktype --help` lists them all.

### Configuration file

`~/.config/talktype/config.yaml`, with every key and its default. Keys whose
default depends on something else are commented out; leave them unset to
keep that default.

```yaml
hotkeys:
  record: f9               # any pynput key name: f10, pause, scroll_lock, menu, ...
  record_mode: toggle      # toggle | hold | auto
  hold_ms: 500             # auto mode: hold at least this long to stop on release
  recovery: null           # re-paste the last transcription; e.g. f8
  retry: null              # re-transcribe the last saved audio; e.g. f7

sounds:                    # true: all four beeps; false: none
  start: true
  stop: true
  success: false
  error: true

transcription:
  mode: local              # local | api
  api_url: http://localhost:8002/transcribe   # used with mode: api
  api_model: whisper-1     # used with OpenAI-compatible APIs; Groq: whisper-large-v3
  model: base              # Whisper: tiny, base, small, medium, large-v3
  # language: en           # default: auto-detect
  # cpu_threads: 8         # default: min(8, CPU count); local model

  streaming: false         # true: type while you speak (local model only)
  stream_engine: whisper   # whisper | parakeet | nemotron
  # final_engine: whisper  # engine after you stop; default: the streaming engine
  stream_interval: 1.0     # seconds between passes (whisper, parakeet)
  parakeet_model: nemo-parakeet-tdt-0.6b-v3
  nemotron_model: onnx-community/nemotron-3.5-asr-streaming-0.6b-onnx-int4
  nemotron_threads: 4

  stream_output: auto      # auto | emacs | kitty | type | paste
  kitty_socket: unix:@kitty   # may contain {kitty_pid}
  kitten: kitten           # path of kitty's kitten command; default: found on PATH
  emacsclient: emacsclient # path of emacsclient; default: found on PATH
  # emacs_socket: server   # Emacs server socket name or path (emacsclient -s); default: emacsclient's

ui:
  minimal: false           # show only the status

history:
  limit: 100               # transcriptions kept for re-paste
```

## Streaming: type while you speak

With `--stream` (or `streaming: true` under `transcription:`), words appear
while you are still talking instead of all at once when you stop. Streaming
needs a local model (not `--api`). Three engines are available.

### Whisper (default engine)

Every `--stream-interval` seconds (default 1.0) the recording so far is
transcribed again, and a word is typed once two consecutive transcripts
agree on it; words Whisper is still changing its mind about stay back. When
you stop, a final transcription of the whole recording adds the rest.
Nothing is typed twice.

Each pass costs about a second of CPU with the `base` model, so text trails
your speech by a few seconds; `--cpu-threads` (default up to 8) matters more
for this than the model size.

```yaml
transcription:
  mode: local
  model: base
  streaming: true
  stream_interval: 1.0
  cpu_threads: 8
```

### Parakeet

`--stream-engine parakeet` (config `stream_engine: parakeet`) streams with
NVIDIA's [Parakeet TDT
0.6B v3](https://huggingface.co/istupakov/parakeet-tdt-0.6b-v3-onnx) instead
of Whisper, run locally through
[onnx-asr](https://github.com/istupakov/onnx-asr) with int8 weights. It
covers English and 24 other European languages, German included, and
detects the language itself (`--language` does not apply to it). It needs
the `parakeet` extra; the model (about 640 MB) downloads on first use.

```yaml
transcription:
  streaming: true
  stream_engine: parakeet
  # final_engine: parakeet   # default: same as stream_engine
```

Parakeet's cost grows with the audio length (about 0.2 s per second of
speech on a laptop CPU), while Whisper pads everything to 30 s and costs
the same up to there. So with Parakeet, audio up to the last typed sentence
end is dropped from later passes, and the pass after you stop only reads
what is left; passes then stay about as long as a sentence however long you
talk.

`--final-engine` picks the engine for the pass after you stop. It defaults
to the streaming engine: typed words and the final text then come from the
same model. Mixing them works, but the final text can word something
differently from what is already typed ("wanna" typed, "want to" final
gives "wanna to").

Measured on a 12-core laptop CPU, `base` Whisper vs Parakeet int8, 8
threads, one pass per second, speech played back in real time:

| Clip | Engine | First word | Words while speaking | Last text after stop |
|---|---|---|---|---|
| English, 9 s | Whisper | 5.2 s | 19/28 | 2.0 s |
| | Parakeet | 3.6 s | 20/28 | 2.7 s |
| German, 9 s | Whisper | 3.0 s | 14/21 | 1.7 s |
| | Parakeet | 4.7 s | 17/21 | 2.7 s |
| English, 34 s | Whisper | 3.0 s | 77/93 | 6.2 s |
| | Parakeet | 4.3 s | 84/93 | 2.3 s |

Past 30 s Whisper needs two windows per pass, so it falls behind; on the
34 s clip Parakeet also got every word right where Whisper wrote "pan" for
"plan". For short dictation the two are close. Parakeet also writes fillers
such as "uh" that Whisper drops.

### Nemotron: native streaming

Whisper and Parakeet are offline models, so streaming with them means
transcribing again and again and waiting for two passes to agree; the first
word then lags speech by 3-5 s whatever the model. `--stream-engine
nemotron` uses NVIDIA's [Nemotron 3.5 ASR Streaming
0.6B](https://huggingface.co/nvidia/nemotron-3.5-asr-streaming-0.6b)
instead, a cache-aware model: it keeps its state from one 560 ms chunk to
the next, so each chunk is decoded once and its words are typed right away.
There is no re-transcription and no pass after you stop, only the last
chunk. It covers 40 locales, English and German among them; `--language`
picks one, otherwise the model detects it.

It runs on the CPU through
[onnxruntime-genai](https://github.com/microsoft/onnxruntime-genai) with the
[INT4 ONNX export](https://huggingface.co/onnx-community/nemotron-3.5-asr-streaming-0.6b-onnx-int4)
(about 790 MB, downloaded on first use). It needs the `nemotron` extra.

```yaml
transcription:
  streaming: true
  stream_engine: nemotron
  language: en            # or de, ...; omit to auto-detect
  nemotron_threads: 4     # see below
```

`--nemotron-threads` defaults to 4. On a laptop with 2 performance and 8
efficiency cores (i7-1255U) a chunk took 320 ms with 4 threads, but 850 ms
with 8 and 1280 ms with 12: extra threads land on the slow cores and hold
the fast ones back. With fewer than about 560 ms per chunk it keeps up with
speech; try 3-6 on other CPUs.

Same laptop and clips as above, speech played back in real time, and here
including a simulated 0.4 s paste (the Whisper and Parakeet numbers above
paste instantly):

| Clip | First word on screen | Words while speaking | Last text after stop | WER |
|---|---|---|---|---|
| English, 9 s | 2.7 s | 29/29 | none left | – |
| German, 9 s | 2.5 s | 21/21 | none left | 0 % |
| English, 34 s | 1.6 s | 90/93 | 0.3 s | 0 % |

The model itself emits its first word about 1.4 s into speech; the rest is
the paste and setting up the recording. It writes fillers such as "uh", and
it always punctuates.

### How streamed words reach the window

`--stream-output` (config `stream_output`) picks the route, once per
recording:

- `auto` (default): `emacsclient` when the focused window is Emacs (see
  below); kitty remote control when the focused window is a kitty that
  answers on its socket; otherwise keystrokes, pasting only chunks with
  characters that are not on the keyboard (ü, ß, €).
- `emacs`: `emacsclient --eval` calls into `talktype.el`, whenever an Emacs
  server answers, whatever window is focused. Without a server the
  recording writes nothing while streaming (the text is in the history).
- `kitty`: `kitten @ send-text` into the focused kitty window. No clipboard,
  no synthetic keys, no focus change, and Unicode arrives intact; over SSH
  it reaches the remote shell like typed input.
- `type`: `xdotool type` keystrokes, as nerd-dictation does. xdotool makes
  missing characters by remapping a spare key, which kitty misses, so German
  umlauts get lost there.
- `paste`: the clipboard and Ctrl+V per chunk. Each chunk hands the
  clipboard to a new xclip, re-activates the window, and makes kitty read
  the clipboard synchronously (up to 2 s, stalling all its windows); on a
  GNOME desktop the terminal stayed blocked until recording stopped.

The kitty route needs kitty's remote control socket. In `kitty.conf`
(read at kitty start, so restart kitty once):

```
allow_remote_control yes
listen_on unix:${XDG_RUNTIME_DIR}/kitty-{kitty_pid}.sock
```

and the same socket for TalkType; `{kitty_pid}` is filled in from the
focused window, since kitty otherwise appends its PID to the name:

```yaml
transcription:
  streaming: true
  stream_engine: nemotron
  stream_output: auto
  kitty_socket: unix:/run/user/1000/kitty-{kitty_pid}.sock   # your XDG_RUNTIME_DIR
  kitten: /home/me/.local/kitty.app/bin/kitten   # if not on the service's PATH
```

A socket under `$XDG_RUNTIME_DIR` is only reachable by you; an abstract
`unix:@…` socket can be reached by any local user.

### Emacs

In Emacs, keys are commands: with evil in normal state `DEL` is a motion,
and the minibuffer, isearch or org-agenda bind keys of their own. The
`emacs` route therefore edits the buffer itself, through `emacsclient` and
the functions in [`talktype.el`](talktype.el):

- `talktype-begin` opens a dictation region at point in the selected
  window's buffer; while it is open the words are underlined
  (face `talktype-provisional`).
- `talktype-append` inserts each chunk at the region's end;
  `talktype-replace-region` replaces the whole region (for corrections).
- `talktype-end` removes the underline and closes the region. The whole
  dictation is one undo step, unless you edited the buffer yourself
  meanwhile: then its chunks stay separate undo steps, so undoing the
  dictation never takes your own edits along.

The evil state and the mark stay as they are, and point moves along only if
it was at the end of the dictation. Selecting another buffer meanwhile does
not matter: the words keep going into the buffer the dictation started in.
In a read-only buffer, the minibuffer or during isearch, `talktype-begin`
refuses and that recording writes nothing into Emacs (never keys, never
Ctrl+V); the text is still in the history for the recovery key. The same
holds when Emacs stops taking words halfway (server gone, buffer killed):
the rest of that recording is not written, to leave no gaps. A region that
could not be closed is closed by the next dictation.

The transcript reaches Emacs as data, never as code: it is passed as a Lisp
string literal with `\` and `"` escaped and everything outside printable
ASCII written as `\uXXXX`, so quotes, backslashes or parentheses in speech
are only ever inserted.

Setup: start a server in the Emacs you dictate into and load `talktype.el`
from the clone, e.g. in Doom's `config.el`:

```elisp
(add-to-list 'load-path "~/src/talktype")   ; your clone
(require 'talktype)
(server-start)                              ; unless already running, or emacs --daemon
```

`stream_output: auto` then picks `emacs` for

- GUI Emacs frames (`WM_CLASS` "emacs", "Emacs") of the Emacs server that
  `emacsclient` reaches, and
- kitty windows whose foreground process is `emacsclient -nw` on the same
  socket (`-s`/`--socket-name`, compared by name) or that server's own
  `emacs -nw` (from `kitten @ ls`, so kitty's remote control must be set up
  as above).

An `emacs -nw` without a server, or with a different one, gets the kitty
route. Set `emacs_socket` if your server does not use emacsclient's default
socket (`server-name` other than `server`).

## OpenAI-Compatible APIs

TalkType supports any OpenAI-compatible transcription API:

```bash
# OpenAI API
talktype --api https://api.openai.com/v1/audio/transcriptions --api-model whisper-1

# Groq (super fast)
talktype --api https://api.groq.com/openai/v1/audio/transcriptions --api-model whisper-large-v3

# Local OpenAI-compatible server (e.g., faster-whisper-server, whisper.cpp)
talktype --api http://localhost:8080/v1/audio/transcriptions --api-model whisper-1

# Any custom server
talktype --api http://localhost:8002/transcribe
```

TalkType auto-detects OpenAI-compatible endpoints by URL pattern. For custom
servers, it uses a simpler format that works with most Whisper APIs.

### Model Sizes

| Model | Size | Speed | Accuracy | VRAM |
|-------|------|-------|----------|------|
| tiny | ~75MB | Fastest | Basic | ~1GB |
| base | ~150MB | Fast | Good | ~1GB |
| small | ~500MB | Medium | Better | ~2GB |
| medium | ~1.5GB | Slow | Great | ~5GB |
| large-v3 | ~3GB | Slowest | Best | ~10GB |

For most use cases, `base` or `small` is the sweet spot.

## Whisper API Server

For faster startup, run the included Whisper API server: the model stays
loaded in memory, so TalkType connects instantly.

| Mode | Startup | Memory | Best for |
|------|---------|--------|----------|
| Direct (`talktype`) | ~3-5 s (loads model) | Uses RAM while running | Occasional use |
| Server (`whisper_server.py`) | Instant | Server keeps model loaded | Heavy use, multiple apps |

The server runs from a clone, with uv:

```bash
git clone https://github.com/ChristianGeng/talktype.git && cd talktype

# Terminal 1 — the server (defaults to CUDA; add --device cpu without a GPU)
uv run --extra local --extra server whisper_server.py --model base

# Terminal 2 — TalkType against it
talktype --api http://localhost:8002/transcribe
```

### Server Options

```bash
uv run --extra local --extra server whisper_server.py --help

# Examples:
uv run --extra local --extra server whisper_server.py --model small   # Better accuracy
uv run --extra local --extra server whisper_server.py --port 8080     # Different port
uv run --extra local --extra server whisper_server.py --device cpu    # Force CPU

# Environment variables also work:
WHISPER_MODEL=large-v3 WHISPER_DEVICE=cuda uv run --extra local --extra server whisper_server.py
```

### Running the Server as a Service (Linux)

```bash
cat > ~/.config/systemd/user/whisper-server.service << 'EOF'
[Unit]
Description=Whisper API Server
After=network.target

[Service]
Type=simple
WorkingDirectory=%h/talktype
ExecStart=%h/.local/bin/uv run --extra local --extra server whisper_server.py --model base
Restart=on-failure
RestartSec=5

[Install]
WantedBy=default.target
EOF

systemctl --user daemon-reload
systemctl --user enable --now whisper-server
```

Adjust `WorkingDirectory` to your clone and the `uv` path to yours
(`command -v uv`).

### API Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/health` | GET | Check server status |
| `/transcribe` | POST | Transcribe audio file |
| `/docs` | GET | Interactive web UI — test transcription right in your browser |

```bash
curl -X POST http://localhost:8002/transcribe \
  -F "file=@audio.wav" \
  -F "language=en"
```

## Running as a Service (Linux)

The setup wizard can install TalkType as a systemd user service — just
select "Run at startup" when prompted. Or write the unit yourself:

```bash
mkdir -p ~/.config/systemd/user
cat > ~/.config/systemd/user/talktype.service << 'EOF'
[Unit]
Description=TalkType Voice Typing
After=graphical-session.target
PartOf=graphical-session.target

[Service]
Type=simple
ExecStart=%h/.local/bin/talktype
Restart=on-failure
RestartSec=5
# Status lines appear in journalctl as they happen.
Environment=PYTHONUNBUFFERED=1

[Install]
WantedBy=default.target
EOF

systemctl --user daemon-reload
systemctl --user enable --now talktype
```

Manage with:
```bash
systemctl --user status talktype   # Check status
systemctl --user restart talktype  # After editing the config
journalctl --user -u talktype -f   # Watch its output
```

Do not set `DISPLAY` in the unit: it is inherited from the desktop session,
and a hard-coded `DISPLAY=:0` crash-loops the service on a session that runs
on another display. If the service cannot reach X at all, import the
session's variables once with
`systemctl --user import-environment DISPLAY XAUTHORITY`. All settings come
from `~/.config/talktype/config.yaml`, so after editing it a restart is
enough. Use `systemctl --user` without `sudo`; under `sudo` it cannot find
your session.

If the first model download stalls at 0 bytes (seen on some networks),
add `Environment=HF_HUB_DISABLE_XET=1` to the unit: it makes the Hugging
Face download use plain HTTPS.

## Using with Claude Code

TalkType works with [Claude Code](https://claude.ai/code) and similar
terminal AI assistants, locally and over SSH:

1. Run TalkType as a service (or in a separate terminal)
2. Focus the terminal with Claude Code — also one where you are SSH'd into a
   remote host
3. Press F9, describe what you want, press F9
4. Your prompt appears in Claude Code; with streaming it grows while you speak

Nothing needs installing on the remote host: the text travels as typed
input. In kitty, the `kitty` route delivers it without the clipboard.

## Using with Browsers

TalkType works in any browser text field:

1. Focus a text field (Google Docs, ChatGPT, Slack, email composer, etc.)
2. Press F9, speak, press F9
3. Your words appear in the browser

Outside kitty it uses the clipboard and the standard paste shortcut
(Ctrl+V / Cmd+V), or keystrokes while streaming, so it works anywhere that
accepts text.

## Troubleshooting

### Linux: Hotkey not working
pynput requires X11. If using Wayland, either:
- Switch to an X11 session
- Run with `GDK_BACKEND=x11` environment variable

### Linux: "No speech detected" although recording beeps
The default input is probably not your microphone (a virtual device, a
muted mic, or a headset that is switched off). Check with
`pactl get-default-source` and `pactl list short sources`, and set the right
one with `pactl set-default-source <name>`.

### Linux: F9 does nothing right after installing
TalkType only listens for the hotkey once the model has loaded; the first
start downloads it. Watch `journalctl --user -u talktype -f` for
"Ready!".

### Linux: Held hotkey starts and stops recording repeatedly
Fixed in this fork: auto-repeat of a held key is ignored. If you see it,
update with `uv tool install --force 'talktype[local] @ git+https://github.com/ChristianGeng/talktype'`.

### macOS: Accessibility permissions
macOS requires accessibility permissions for keyboard monitoring:
1. Go to System Preferences → Security & Privacy → Privacy → Accessibility
2. Add your terminal app (Terminal, iTerm, etc.)

### Windows: No audio input
Make sure your microphone is set as the default input device in Windows
Sound settings.

### Transcription is slow
- Try a smaller model: `--model tiny` or `--model base`
- If you have an NVIDIA GPU, ensure CUDA is installed for GPU acceleration
- Consider running a separate Whisper API server and using `--api`
- For streaming, try `--stream-engine nemotron`

## How It Works

1. **Global hotkey capture** (pynput) — works even when other apps are focused
2. **Audio recording** (sounddevice) — captures from your microphone
3. **Local transcription** (faster-whisper, Parakeet or Nemotron)
4. **Delivery** — emacsclient into Emacs, kitty remote control, keystrokes, or smart paste

```
[F9 Press] → Start Recording → [Speak] → [F9 Press] → Stop Recording
                  ↓ (streaming)                              ↓
          words typed as you speak                    Transcribe the rest
                                                             ↓
                                                    Focus Original Window
                                                             ↓
                                                    Paste / type the text
```

## Contributing

Contributions welcome! Some ideas:
- [ ] Voice activity detection (auto-stop on silence)
- [ ] Wayland support (wtype instead of xdotool)
- [ ] Tray icon / visual indicator
- [ ] Custom vocabulary/prompts

## License

MIT License — see [LICENSE](LICENSE) for details.

## Acknowledgments

- [lmacan1/talktype](https://github.com/lmacan1/talktype) — the original
  TalkType this fork builds on
- [faster-whisper](https://github.com/guillaumekln/faster-whisper) — CTranslate2-based Whisper
- [OpenAI Whisper](https://github.com/openai/whisper) — the model itself
- [onnx-asr](https://github.com/istupakov/onnx-asr) and
  [onnxruntime-genai](https://github.com/microsoft/onnxruntime-genai) — Parakeet
  and Nemotron on the CPU
- [pynput](https://github.com/moses-palmer/pynput) — cross-platform input monitoring
