#!/usr/bin/env python3
"""
TalkType - Push-to-talk voice typing for your terminal.

Press a hotkey, speak, press again - your words appear wherever you're typing.
Works on Linux, Windows, and macOS with local Whisper transcription.

Usage:
    python talktype.py [--api URL] [--model MODEL] [--hotkey KEY]

Examples:
    python talktype.py                          # Use faster-whisper locally
    python talktype.py --api http://localhost:8002/transcribe  # Use API
    python talktype.py --model small            # Use small model
    python talktype.py --hotkey f8              # Use F8 instead of F9
"""

import argparse
import atexit
import io
import json
import os
import platform
import queue
import shutil
import subprocess
import sys
import threading
import time
from datetime import datetime
from pathlib import Path

import numpy as np
import pyperclip
import requests
import sounddevice as sd
from pynput import keyboard
from scipy.io import wavfile
import yaml

import nemotron
import parakeet
import streaming
from hotkey import MODES, PressGate, RecordKey

# === Configuration ===
SAMPLE_RATE = 16000
DEFAULT_MODEL = "base"
SYSTEM = platform.system()  # "Linux", "Windows", "Darwin" (macOS)

# Terminal identifiers per OS
TERMINALS = {
    "Linux": [
        "gnome-terminal", "xterm", "konsole", "alacritty", "kitty",
        "terminator", "tilix", "xfce4-terminal", "urxvt", "st",
        "sakura", "guake", "tilda", "hyper", "wezterm"
    ],
    "Windows": [
        "WindowsTerminal", "cmd.exe", "powershell", "pwsh",
        "ConEmu", "mintty", "Hyper", "Terminus"
    ],
    "Darwin": [
        "Terminal", "iTerm", "iTerm2", "Hyper", "kitty",
        "alacritty", "wezterm"
    ]
}


# === State ===
class State:
    IDLE = 0
    RECORDING = 1
    TRANSCRIBING = 2


state = State.IDLE
state_lock = threading.Lock()
audio_chunks: list[np.ndarray] = []
stream: sd.InputStream | None = None
target_window = None
whisper_model = None
stream_model = None  # Parakeet model for streaming passes (--stream-engine parakeet)
nemotron_engine = None  # Nemotron model (--stream-engine nemotron)
config = None
history = None  # TranscriptionHistory instance
session = None  # StreamingSession while recording with --stream

# Debouncing to prevent double-paste and accidental re-triggers
_last_hotkey_time: float = 0.0
_last_paste_time: float = 0.0
HOTKEY_DEBOUNCE_MS = 300  # Ignore hotkey presses within 300ms
PASTE_DEBOUNCE_MS = 500   # Ignore paste calls within 500ms

# Debug logging for paste investigation (set to True to diagnose issues)
DEBUG_PASTE = False


class TranscriptionHistory:
    """Persists transcriptions to ~/.cache/talktype/history.jsonl for recovery."""

    def __init__(self, max_entries: int = 100):
        self.max_entries = max_entries
        self.cache_dir = Path.home() / ".cache" / "talktype"
        self.history_file = self.cache_dir / "history.jsonl"
        self.pending_audio = self.cache_dir / "pending.wav"
        self._last: dict | None = None
        self._ensure_dir()

    def _ensure_dir(self):
        """Create cache directory if needed."""
        self.cache_dir.mkdir(parents=True, exist_ok=True)

    def add(self, text: str):
        """Add transcription to history."""
        entry = {"timestamp": datetime.now().isoformat(), "text": text}
        self._last = entry
        try:
            with open(self.history_file, "a", encoding="utf-8") as f:
                f.write(json.dumps(entry) + "\n")
            self._maybe_trim()
        except Exception:
            pass  # Don't crash on history write failure

    def get_last(self) -> str | None:
        """Get last transcription text."""
        if self._last:
            return self._last["text"]
        # Fallback: read from file
        try:
            with open(self.history_file, "r", encoding="utf-8") as f:
                lines = f.readlines()
                if lines:
                    return json.loads(lines[-1])["text"]
        except Exception:
            pass
        return None

    def _maybe_trim(self):
        """Trim history file if it exceeds max_entries."""
        try:
            with open(self.history_file, "r", encoding="utf-8") as f:
                lines = f.readlines()
            if len(lines) > self.max_entries * 1.5:  # Only trim when 50% over
                with open(self.history_file, "w", encoding="utf-8") as f:
                    f.writelines(lines[-self.max_entries:])
        except Exception:
            pass

    def save_pending_audio(self, wav_buffer: io.BytesIO):
        """Save audio before transcription attempt."""
        try:
            wav_buffer.seek(0)
            with open(self.pending_audio, "wb") as f:
                f.write(wav_buffer.read())
            wav_buffer.seek(0)  # Reset for transcription
        except Exception:
            pass

    def clear_pending_audio(self):
        """Delete pending audio after successful transcription."""
        try:
            self.pending_audio.unlink(missing_ok=True)
        except Exception:
            pass

    def get_pending_audio(self) -> bytes | None:
        """Get pending audio for retry (expires after 1 hour)."""
        try:
            if self.pending_audio.exists():
                # Check if not too old (1 hour max)
                age = time.time() - self.pending_audio.stat().st_mtime
                if age > 3600:
                    self.clear_pending_audio()
                    return None
                return self.pending_audio.read_bytes()
        except Exception:
            pass
        return None


# === Config File Loading ===
CONFIG_PATH = Path.home() / ".config" / "talktype" / "config.yaml"


def load_config_file() -> dict:
    """Load config from YAML file if it exists."""
    if CONFIG_PATH.exists():
        try:
            with open(CONFIG_PATH) as f:
                return yaml.safe_load(f) or {}
        except Exception:
            pass
    return {}


# === Argument Parsing ===
def parse_args():
    # Load config file first (CLI args will override)
    file_config = load_config_file()
    hotkeys = file_config.get("hotkeys", {})
    trans = file_config.get("transcription", {})
    ui = file_config.get("ui", {})
    hist = file_config.get("history", {})

    # Determine API default from config
    api_default = None
    if trans.get("mode") == "api":
        api_default = trans.get("api_url")

    parser = argparse.ArgumentParser(
        description="Push-to-talk voice typing for your terminal.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python talktype.py                     # Use local faster-whisper
  python talktype.py --api http://localhost:8002/transcribe
  python talktype.py --model small       # Use 'small' model for better accuracy
  python talktype.py --hotkey f8         # Use F8 instead of F9
  python talktype.py --setup             # Run setup wizard
        """
    )
    parser.add_argument(
        "--api", "-a",
        default=api_default,
        help="Whisper API URL (if not set, uses local faster-whisper)"
    )
    parser.add_argument(
        "--api-model",
        default=trans.get("api_model"),
        help=f"Model name for OpenAI-compatible APIs (default: {trans.get('api_model') or 'whisper-1'})"
    )
    parser.add_argument(
        "--model", "-m",
        default=trans.get("model", DEFAULT_MODEL),
        help=f"Whisper model size: tiny, base, small, medium, large-v3 (default: {DEFAULT_MODEL})"
    )
    parser.add_argument(
        "--record-mode",
        choices=MODES,
        default=hotkeys.get("record_mode", "toggle"),
        help="toggle: press to start, press to stop (default); hold: hold to talk; "
             "auto: tap to toggle, hold at least --hold-ms to talk"
    )
    parser.add_argument(
        "--hold-ms",
        type=int,
        default=hotkeys.get("hold_ms", 500),
        help="In auto mode, how long the record key must be held to stop on release "
             "(default: 500)"
    )
    parser.add_argument(
        "--hotkey", "-k",
        default=hotkeys.get("record", "f9"),
        help="Hotkey to use (default: f9). Examples: f10, pause, scroll_lock, menu"
    )
    parser.add_argument(
        "--language", "-l",
        default=trans.get("language"),
        help="Language code for transcription (default: auto-detect)"
    )
    parser.add_argument(
        "--stream",
        action=argparse.BooleanOptionalAction,
        default=trans.get("streaming", False),
        help="Type words while you are still speaking (local model only)"
    )
    parser.add_argument(
        "--cpu-threads",
        type=int,
        default=trans.get("cpu_threads", min(8, os.cpu_count() or 4)),
        help="CPU threads for the local model (default: up to 8; faster-whisper alone uses 4)"
    )
    parser.add_argument(
        "--stream-engine",
        choices=["whisper", "parakeet", "nemotron"],
        default=trans.get("stream_engine", "whisper"),
        help="Engine for streaming (default: whisper). parakeet and nemotron need their extras; "
             "nemotron streams natively, each chunk decoded once"
    )
    parser.add_argument(
        "--stream-output",
        choices=["auto", "emacs", "kitty", "type", "paste"],
        default=trans.get("stream_output", "auto"),
        help="How streamed words reach the window: auto (default: emacsclient into Emacs, "
             "kitty remote control in kitty, else keystrokes, pasting chunks with non-ASCII "
             "characters), emacs (emacsclient and talktype.el), kitty, "
             "type (keystrokes via xdotool) or paste (clipboard and Ctrl+V per chunk)"
    )
    parser.add_argument(
        "--kitty-socket",
        default=trans.get("kitty_socket", "unix:@kitty"),
        help="kitty's remote-control socket, as set by listen_on in kitty.conf; "
             "{kitty_pid} is filled in from the focused window (default: unix:@kitty)"
    )
    parser.add_argument(
        "--kitten",
        default=trans.get("kitten") or shutil.which("kitten") or "kitten",
        help="Path of kitty's kitten command (default: found on PATH)"
    )
    parser.add_argument(
        "--emacsclient",
        default=trans.get("emacsclient") or shutil.which("emacsclient") or "emacsclient",
        help="Path of the emacsclient command for the emacs route (default: found on PATH)"
    )
    parser.add_argument(
        "--emacs-socket",
        default=trans.get("emacs_socket"),
        help="Emacs server socket name or path, as emacsclient -s takes it "
             "(default: emacsclient's own default)"
    )
    parser.add_argument(
        "--final-engine",
        choices=["whisper", "parakeet", "nemotron"],
        default=trans.get("final_engine"),
        help="Engine for the transcription after you stop (default: the streaming engine "
             "when streaming, else whisper; mixing engines can repeat a word)"
    )
    parser.add_argument(
        "--parakeet-model",
        default=trans.get("parakeet_model", parakeet.DEFAULT_MODEL),
        help=f"onnx-asr model name for --stream-engine parakeet (default: {parakeet.DEFAULT_MODEL})"
    )
    parser.add_argument(
        "--nemotron-model",
        default=trans.get("nemotron_model", nemotron.DEFAULT_MODEL),
        help=f"Hugging Face repo of the Nemotron ONNX export (default: {nemotron.DEFAULT_MODEL})"
    )
    parser.add_argument(
        "--nemotron-threads",
        type=int,
        default=trans.get("nemotron_threads", 4),
        help="CPU threads for Nemotron (default: 4; on laptops with efficiency cores, "
             "more threads were slower)"
    )
    parser.add_argument(
        "--stream-interval",
        type=float,
        default=trans.get("stream_interval", 1.0),
        help="Seconds between re-transcriptions while streaming (default: 1.0)"
    )
    parser.add_argument(
        "--minimal", "-M",
        action="store_true",
        default=ui.get("minimal", False),
        help="Minimal UI - only show status (great for demos)"
    )
    parser.add_argument(
        "--history-limit",
        type=int,
        default=hist.get("limit", 100),
        help="Maximum transcriptions to keep in history (default: 100)"
    )
    # Re-paste and retry take a key away from every window, and are rarely
    # needed (the paste route seldom fails; the local model saves no retry
    # audio for Nemotron), so they are unbound unless configured.
    parser.add_argument(
        "--recovery-hotkey",
        default=hotkeys.get("recovery"),
        help="Hotkey to re-paste the last transcription (default: none)"
    )
    parser.add_argument(
        "--retry-hotkey",
        default=hotkeys.get("retry"),
        help="Hotkey to retry a failed transcription from saved audio (default: none)"
    )
    parser.add_argument(
        "--setup",
        action="store_true",
        help="Run setup wizard (reconfigure settings)"
    )
    args = parser.parse_args()
    # Recovery and retry may stay unbound; recording needs a key.
    if not args.setup and get_hotkey(args.hotkey) is None:
        parser.error("hotkeys.record must name a key, such as f10")
    # bool is an int subclass, so `hold_ms: true` must be caught by name.
    if isinstance(args.hold_ms, bool) or not isinstance(args.hold_ms, int) or args.hold_ms < 0:
        parser.error(f"hotkeys.hold_ms must be a whole number of milliseconds >= 0, got {args.hold_ms!r}")
    try:
        args.sounds = parse_sounds(file_config.get("sounds"))
    except ValueError as e:
        print(f"Config error: {e}")
        sys.exit(1)
    return args


# === Dependency Checks ===
def check_dependencies():
    """Verify system dependencies based on OS."""
    if SYSTEM == "Linux":
        missing = []
        for cmd in ("xdotool", "xclip"):
            try:
                subprocess.run(["which", cmd], capture_output=True, check=True)
            except (subprocess.CalledProcessError, FileNotFoundError):
                missing.append(cmd)
        if missing:
            print(f"Missing Linux dependencies: {', '.join(missing)}")
            print(f"Install with: sudo apt install {' '.join(missing)}")
            sys.exit(1)

    # Check microphone
    try:
        devices = sd.query_devices()
        if not any(d['max_input_channels'] > 0 for d in devices):
            print("No microphone detected!")
            sys.exit(1)
    except Exception as e:
        print(f"Audio device error: {e}")
        sys.exit(1)


def load_whisper_model():
    """Load local Whisper model if not using API."""
    global whisper_model
    if config.api:
        # Test API connection
        try:
            health_url = config.api.rsplit('/', 1)[0] + "/health"
            resp = requests.get(health_url, timeout=2)
            info = resp.json()
            print(f"Using Whisper API: model={info.get('default_model', 'unknown')}")
        except:
            print(f"Using Whisper API: {config.api}")
    else:
        try:
            from faster_whisper import WhisperModel
            print(f"Loading Whisper model '{config.model}'... (first run downloads ~150MB)")
            whisper_model = WhisperModel(
                config.model, device="auto", compute_type="auto", cpu_threads=config.cpu_threads
            )
            print("Model loaded.")
            if (config.stream and config.stream_engine == "parakeet") or config.final_engine == "parakeet":
                load_stream_model()
            if (config.stream and config.stream_engine == "nemotron") or config.final_engine == "nemotron":
                load_nemotron()
        except ImportError:
            print("faster-whisper not installed!")
            print("Install with: pip install faster-whisper")
            print("Or use --api flag to connect to a Whisper API server")
            sys.exit(1)


def load_stream_model():
    """Load Parakeet for the streaming passes and/or the final pass."""
    global stream_model
    print(f"Loading Parakeet model '{config.parakeet_model}'... (first run downloads ~640MB)")
    stream_model = parakeet.load(config.parakeet_model, cpu_threads=config.cpu_threads)
    print("Parakeet loaded.")


def load_nemotron():
    """Load Nemotron for native streaming and/or the final pass."""
    global nemotron_engine
    print(f"Loading Nemotron model '{config.nemotron_model}'... (first run downloads ~790MB)")
    nemotron_engine = nemotron.load(config.nemotron_model, cpu_threads=config.nemotron_threads)
    print("Nemotron loaded.")


# === Audio Feedback ===
def beep(freq: float, duration: float, volume: float = 0.12):
    """Play beep without blocking."""
    t = np.linspace(0, duration, int(SAMPLE_RATE * duration), False)
    wave = (volume * np.sin(2 * np.pi * freq * t)).astype(np.float32)
    try:
        sd.play(wave, SAMPLE_RATE)
    except:
        pass  # Ignore audio errors


SOUNDS = ("start", "stop", "success", "error")
# One beep to start and one to stop. "success" (text is in) followed "stop"
# about 0.4 s later and sounded like a double beep; the text appearing says
# as much. "error" stays on: it only plays when something went wrong.
DEFAULT_SOUNDS = {"start": True, "stop": True, "success": False, "error": True}


def parse_sounds(value) -> dict:
    """Which feedback beeps play, from the config's `sounds:` entry.

    None: the defaults (all but "success"); true: all four; false: none; a
    mapping switches single beeps, the rest keep their defaults.
    """
    if value is None:
        return dict(DEFAULT_SOUNDS)
    if isinstance(value, bool):
        return dict.fromkeys(SOUNDS, value)
    if not isinstance(value, dict):
        raise ValueError(f"sounds must be true, false or a mapping of {', '.join(SOUNDS)}")
    unknown = set(value) - set(SOUNDS)
    if unknown:
        raise ValueError(f"unknown sound {', '.join(sorted(unknown))}; use {', '.join(SOUNDS)}")
    return {name: bool(value.get(name, DEFAULT_SOUNDS[name])) for name in SOUNDS}


def sound_on(name: str) -> bool:
    sounds = getattr(config, "sounds", None)
    return sounds is None or sounds.get(name, True)


def beep_start():
    if sound_on("start"):
        beep(880, 0.08)

def beep_stop():
    if sound_on("stop"):
        beep(440, 0.12)

def beep_error():
    if sound_on("error"):
        beep(220, 0.2)

def beep_success():
    if sound_on("success"):
        beep(660, 0.08)


# === Terminal Title (visual status) ===
def set_terminal_title(title: str):
    """Set terminal window title for visual status."""
    # ANSI escape sequence to set terminal title
    sys.stdout.write(f"\033]0;{title}\007")
    sys.stdout.flush()


def show_status(status: str, detail: str = ""):
    """Show status in minimal mode (clears and centers)."""
    if not config.minimal:
        if detail:
            print(f"{status} {detail}")
        else:
            print(status)
        return

    # Clear screen and show centered status
    sys.stdout.write("\033[2J\033[H")  # Clear screen, move to top
    sys.stdout.write("\n" * 8)  # Padding from top
    sys.stdout.write(f"{'─' * 40}\n")
    sys.stdout.write(f"{status:^40}\n")
    if detail:
        # Truncate detail if too long
        detail = detail[:36] + "..." if len(detail) > 36 else detail
        sys.stdout.write(f"{detail:^40}\n")
    sys.stdout.write(f"{'─' * 40}\n")
    sys.stdout.flush()


# === Window Management (OS-specific) ===
def get_active_window():
    """Get the currently focused window identifier."""
    try:
        if SYSTEM == "Linux":
            return subprocess.check_output(
                ["xdotool", "getactivewindow"],
                stderr=subprocess.DEVNULL
            ).strip()
        elif SYSTEM == "Windows":
            import ctypes
            return ctypes.windll.user32.GetForegroundWindow()
        elif SYSTEM == "Darwin":
            script = 'tell application "System Events" to get name of first process whose frontmost is true'
            result = subprocess.check_output(["osascript", "-e", script], stderr=subprocess.DEVNULL)
            return result.strip()
    except:
        return None
    return None


def focus_window(window_id):
    """Focus a specific window."""
    if not window_id:
        return
    try:
        if SYSTEM == "Linux":
            subprocess.run(
                ["xdotool", "windowactivate", "--sync", window_id],
                stderr=subprocess.DEVNULL
            )
        elif SYSTEM == "Windows":
            import ctypes
            ctypes.windll.user32.SetForegroundWindow(window_id)
        elif SYSTEM == "Darwin":
            # macOS: window_id is app name
            script = f'tell application "{window_id.decode()}" to activate'
            subprocess.run(["osascript", "-e", script], stderr=subprocess.DEVNULL)
    except:
        pass


def is_terminal_window(window_id) -> bool:
    """Check if the window is a terminal."""
    try:
        if SYSTEM == "Linux":
            wm_class = subprocess.check_output(
                ["xprop", "-id", window_id, "WM_CLASS"],
                stderr=subprocess.DEVNULL
            ).decode().lower()
            return any(t in wm_class for t in TERMINALS.get("Linux", []))

        elif SYSTEM == "Windows":
            import ctypes
            buffer = ctypes.create_unicode_buffer(256)
            ctypes.windll.user32.GetWindowTextW(window_id, buffer, 256)
            title = buffer.value.lower()
            class_buffer = ctypes.create_unicode_buffer(256)
            ctypes.windll.user32.GetClassNameW(window_id, class_buffer, 256)
            class_name = class_buffer.value
            return any(t.lower() in title or t.lower() in class_name.lower()
                      for t in TERMINALS.get("Windows", []))

        elif SYSTEM == "Darwin":
            # window_id is app name on macOS
            app_name = window_id.decode() if isinstance(window_id, bytes) else str(window_id)
            return any(t.lower() in app_name.lower() for t in TERMINALS.get("Darwin", []))
    except:
        pass
    return False


# === Recording ===
def audio_callback(indata, frames, time_info, status):
    """Accumulate audio chunks."""
    audio_chunks.append(indata.copy())


def start_recording():
    """Start recording from microphone."""
    global stream, audio_chunks, target_window, session
    target_window = get_active_window()
    audio_chunks = []
    stream = sd.InputStream(
        samplerate=SAMPLE_RATE,
        channels=1,
        dtype='float32',
        callback=audio_callback
    )
    stream.start()
    if config.stream:
        session = NemotronSession() if config.stream_engine == "nemotron" else StreamingSession()
    beep_start()
    set_terminal_title("🎤 RECORDING...")
    show_status("🎤 RECORDING", "Press hotkey to stop")


def stop_recording() -> np.ndarray:
    """Stop recording, return audio array."""
    global stream
    if stream:
        stream.stop()
        stream.close()
        stream = None
    beep_stop()
    set_terminal_title("⏳ Transcribing...")
    show_status("⏳ TRANSCRIBING", "Processing speech...")

    if not audio_chunks:
        return np.array([], dtype=np.float32)
    return np.concatenate(audio_chunks).flatten()


# === Transcription ===
# Common Whisper hallucinations on silence/noise
# Phrases that indicate Whisper is hallucinating on silence
HALLUCINATION_PHRASES = [
    "thanks for watching", "thank you for watching", "thanks for listening",
    "thank you for listening", "thank you", "thanks", "subscribe",
    "like and subscribe", "see you next time", "see you later",
    "the end", "silence", "no speech", "inaudible", "[music]", "(music)",
    "please subscribe", "don't forget to subscribe", "hit the bell",
    "leave a comment", "see you in the next", "bye bye", "good bye",
    "take care", "have a nice day", "have a good day", "peace out",
    "cheers", "ciao", "adios", "auf wiedersehen", "さようなら",
    "...", "♪", "music playing", "background noise", "applause",
]
# Single words that are hallucinations when they're the ENTIRE output
HALLUCINATION_WORDS = {
    "you", "i", "so", "uh", "um", "hmm", "huh", "ah", "oh", "bye",
    "goodbye", "thanks", "okay", "ok", "yes", "no", "yeah", "yep",
    "nope", "well", "right", "hey", "hi", "hello", "what", "hm",
}


def is_hallucination(text: str) -> bool:
    """Check if text is likely a Whisper hallucination."""
    t = text.lower().strip()
    if len(t) < 3:
        return True
    # Check if entire text is just a hallucination word
    if t in HALLUCINATION_WORDS:
        return True
    # Check for hallucination phrases in short outputs
    if len(t) < 40:
        return any(phrase in t for phrase in HALLUCINATION_PHRASES)
    return False


def has_speech(audio: np.ndarray, threshold: float = 0.01, segment_ms: int = 50) -> bool:
    """Check if audio contains actual speech using segment-based detection.

    Instead of averaging energy over the entire recording (which dilutes
    short phrases surrounded by silence), this checks if ANY segment
    exceeds the threshold. This catches quick phrases much better.
    """
    segment_samples = int(SAMPLE_RATE * segment_ms / 1000)

    # Check each segment for speech
    for i in range(0, len(audio), segment_samples):
        segment = audio[i:i + segment_samples]
        if len(segment) < segment_samples // 2:
            continue  # Skip tiny trailing segments
        energy = np.sqrt(np.mean(segment ** 2))
        if energy > threshold:
            return True

    return False


def is_openai_api(url: str) -> bool:
    """Check if URL looks like an OpenAI-compatible API."""
    openai_patterns = ["/v1/audio/transcriptions", "/v1/audio/", "openai", "groq", "deepgram"]
    return any(p in url.lower() for p in openai_patterns)


def transcribe_api(wav_buffer: io.BytesIO) -> str:
    """Transcribe using API (supports OpenAI-compatible and custom APIs)."""
    wav_buffer.seek(0)

    if is_openai_api(config.api):
        # OpenAI-compatible API format
        files = {"file": ("audio.wav", wav_buffer, "audio/wav")}
        data = {
            "model": config.api_model or "whisper-1",
            "language": config.language,
            "response_format": "json"
        }
    else:
        # Custom API format (e.g., local faster-whisper server)
        files = {"file": ("audio.wav", wav_buffer, "audio/wav")}
        data = {"language": config.language}

    resp = requests.post(config.api, files=files, data=data, timeout=240)
    resp.raise_for_status()

    # Handle both JSON {"text": "..."} and plain text responses
    try:
        result = resp.json()
        return result.get("text", "").strip()
    except:
        return resp.text.strip()


def transcribe(audio: np.ndarray, tail_from: int = 0) -> str:
    """Transcribe audio to text.

    With Parakeet as final engine, only audio from sample `tail_from` on is
    transcribed: streaming has typed everything before it, and Parakeet's cost
    grows with the audio length. Retry still gets the whole recording.
    """
    if len(audio) < SAMPLE_RATE * 0.5:  # < 500ms
        return ""

    # Check if audio has enough energy (not just silence)
    if not has_speech(audio):
        return ""

    # Convert to int16 WAV
    audio_int16 = (audio * 32767).astype(np.int16)
    wav_buffer = io.BytesIO()
    wavfile.write(wav_buffer, SAMPLE_RATE, audio_int16)

    # Save pending audio BEFORE transcription (for retry on failure)
    if history:
        history.save_pending_audio(wav_buffer)

    wav_buffer.seek(0)

    if config.api:
        text = transcribe_api(wav_buffer)
    elif config.final_engine == "parakeet":
        text = parakeet.transcribe(stream_model, audio[tail_from:])
    elif config.final_engine == "nemotron":
        text = nemotron.transcribe(nemotron_engine, audio, config.language)
    else:
        # Use local model
        wav_buffer.seek(0)
        audio_for_whisper = audio.astype(np.float32)
        segments, _ = whisper_model.transcribe(audio_for_whisper, language=config.language)
        text = " ".join(seg.text for seg in segments).strip()

    # Clear pending audio on success
    if history and text:
        history.clear_pending_audio()

    return text


# === Paste ===
def paste_text(text: str, restore_clipboard: bool = True, debounce: bool = True):
    """Paste text into the target window.

    Streaming pastes several times per recording, so it turns off the
    debounce and restores the clipboard once at the end instead: a delayed
    restore from one paste would otherwise overwrite the next one's text.
    """
    global _last_paste_time

    # Debounce: prevent pasting twice within PASTE_DEBOUNCE_MS
    now = time.time() * 1000
    if debounce and now - _last_paste_time < PASTE_DEBOUNCE_MS:
        if DEBUG_PASTE:
            print(f"[DEBUG] paste_text BLOCKED by debounce (delta={now - _last_paste_time:.0f}ms)")
        return  # Skip duplicate paste
    _last_paste_time = now

    if DEBUG_PASTE:
        import traceback
        print(f"[DEBUG] paste_text called at {now:.0f}ms")
        print(f"[DEBUG] text length: {len(text)}, preview: {text[:50]!r}")
        print(f"[DEBUG] call stack:\n{''.join(traceback.format_stack()[-4:-1])}")

    # Save old clipboard
    try:
        old_clipboard = pyperclip.paste()
    except:
        old_clipboard = None

    # Set new clipboard
    pyperclip.copy(text)
    time.sleep(0.05)

    # Focus original window
    focus_window(target_window)
    time.sleep(0.05)

    # Determine paste shortcut
    is_terminal = is_terminal_window(target_window) if target_window else False

    if SYSTEM == "Linux":
        key = "ctrl+shift+v" if is_terminal else "ctrl+v"
        if DEBUG_PASTE:
            print(f"[DEBUG] xdotool sending: {key} (is_terminal={is_terminal})")
        # Use --clearmodifiers to prevent interference from held modifier keys
        # Use --delay to ensure clean key release
        subprocess.run(["xdotool", "key", "--clearmodifiers", "--delay", "50", key], stderr=subprocess.DEVNULL)
        if DEBUG_PASTE:
            print(f"[DEBUG] xdotool completed")

    elif SYSTEM == "Windows":
        import pyautogui
        if is_terminal:
            # Windows Terminal and modern terminals use Ctrl+V
            pyautogui.hotkey('ctrl', 'v')
        else:
            pyautogui.hotkey('ctrl', 'v')

    elif SYSTEM == "Darwin":
        import pyautogui
        pyautogui.hotkey('command', 'v', interval=0.05)  # 50ms between keys for cold start reliability

    # Restore old clipboard (scale delay by text length to avoid race condition)
    if restore_clipboard and old_clipboard:
        def restore():
            # Base 1.0s + 10ms per 100 chars, capped at 3.0s
            delay = min(3.0, max(1.0, 1.0 + len(text) * 0.0001))
            time.sleep(delay)
            try:
                pyperclip.copy(old_clipboard)
            except:
                pass
        threading.Thread(target=restore, daemon=True).start()


# === Streaming ===
def window_is_kitty(window_id) -> bool:
    """True if the window is a kitty terminal."""
    if SYSTEM != "Linux" or not window_id:
        return False
    try:
        wm_class = subprocess.check_output(
            ["xprop", "-id", window_id, "WM_CLASS"], stderr=subprocess.DEVNULL
        ).decode().lower()
    except Exception:
        return False
    return "kitty" in wm_class


def window_pid(window_id) -> int | None:
    """The process ID behind a window (_NET_WM_PID), if the window has one."""
    try:
        out = subprocess.check_output(
            ["xprop", "-id", window_id, "_NET_WM_PID"], stderr=subprocess.DEVNULL
        ).decode()
        return int(out.rsplit("=", 1)[1])
    except Exception:
        return None


def kitty_socket() -> str:
    """kitty's socket, with {kitty_pid} filled in from the focused window.

    kitty appends its PID to a listen_on path unless the path contains
    {kitty_pid}, so the socket name changes with every kitty start;
    `listen_on unix:${XDG_RUNTIME_DIR}/kitty-{kitty_pid}.sock` plus the same
    template here finds the right one, also with several kitty instances.
    """
    template = config.kitty_socket
    if "{kitty_pid}" not in template:
        return template
    return template.replace("{kitty_pid}", str(window_pid(target_window)))


def kitty_reachable() -> bool:
    """True if kitty answers on its remote-control socket."""
    try:
        done = subprocess.run([config.kitten, "@", "--to", kitty_socket(), "ls"],
                              stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=2)
    except Exception:
        return False
    return done.returncode == 0


def window_is_emacs(window_id) -> bool:
    """True if the window is a GUI Emacs frame (WM_CLASS "emacs", "Emacs")."""
    if SYSTEM != "Linux" or not window_id:
        return False
    try:
        wm_class = subprocess.check_output(
            ["xprop", "-id", window_id, "WM_CLASS"], stderr=subprocess.DEVNULL
        ).decode().lower()
    except Exception:
        return False
    return "emacs" in wm_class


def lisp_string(text: str) -> str:
    """text as an Emacs Lisp string literal, in plain ASCII.

    Inside a Lisp string only \\ and " are special, so the transcript stays
    data whatever it contains. Newlines, control and non-ASCII characters
    become \\n, \\uXXXX or \\UXXXXXXXX escapes: the expression emacsclient
    carries is then ASCII, independent of either side's locale.
    """
    out = []
    for ch in text:
        if ch in '\\"':
            out.append("\\" + ch)
        elif " " <= ch <= "~":
            out.append(ch)
        elif ch == "\n":
            out.append("\\n")
        elif ord(ch) <= 0xFFFF:
            out.append(f"\\u{ord(ch):04x}")
        else:
            out.append(f"\\U{ord(ch):08x}")
    return '"' + "".join(out) + '"'


def emacsclient(expr: str, capture: bool = False) -> subprocess.CompletedProcess | None:
    """Evaluate expr in the Emacs server; None if emacsclient could not run."""
    cmd = [config.emacsclient]
    if config.emacs_socket:
        cmd += ["-s", config.emacs_socket]
    cmd += ["--eval", expr]
    try:
        return subprocess.run(cmd, stdout=subprocess.PIPE if capture else subprocess.DEVNULL,
                              stderr=subprocess.DEVNULL, timeout=2)
    except (OSError, subprocess.TimeoutExpired):
        return None


def emacs_call(function: str, *args: str) -> bool:
    """Call a talktype.el function with string arguments; True if it succeeded."""
    expr = "(" + " ".join([function, *map(lisp_string, args)]) + ")"
    done = emacsclient(expr)
    return done is not None and done.returncode == 0


def emacs_server_pid() -> int | None:
    """The process ID of the Emacs server emacsclient reaches, None if none answers."""
    done = emacsclient("(emacs-pid)", capture=True)
    if done is None or done.returncode != 0:
        return None
    try:
        return int(done.stdout)
    except (TypeError, ValueError):
        return None


def kitty_foreground_processes() -> list[dict]:
    """The foreground processes of the focused kitty window, from `kitten @ ls`."""
    try:
        # nosemgrep: python.lang.security.audit.dangerous-subprocess-use-audit
        # List argv, no shell: kitten and the socket come from the user's own
        # config, "ls" is constant, and nothing of the transcript is passed.
        done = subprocess.run([config.kitten, "@", "--to", kitty_socket(), "ls"],
                              stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, timeout=2)
        os_windows = json.loads(done.stdout)
    except Exception:
        return []
    for os_window in os_windows if isinstance(os_windows, list) else []:
        for tab in os_window.get("tabs", []):
            for window in tab.get("windows", []):
                if window.get("is_focused"):
                    return window.get("foreground_processes", [])
    return []


def emacsclient_socket(cmdline: list[str]) -> str:
    """The server socket name an emacsclient command line connects to.

    Names and paths compare by their last part, emacsclient's default is
    "server", and a TCP server file (-f) never matches a socket.
    """
    args = iter(cmdline[1:])
    for arg in args:
        if arg in ("-s", "--socket-name"):
            return os.path.basename(next(args, "") or "server")
        if arg.startswith("--socket-name="):
            return os.path.basename(arg.split("=", 1)[1])
        if arg.startswith("-s") and not arg.startswith("--"):
            return os.path.basename(arg[2:])
        if arg in ("-f", "--server-file") or arg.startswith(("-f", "--server-file=")):
            return ""
    return "server"


def emacs_targeted() -> bool:
    """True if the focused window shows the Emacs that emacsclient reaches.

    That is a GUI frame of the server's process, or a kitty window running
    `emacsclient -nw` on the same socket, or `emacs -nw` as the server itself.
    An Emacs without a server, or with another one, is not reached this way.
    """
    if window_is_emacs(target_window):
        server = emacs_server_pid()
        pid = window_pid(target_window)
        return server is not None and (pid is None or pid == server)
    if not window_is_kitty(target_window):
        return False
    processes = kitty_foreground_processes()
    names = [os.path.basename((p.get("cmdline") or [""])[0]) for p in processes]
    if not any(n.startswith("emacs") for n in names):
        return False
    server = emacs_server_pid()
    if server is None:
        return False
    ours = os.path.basename(config.emacs_socket or "server")
    return any(p.get("pid") == server
               or (n.startswith("emacsclient")
                   and emacsclient_socket(p.get("cmdline") or []) == ours)
               for p, n in zip(processes, names))


def choose_route() -> str:
    """Decide once per recording how streamed words reach the window.

    kitty: `kitten @ send-text` writes into the focused kitty window's
        terminal. No clipboard, no synthetic keys, no focus change, and any
        Unicode arrives intact; it needs listen_on in kitty.conf.
    type: xdotool keystrokes. xdotool produces characters missing from the
        keyboard (ü, ß, €) by remapping a spare key, which kitty misses, so
        "type-or-paste" pastes those chunks instead.
    paste: the clipboard and Ctrl+V per chunk, as before. Each chunk means a
        new xclip owning the clipboard, re-activating the window, and in kitty
        a synchronous clipboard read (up to 2 s, stalling all its windows); on
        a GNOME desktop the terminal stayed blocked until recording stopped.
    emacs: `emacsclient --eval` calls into talktype.el, which edits the
        buffer by position. Keys would be commands there (evil normal state,
        minibuffer, isearch). auto picks it for the server's GUI frames and
        for kitty windows running it; emacs picks it whenever a server answers.
    """
    mode = config.stream_output
    if mode in ("type", "paste"):
        return mode
    if mode == "emacs":
        # Without a server, keys would reach a window that may well be Emacs.
        return "emacs" if emacs_server_pid() is not None else "none"
    if mode == "auto" and emacs_targeted():
        return "emacs"
    if window_is_kitty(target_window) and kitty_reachable():
        return "kitty"
    return "paste" if mode == "kitty" else "type-or-paste"


def stream_write(text: str, route: str) -> bool | None:
    """Put words the streaming session has settled on into the window.

    The emacs route returns whether Emacs took them.
    """
    if route == "none":
        return None
    if route == "emacs":
        # No fallback to keys or Ctrl+V: in Emacs they are commands. The
        # text still reaches the history for the recovery key.
        return emacs_call("talktype-append", text)
    if route == "kitty":
        try:
            # nosemgrep: python.lang.security.audit.dangerous-subprocess-use-audit
            # List argv, no shell, and the text follows "--", so kitten takes
            # it as text and never as options.
            done = subprocess.run(
                [config.kitten, "@", "--to", kitty_socket(), "send-text",
                 "--match", "state:focused", "--", text],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=2)
            if done.returncode == 0:
                return
        except subprocess.TimeoutExpired:
            pass
        route = "paste"
    if route == "type-or-paste":
        route = "type" if text.isascii() else "paste"
    if route == "type" and SYSTEM == "Linux":
        subprocess.run(["xdotool", "type", "--clearmodifiers", "--delay", "4", "--", text],
                       stderr=subprocess.DEVNULL)
    else:
        # In paste mode the session restores the clipboard once at the end;
        # an occasional fallback paste restores it itself.
        paste_text(text, restore_clipboard=config.stream_output != "paste", debounce=False)


def save_clipboard():
    """The clipboard to restore after a recording; only paste mode touches it."""
    if config.stream_output != "paste":
        return None
    try:
        return pyperclip.paste()
    except Exception:
        return None


def transcribe_partial(audio: np.ndarray) -> tuple[list[str], list[float] | None]:
    """Quick transcription used while streaming: words, and their start times
    in seconds if the engine reports them (Parakeet does, Whisper here not)."""
    if config.stream_engine == "parakeet":
        return parakeet.transcribe_words(stream_model, audio)
    segments, _ = whisper_model.transcribe(
        audio.astype(np.float32), language=config.language, beam_size=1
    )
    return " ".join(seg.text for seg in segments).split(), None


class StreamingSession:
    """Types the words Whisper has settled on while recording continues.

    Every config.stream_interval seconds the recording so far is transcribed
    again, and the words two consecutive transcripts agree on are pasted.
    When recording stops, the final transcript supplies whatever is missing.

    With word start times (Parakeet), audio up to the start of the sentence
    after the last typed sentence end is dropped from later passes. Parakeet's
    cost grows with the audio length, so without this a pass would take 3 s
    after 18 s of speech; with it, passes stay about as long as a sentence.
    """

    def __init__(self):
        self.typed: list[str] = []  # words already pasted, in order
        self._previous: list[str] = []
        self.window: list[str] = []  # typed words still inside the audio window
        self.offset = 0  # samples before the window, already typed
        self._stop = threading.Event()
        self.clipboard = save_clipboard()
        self.route = None  # chosen on the first write, not in the hotkey callback
        self.emacs_open = False  # talktype-begin succeeded, talktype-end pending
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def _run(self):
        # The interval runs from the start of one pass to the start of the
        # next, so a slow pass does not add a full interval of waiting.
        next_pass = time.monotonic() + config.stream_interval
        while not self._stop.wait(max(0.0, next_pass - time.monotonic())):
            next_pass = time.monotonic() + config.stream_interval
            chunks = list(audio_chunks)
            if not chunks:
                continue
            audio = np.concatenate(chunks).flatten()[self.offset:]
            if len(audio) < SAMPLE_RATE or not has_speech(audio):
                continue
            try:
                current, starts = transcribe_partial(audio)
            except Exception:
                continue
            stable = streaming.stable_prefix(self._previous, current)
            self._previous = current
            # Whisper invents "Thank you." and the like on near-silence; only
            # the first words need the check, later ones follow real speech.
            if not self.typed and is_hallucination(" ".join(stable)):
                continue
            new = streaming.remainder(self.window, stable)
            if new:
                self.write(" " + " ".join(new))
                self.typed.extend(new)
                self.window.extend(new)
                show_status("📝 TYPING", " ".join(new)[:50])
            cut = streaming.sentence_cut(stable)
            if starts and 0 < cut < len(current):
                self.offset += int(starts[cut] * SAMPLE_RATE)
                self.window = stable[cut:]
                self._previous = current[cut:]

    def stop(self):
        """Stop re-transcribing, after the pass in progress."""
        self._stop.set()
        self._thread.join()

    def write(self, text: str):
        """Deliver words by the route chosen on the first write of this recording."""
        if self.route is None:
            self.route = choose_route()
            if self.route == "emacs":
                self.emacs_open = emacs_call("talktype-begin")
                if not self.emacs_open:
                    # Emacs refused (read-only buffer, minibuffer, isearch) or
                    # talktype.el is not loaded; typing keys there would run
                    # commands, so this recording writes nothing.
                    self.route = "none"
        if stream_write(text, self.route) is False:
            # Emacs stopped taking words (server gone, buffer killed or made
            # read-only). Later words would leave a gap, so none follow.
            self.route = "none"
            show_status("⚠️ EMACS", "Stopped writing; the text is in the history")

    def end(self, attempts: int = 3):
        """Close the Emacs dictation region, if this recording opened one.

        A server that stays away keeps the region open; the next
        talktype-begin closes it.
        """
        if not self.emacs_open:
            return
        for attempt in range(attempts):
            if attempt:
                time.sleep(0.5)
            if emacs_call("talktype-end"):
                self.emacs_open = False
                return
        show_status("⚠️ EMACS", "Could not close the dictation region")

    def restore_clipboard(self):
        """Put back the clipboard from before the recording."""
        if self.clipboard is None:
            return
        def restore():
            time.sleep(1.0)  # let the last paste read the clipboard first
            try:
                pyperclip.copy(self.clipboard)
            except Exception:
                pass
        threading.Thread(target=restore, daemon=True).start()


class NemotronSession:
    """Types Nemotron's words as each chunk (560 ms) is decoded.

    The model keeps its state from chunk to chunk, so every chunk is decoded
    once and its words are final: no re-transcription and no agreement step.
    Pasting (about 0.4 s with focus and xdotool) runs in a thread of its own,
    so decoding keeps pace with speech while earlier words are being pasted.
    """

    def __init__(self):
        # Created in _run: setting up the stream decodes a lead-in chunk of
        # silence (~0.5 s), and __init__ runs in the hotkey callback, where it
        # would delay the start beep and block the keyboard listener.
        self._stream = None
        self.text = ""  # everything decoded in this recording
        self._fed = 0  # entries of audio_chunks already fed to the model
        self._stop = threading.Event()
        self._queue: queue.Queue[str | None] = queue.Queue()
        self.clipboard = save_clipboard()
        self.route = None  # chosen on the first write, not in the hotkey callback
        self.emacs_open = False  # talktype-begin succeeded, talktype-end pending
        self._paster = threading.Thread(target=self._paste_loop, daemon=True)
        self._paster.start()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def _run(self):
        # Audio keeps collecting in audio_chunks meanwhile; nothing is lost.
        self._stream = nemotron.Stream(nemotron_engine, config.language)
        while not self._stop.wait(0.05):
            self._feed_new()

    def _feed_new(self):
        chunks = audio_chunks[self._fed:]
        self._fed += len(chunks)
        if chunks:
            self._emit(self._stream.feed(np.concatenate(chunks).flatten()))

    def _emit(self, text: str):
        if not text:
            return
        if not self.text:
            text = " " + text.lstrip()  # space to separate from previous
        self.text += text
        self._queue.put(text)

    def _paste_loop(self):
        done = False
        while not done:
            parts = [self._queue.get()]
            # Paste everything that queued up while the last paste ran.
            while not self._queue.empty():
                parts.append(self._queue.get())
            if None in parts:
                done = True
                parts = parts[:parts.index(None)]
            if parts:
                text = "".join(parts)
                self.write(text)
                show_status("📝 TYPING", text.strip()[:50])

    def finish(self) -> str:
        """Recording stopped: decode and paste the rest; return all text."""
        self._stop.set()
        self._thread.join()
        self._feed_new()
        self._emit(self._stream.flush())
        self._queue.put(None)
        self._paster.join()
        return self.text.strip()

    # Same clipboard handling as the re-transcribing session.
    restore_clipboard = StreamingSession.restore_clipboard
    write = StreamingSession.write
    end = StreamingSession.end


# === Main Logic ===
def transcribe_and_paste(audio: np.ndarray, live: StreamingSession | NemotronSession | None = None):
    """Background thread: transcribe and paste.

    With a streaming session, part of the text is already on screen; only the
    words after it are pasted.
    """
    global state
    try:
        if isinstance(live, NemotronSession):
            # Everything decoded is final; only the last chunk is missing.
            text = live.finish()
            if text:
                if history:
                    history.add(text)
                beep_success()
                set_terminal_title("TalkType ✅")
                show_status("✅ DONE", text[:50])
            else:
                beep_error()
                set_terminal_title("TalkType")
                show_status("❌ NO SPEECH", "Nothing detected")
            return
        if live:
            live.stop()
        tail = bool(live) and live.offset > 0 and config.final_engine == "parakeet"
        text = transcribe(audio, tail_from=live.offset if tail else 0)
        on_screen = live.typed if live else []
        typed = live.window if tail else on_screen
        if on_screen or (text and not is_hallucination(text)):
            rest = streaming.remainder(typed, text.split())
            if rest:
                # Space to separate from previous
                if live:
                    live.write(" " + " ".join(rest))
                else:
                    paste_text(" " + " ".join(rest))
            if live:
                text = " ".join(on_screen + rest)  # what the window shows, for F11
            # Save to history for recovery
            if history:
                history.add(text)
            beep_success()
            set_terminal_title("TalkType ✅")
            show_status("✅ DONE", text[:50])
        else:
            beep_error()
            set_terminal_title("TalkType")
            show_status("❌ NO SPEECH", "Nothing detected")
            # Clear pending audio - no point retrying silence
            if history:
                history.clear_pending_audio()
    except Exception as e:
        beep_error()
        set_terminal_title("TalkType ❌")
        show_status("❌ FAILED", str(e)[:50])
        # Keep pending audio for retry - don't clear it
    finally:
        if live:
            live.end()
            live.restore_clipboard()
        with state_lock:
            state = State.IDLE
        # Reset to ready after a moment
        time.sleep(1.5)
        set_terminal_title("TalkType - Ready")
        show_status("● READY", record_prompt(config))


def get_hotkey(key_name: str | None):
    """Convert a pynput key name (f1-f20, pause, scroll_lock, menu, ...) to a key.

    Keys a terminal does not forward, such as pause or menu, avoid clashing
    with programs that bind function keys (byobu, mc, htop). None, an empty
    name, "none" or "null" leave the action unbound.
    """
    name = (key_name or "").lower().strip()
    if name in ("", "none", "null"):
        return None
    key = getattr(keyboard.Key, name, None)
    if not isinstance(key, keyboard.Key):
        print(f"Unknown hotkey {key_name!r}. Use a key name such as f9, pause, scroll_lock or menu.")
        sys.exit(1)
    return key


def record_prompt(config) -> str:
    """How to record, in the words of the record mode."""
    key = config.hotkey.upper()
    return {"toggle": f"Press {key} to record",
            "hold": f"Hold {key} to talk",
            "auto": f"Tap {key} to record, or hold it to talk"}[getattr(config, "record_mode", "toggle")]


def ready_message(config) -> str:
    """The start-up line, naming only the actions that have a key."""
    mode = getattr(config, "record_mode", "toggle")
    first = record_prompt(config)
    others = [f"{k.upper()} to {what}"
              for k, what in ((config.recovery_hotkey, "recover"), (config.retry_hotkey, "retry"))
              if get_hotkey(k)]
    if not others:
        return f"Ready! {first}."
    return f"Ready! {first}, {'' if mode == 'toggle' else 'press '}{', '.join(others)}."


def create_hotkey_handler(hotkey, record_key: RecordKey):
    """Create the record key's press and release handlers.

    record_key decides from the mode (toggle, hold, auto) whether a press or
    a release starts or stops recording.
    """
    def stop():
        """Stop recording and transcribe in the background; state_lock held."""
        global state, session
        state = State.TRANSCRIBING
        audio = stop_recording()
        live, session = session, None
        threading.Thread(
            target=transcribe_and_paste,
            args=(audio, live),
            daemon=True
        ).start()

    def on_press(key):
        global state, _last_hotkey_time
        if key != hotkey:
            return

        # Debounce: ignore rapid key repeats
        now = time.time() * 1000
        if now - _last_hotkey_time < HOTKEY_DEBOUNCE_MS:
            return
        _last_hotkey_time = now

        with state_lock:
            if state == State.TRANSCRIBING:
                return
            action = record_key.press(time.monotonic(), state == State.RECORDING)
            if action == "start":
                state = State.RECORDING
                start_recording()
            elif action == "stop":
                stop()

    def on_release(key):
        if key != hotkey:
            return
        with state_lock:
            if record_key.release(time.monotonic(), state == State.RECORDING) == "stop":
                stop()

    return on_press, on_release


def create_recovery_handler(recovery_key):
    """Create the recovery hotkey handler (re-paste last transcription)."""
    def on_press(key):
        global target_window
        if key != recovery_key:
            return

        with state_lock:
            if state != State.IDLE:
                return  # Only recover when idle

        if not history:
            beep_error()
            return

        last_text = history.get_last()
        if not last_text:
            beep_error()
            show_status("❌ NO HISTORY", "Nothing to recover")
            return

        # Store the current window so we know where to paste back
        target_window = get_active_window()

        # Re-paste the last transcription
        paste_text(" " + last_text)
        beep_success()
        set_terminal_title("TalkType ↩️")
        show_status("↩️ RECOVERED", last_text[:50])

    return on_press


def create_retry_handler(retry_key):
    """Create the retry hotkey handler (re-transcribe from saved audio)."""
    def on_press(key):
        global target_window
        if key != retry_key:
            return

        with state_lock:
            if state != State.IDLE:
                return  # Only retry when idle

        if not history:
            beep_error()
            return

        pending = history.get_pending_audio()
        if not pending:
            beep_error()
            show_status("❌ NO PENDING", "Nothing to retry")
            return

        # Store the current window so we know where to paste back
        target_window = get_active_window()

        # Re-transcribe from saved WAV
        set_terminal_title("TalkType 🔄")
        show_status("🔄 RETRYING", "Re-transcribing...")

        try:
            wav_buffer = io.BytesIO(pending)
            if config.api:
                text = transcribe_api(wav_buffer)
            else:
                # Load audio from WAV for local transcription
                wav_buffer.seek(0)
                # Skip WAV header (44 bytes) and convert to float32
                audio = np.frombuffer(wav_buffer.read()[44:], dtype=np.int16).astype(np.float32) / 32767
                segments, _ = whisper_model.transcribe(audio, language=config.language)
                text = " ".join(seg.text for seg in segments).strip()

            if text and not is_hallucination(text):
                paste_text(" " + text)
                if history:
                    history.add(text)
                    history.clear_pending_audio()
                beep_success()
                set_terminal_title("TalkType ✅")
                show_status("✅ RETRIED", text[:50])
            else:
                beep_error()
                show_status("❌ NO SPEECH", "")
                if history:
                    history.clear_pending_audio()
        except Exception as e:
            beep_error()
            set_terminal_title("TalkType ❌")
            show_status("❌ RETRY FAILED", str(e)[:30])
            # Keep pending audio for another retry attempt

    return on_press


class _WindowsLock:
    def __init__(self, handle):
        self._handle = handle

    def close(self):
        import ctypes
        if self._handle:
            ctypes.windll.kernel32.CloseHandle(self._handle)
            self._handle = None


def acquire_instance_lock():
    """Ensure only one instance of TalkType runs at a time."""
    lock_file = Path.home() / ".cache" / "talktype" / "talktype.lock"
    lock_file.parent.mkdir(parents=True, exist_ok=True)

    if SYSTEM == "Windows":
        import ctypes
        handle = ctypes.windll.kernel32.CreateMutexW(None, True, "TalkTypeSingleInstance")
        if ctypes.windll.kernel32.GetLastError() == 183:  # ERROR_ALREADY_EXISTS
            try:
                with open(lock_file, 'r') as f:
                    pid = f.read().strip()
                print(f"TalkType is already running (PID {pid})")
            except Exception:
                print("TalkType is already running")
            ctypes.windll.kernel32.CloseHandle(handle)
            sys.exit(1)
        try:
            with open(lock_file, 'w') as f:
                f.write(str(os.getpid()))
        except Exception:
            pass
        return _WindowsLock(handle)
    else:
        import fcntl
        lock_fd = open(lock_file, 'w')
        try:
            fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            lock_fd.write(str(os.getpid()))
            lock_fd.flush()
            return lock_fd
        except BlockingIOError:
            try:
                with open(lock_file, 'r') as f:
                    pid = f.read().strip()
                print(f"TalkType is already running (PID {pid})")
            except Exception:
                print("TalkType is already running")
            sys.exit(1)


def main():
    global config, history

    # Ensure single instance
    lock_fd = acquire_instance_lock()
    atexit.register(lambda: lock_fd.close())

    # Check for first run or --setup flag. The wizard needs a terminal, so it
    # is skipped for --help and when started without one (e.g. by systemd).
    wants_help = any(arg in ("-h", "--help") for arg in sys.argv[1:])
    first_run = not CONFIG_PATH.exists() and sys.stdin.isatty() and not wants_help
    if "--setup" in sys.argv or first_run:
        try:
            from setup_wizard import run_wizard
            result = run_wizard()
            # run_wizard returns (config, should_run)
            if isinstance(result, tuple):
                _, should_run = result
                if not should_run:
                    sys.exit(0)
        except ImportError:
            print("Setup wizard not available. Using defaults.")
        except KeyboardInterrupt:
            print("\nSetup cancelled.")
            sys.exit(0)

    config = parse_args()
    if config.stream and config.api:
        print("Streaming needs the local model; ignoring --stream with --api.")
        config.stream = False
    if config.final_engine is None:
        config.final_engine = config.stream_engine if config.stream else "whisper"
    history = TranscriptionHistory(max_entries=config.history_limit)

    print("TalkType - Voice Typing for Your Terminal")
    print("=" * 45)
    print(f"System: {SYSTEM}")
    if config.stream and config.stream_engine == "nemotron":
        print("Streaming: types while you speak (nemotron, each chunk decoded once)")
    elif config.stream:
        print(f"Streaming: types while you speak, every {config.stream_interval:g} s ({config.stream_engine})")

    check_dependencies()
    load_whisper_model()

    hotkey = get_hotkey(config.hotkey)
    recovery_key = get_hotkey(config.recovery_hotkey)
    retry_key = get_hotkey(config.retry_hotkey)
    set_terminal_title("TalkType - Ready")

    if config.minimal:
        show_status("● READY", record_prompt(config))
    else:
        print(f"\n{ready_message(config)}")
        print("Press Ctrl+C to exit.\n")

    # Create handlers for all hotkeys
    record_handler, record_release = create_hotkey_handler(
        hotkey, RecordKey(config.record_mode, config.hold_ms / 1000)
    )
    recovery_handler = create_recovery_handler(recovery_key)
    retry_handler = create_retry_handler(retry_key)

    # Holding a hotkey makes X repeat its press; without the gate a held F9
    # would start and stop recording over and over.
    gate = PressGate()

    def combined_handler(key):
        if not gate.press(key):
            return
        record_handler(key)
        recovery_handler(key)
        retry_handler(key)

    # Use signal handler for clean Ctrl+C exit
    import signal
    def signal_handler(sig, frame):
        print("\nBye!")
        sys.exit(0)
    signal.signal(signal.SIGINT, signal_handler)

    def combined_release(key):
        gate.release(key)
        record_release(key)

    with keyboard.Listener(on_press=combined_handler, on_release=combined_release) as listener:
        listener.join()


if __name__ == "__main__":
    main()
