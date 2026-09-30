# TalkType

**Push-to-talk voice typing for your terminal.**

Press a hotkey, speak, press again — your words appear wherever you're typing. Works with any terminal, IDE, or text field. Local transcription using [Whisper](https://github.com/openai/whisper), no cloud services required.

![Demo](assets/demo.gif)

## Why TalkType?

When you type, you self-edit and truncate. When you speak, you explain naturally and fully. TalkType bridges that gap — letting you talk to your terminal, your AI assistant, or any app, and have your words appear instantly.

Built for developers who want:
- **Voice input for CLI tools** like Claude Code, aider, or any terminal app
- **System-wide dictation** that works anywhere — terminals, IDEs, browsers
- **Local, private transcription** — your voice never leaves your machine
- **Minimal latency** — GPU-accelerated transcription in under a second

## Features

- **Push-to-talk**: Press F9 to start, speak, press F9 to stop and paste
- **Works everywhere**: Browsers, IDEs, terminals — any text field that accepts paste
- **Cross-platform**: Linux, Windows, macOS
- **Local Whisper**: Uses faster-whisper for fast, private transcription
- **API mode**: Connect to any Whisper-compatible API server
- **Smart paste**: Auto-detects terminals vs other apps (Ctrl+Shift+V vs Ctrl+V)
- **Window focus**: Remembers where you started — switch apps while speaking
- **Configurable**: Choose your hotkey, model size, and language

## Installation

### Quick Install (Linux)

```bash
git clone https://github.com/lmacan1/talktype.git && cd talktype
sudo apt install xdotool xclip portaudio19-dev
python3 -m venv venv && source venv/bin/activate
pip install -e .
talktype  # Setup wizard launches automatically
```

### Manual Install - Linux (Ubuntu/Debian)

```bash
# System dependencies
sudo apt install xdotool xclip portaudio19-dev

# Clone and install
git clone https://github.com/lmacan1/talktype.git
cd talktype
python3 -m venv venv
source venv/bin/activate
pip install -e .  # Installs 'talktype' command
```

### Windows

```powershell
git clone https://github.com/lmacan1/talktype.git
cd talktype
python -m venv venv
.\venv\Scripts\activate
pip install -e .
talktype  # Setup wizard launches automatically
```

### macOS

```bash
brew install portaudio
git clone https://github.com/lmacan1/talktype.git
cd talktype
python3 -m venv venv && source venv/bin/activate
pip install -e .
talktype  # Setup wizard launches automatically
```

## Usage

### First Run — Setup Wizard

On first launch, TalkType runs an interactive setup wizard:

```bash
talktype
```

The wizard lets you:
- Choose transcription mode (local server, cloud API, or local model)
- Set hotkeys by pressing them (not typing)
- Select Whisper model and language
- Optionally install as a system service (runs on login)

Config is saved to `~/.config/talktype/config.yaml`. Re-run anytime with `talktype --setup`.

### Basic Usage

```bash
talktype  # Uses saved config
```

1. Press **F9** to start recording (beep)
2. Speak your text
3. Press **F9** again to stop and paste (beep)
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
python talktype.py --model small

# Use a different hotkey: any key name pynput knows, e.g. f10, pause, scroll_lock, menu
python talktype.py --hotkey pause

# Connect to a Whisper API server (if you have one running)
python talktype.py --api http://localhost:8002/transcribe

# Change language
python talktype.py --language es  # Spanish

# Type while you are still speaking (see Streaming below)
python talktype.py --stream
```

### Streaming: type while you speak

With `--stream` (or `streaming: true` under `transcription:` in the config
file), words appear while you are still talking instead of all at once when
you stop. Every `--stream-interval` seconds (default 1.0) the recording so
far is transcribed again, and a word is pasted once two consecutive
transcripts agree on it; words Whisper is still changing its mind about stay
back. When you stop, a final transcription of the whole recording adds the
rest. Nothing is typed twice, and the clipboard is restored once at the end.

Streaming needs the local model (not `--api`). Each pass costs about a
second of CPU with the `base` model, so text trails your speech by a few
seconds; `--cpu-threads` (default up to 8) matters more for this than the
model size.

```yaml
transcription:
  mode: local
  model: base
  streaming: true
  stream_interval: 1.0
  cpu_threads: 8
```

#### Parakeet as streaming engine

`--stream-engine parakeet` (config `stream_engine: parakeet`) streams with
NVIDIA's [Parakeet TDT
0.6B v3](https://huggingface.co/istupakov/parakeet-tdt-0.6b-v3-onnx) instead
of Whisper, run locally through
[onnx-asr](https://github.com/istupakov/onnx-asr) with int8 weights. It
covers English and 24 other European languages, German included, and
detects the language itself (`--language` does not apply to it). Install
the extra; the model (about 640 MB) downloads on first use:

```bash
uv tool install 'talktype[local,parakeet] @ git+https://github.com/ChristianGeng/talktype'
```

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

#### Nemotron: native streaming

Whisper and Parakeet are offline models, so streaming with them means
transcribing again and again and waiting for two passes to agree; the first
word then lags speech by 3-5 s whatever the model. `--stream-engine
nemotron` uses NVIDIA's [Nemotron 3.5 ASR Streaming
0.6B](https://huggingface.co/nvidia/nemotron-3.5-asr-streaming-0.6b)
instead, a cache-aware model: it keeps its state from one 560 ms chunk to
the next, so each chunk is decoded once and its words are pasted right away.
There is no re-transcription and no pass after you stop, only the last
chunk. It covers 40 locales, English and German among them; `--language`
picks one, otherwise the model detects it.

It runs on the CPU through
[onnxruntime-genai](https://github.com/microsoft/onnxruntime-genai) with the
[INT4 ONNX export](https://huggingface.co/onnx-community/nemotron-3.5-asr-streaming-0.6b-onnx-int4)
(about 790 MB, downloaded on first use):

```bash
uv tool install 'talktype[local,nemotron] @ git+https://github.com/ChristianGeng/talktype'
```

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

#### How streamed words reach the window

`--stream-output` (config `stream_output`) picks the route, once per
recording:

- `auto` (default): kitty remote control when the focused window is a kitty
  that answers on its socket; otherwise keystrokes, pasting only chunks
  with characters that are not on the keyboard (ü, ß, €).
- `kitty`: `kitten @ send-text` into the focused kitty window. No clipboard,
  no synthetic keys, no focus change, and Unicode arrives intact. Needs
  `listen_on unix:@kitty` in kitty.conf (and a kitty restart); set
  `--kitty-socket` / `--kitten` if yours differ.
- `type`: `xdotool type` keystrokes, as nerd-dictation does. xdotool makes
  missing characters by remapping a spare key, which kitty misses, so German
  umlauts get lost there.
- `paste`: the clipboard and Ctrl+V per chunk. Each chunk hands the
  clipboard to a new xclip, re-activates the window, and makes kitty read
  the clipboard synchronously (up to 2 s, stalling all its windows); on a
  GNOME desktop the terminal stayed blocked until recording stopped.

```yaml
transcription:
  streaming: true
  stream_engine: nemotron
  stream_output: auto
  kitten: /home/me/.local/kitty.app/bin/kitten   # if not on the service's PATH
```

### OpenAI-Compatible APIs

TalkType supports any OpenAI-compatible transcription API, so you can use different backends like Whisper, Parakeet, or Whisper Turbo:

```bash
# OpenAI API
python talktype.py --api https://api.openai.com/v1/audio/transcriptions --api-model whisper-1

# Groq (super fast)
python talktype.py --api https://api.groq.com/openai/v1/audio/transcriptions --api-model whisper-large-v3

# Local OpenAI-compatible server (e.g., faster-whisper-server, whisper.cpp)
python talktype.py --api http://localhost:8080/v1/audio/transcriptions --api-model whisper-1

# Any custom server
python talktype.py --api http://localhost:8002/transcribe
```

TalkType auto-detects OpenAI-compatible endpoints by URL pattern. For custom servers, it uses a simpler format that works with most Whisper APIs.

### Model Sizes

| Model | Size | Speed | Accuracy | VRAM |
|-------|------|-------|----------|------|
| tiny | ~75MB | Fastest | Basic | ~1GB |
| base | ~150MB | Fast | Good | ~1GB |
| small | ~500MB | Medium | Better | ~2GB |
| medium | ~1.5GB | Slow | Great | ~5GB |
| large-v3 | ~3GB | Slowest | Best | ~10GB |

For most use cases, `base` or `small` is the sweet spot.

## Whisper API Server (Recommended for Power Users)

For faster startup and better performance, run the included Whisper API server. The model stays loaded in memory, so TalkType connects instantly.

### Why use the server?

| Mode | Startup | Memory | Best for |
|------|---------|--------|----------|
| Direct (`talktype.py`) | ~3-5s (loads model) | Uses RAM while running | Occasional use |
| Server (`whisper_server.py`) | Instant | Server keeps model loaded | Heavy use, multiple apps |

### Running the Server

**Terminal 1 - Start the server (once):**
```bash
source venv/bin/activate
python whisper_server.py --model base

# Or with GPU and larger model:
python whisper_server.py --model large-v3 --device cuda
```

**Terminal 2 - Run TalkType:**
```bash
source venv/bin/activate
python talktype.py --api http://localhost:8002/transcribe
```

### Server Options

```bash
python whisper_server.py --help

# Examples:
python whisper_server.py --model small        # Better accuracy
python whisper_server.py --port 8080          # Different port
python whisper_server.py --device cpu         # Force CPU
python whisper_server.py --device cuda        # Force GPU

# Environment variables also work:
WHISPER_MODEL=large-v3 WHISPER_DEVICE=cuda python whisper_server.py
```

### Running Server as a Service (Linux)

```bash
cat > ~/.config/systemd/user/whisper-server.service << 'EOF'
[Unit]
Description=Whisper API Server
After=network.target

[Service]
Type=simple
WorkingDirectory=/path/to/talktype
ExecStart=/path/to/talktype/venv/bin/python whisper_server.py --model base
Restart=on-failure
RestartSec=5

[Install]
WantedBy=default.target
EOF

systemctl --user daemon-reload
systemctl --user enable whisper-server
systemctl --user start whisper-server
```

### API Endpoints

The server exposes:

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/health` | GET | Check server status |
| `/transcribe` | POST | Transcribe audio file |
| `/docs` | GET | Interactive web UI — test transcription right in your browser |

**Example with curl:**
```bash
curl -X POST http://localhost:8002/transcribe \
  -F "file=@audio.wav" \
  -F "language=en"
```

## Running as a Service (Linux)

The setup wizard can install TalkType as a systemd service automatically — just select "Run at startup" when prompted.

Or install manually:

```bash
# Create systemd user service
mkdir -p ~/.config/systemd/user

cat > ~/.config/systemd/user/talktype.service << 'EOF'
[Unit]
Description=TalkType Voice Dictation
After=graphical-session.target
PartOf=graphical-session.target

[Service]
Type=simple
ExecStart=/path/to/talktype/venv/bin/talktype
Restart=on-failure
RestartSec=5
# Status lines appear in journalctl as they happen.
Environment=PYTHONUNBUFFERED=1

[Install]
WantedBy=default.target
EOF

# Enable and start
systemctl --user daemon-reload
systemctl --user enable talktype
systemctl --user start talktype
```

Manage with:
```bash
systemctl --user status talktype   # Check status
systemctl --user stop talktype     # Stop
systemctl --user restart talktype  # Restart
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

TalkType works seamlessly with [Claude Code](https://claude.ai/code) and similar terminal AI assistants:

1. Start TalkType in a separate terminal (or as a service)
2. Focus your Claude Code terminal
3. Press F9, describe what you want, press F9
4. Your detailed voice prompt appears in Claude Code

Voice lets you elaborate naturally without self-editing — often resulting in clearer, more detailed prompts.

## Using with Browsers

TalkType works in any browser text field — it's not just for terminals:

1. Focus a text field (Google Docs, ChatGPT, Slack, email composer, etc.)
2. Press F9, speak, press F9
3. Your words appear in the browser

Since TalkType uses clipboard + standard paste (Ctrl+V / Cmd+V), it works anywhere that accepts pasted text.

## Troubleshooting

### Linux: "No module named 'pynput'"
Make sure you activated the virtual environment: `source venv/bin/activate`

### Linux: Hotkey not working
pynput requires X11. If using Wayland, either:
- Switch to X11 session
- Run with `GDK_BACKEND=x11` environment variable

### macOS: Accessibility permissions
macOS requires accessibility permissions for keyboard monitoring:
1. Go to System Preferences → Security & Privacy → Privacy → Accessibility
2. Add your terminal app (Terminal, iTerm, etc.)

### Windows: No audio input
Make sure your microphone is set as the default input device in Windows Sound settings.

### Transcription is slow
- Try a smaller model: `--model tiny` or `--model base`
- If you have an NVIDIA GPU, ensure CUDA is installed for GPU acceleration
- Consider running a separate Whisper API server and using `--api`

## How It Works

1. **Global hotkey capture** (pynput) — works even when other apps are focused
2. **Audio recording** (sounddevice) — captures from your microphone
3. **Local transcription** (faster-whisper) — Whisper running on your machine
4. **Smart paste** (pyperclip + OS-specific) — detects terminal vs other apps

```
[F9 Press] → Start Recording → [Speak] → [F9 Press] → Stop Recording
                                                            ↓
                                                    Transcribe (Whisper)
                                                            ↓
                                                    Focus Original Window
                                                            ↓
                                                    Paste Text
```

## Contributing

Contributions welcome! Some ideas:
- [ ] Voice activity detection (auto-stop on silence)
- [ ] Wayland support (wtype instead of xdotool)
- [ ] Tray icon / visual indicator
- [ ] Custom vocabulary/prompts
- [ ] Streaming transcription

## License

MIT License — see [LICENSE](LICENSE) for details.

## Acknowledgments

- [faster-whisper](https://github.com/guillaumekln/faster-whisper) — CTranslate2-based Whisper
- [OpenAI Whisper](https://github.com/openai/whisper) — the model itself
- [pynput](https://github.com/moses-palmer/pynput) — cross-platform input monitoring
