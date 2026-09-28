"""NVIDIA Nemotron 3.5 ASR Streaming as a natively streaming engine.

Whisper and Parakeet TDT are offline models: to type while you speak they
must transcribe the recording again and again, and a word appears only once
two passes agree. Nemotron's encoder is cache-aware: it keeps its state from
one 560 ms chunk to the next, so every chunk is computed once and the new
words come out right away. No re-transcription, no agreement step.

Runs on the CPU through onnxruntime-genai (optional extra
`talktype[nemotron]`), which handles the encoder caches and the RNN-T
decoding. The INT4 ONNX export (about 790 MB) is downloaded from Hugging
Face on first use. 40 locales, German and English among them.
"""

import json
import re

import numpy as np

DEFAULT_MODEL = "onnx-community/nemotron-3.5-asr-streaming-0.6b-onnx-int4"
SAMPLE_RATE = 16000

# The model's language-prompt slots (from onnxruntime-genai's ASR example,
# which follows the model's prompt dictionary), for TalkType's --language
# codes. Anything else, or no language, means auto-detect.
LANG_IDS = {
    "en": 0,
    "es": 3,
    "zh": 4,
    "hi": 6,
    "ar": 7,
    "fr": 8,
    "de": 9,
    "ja": 10,
    "ru": 11,
    "pt": 13,
    "ko": 14,
    "it": 15,
    "nl": 16,
    "pl": 17,
    "tr": 18,
    "uk": 19,
    "ro": 20,
    "el": 21,
    "cs": 22,
    "hu": 23,
    "sv": 24,
    "da": 25,
    "fi": 26,
    "sk": 28,
    "hr": 29,
    "bg": 30,
    "vi": 33,
}
AUTO = 101

# The model prefixes detected-language segments with a tag like "<en-US>".
_LANG_TAG = re.compile(r"\s*<[a-z]{2}(?:-[A-Z]{2})?>")


def lang_id(language: str | None) -> int:
    """Map a language code such as "de" or "en-GB" to a prompt slot."""
    if not language:
        return AUTO
    return LANG_IDS.get(language.lower().split("-")[0], AUTO)


def strip_tags(text: str) -> str:
    """Remove the language tags the model writes into its output."""
    return _LANG_TAG.sub("", text)


class Engine:
    """A loaded model; cheap Streams are made from it per recording."""

    def __init__(self, model_dir: str, cpu_threads: int):
        try:
            import onnxruntime_genai as og
        except ImportError:
            raise SystemExit(
                "The nemotron engine needs the 'nemotron' extra: "
                "uv tool install 'talktype[local,nemotron] @ ...'"
            )
        self.og = og
        config = og.Config(model_dir)
        config.clear_providers()  # CPU
        if cpu_threads:
            options = {"intra_op_num_threads": cpu_threads, "inter_op_num_threads": 1}
            config.overlay(
                json.dumps(
                    {
                        "model": {
                            part: {"session_options": options}
                            for part in ("encoder", "decoder", "joiner")
                        }
                    }
                )
            )
        self.model = og.Model(config)
        self.tokenizer = og.Tokenizer(self.model)
        with open(f"{model_dir}/genai_config.json") as f:
            self.chunk_samples = json.load(f)["model"]["chunk_samples"]


def load(model: str = DEFAULT_MODEL, cpu_threads: int = 4) -> Engine:
    """Download (first use) and load the model.

    cpu_threads defaults to 4: on a laptop with 2 performance cores and 8
    efficiency cores (i7-1255U) a chunk took 320 ms with 4 threads, 850 ms
    with 8 and 1280 ms with 12; the slow cores hold the fast ones back.
    """
    from huggingface_hub import snapshot_download

    model_dir = snapshot_download(
        model, allow_patterns=["*.json", "*.onnx", "*.onnx.data", "vocab.txt"]
    )
    return Engine(model_dir, cpu_threads)


class Stream:
    """One recording: feed audio as it arrives, get the new text back."""

    def __init__(self, engine: Engine, language: str | None = None):
        og = engine.og
        self.chunk = engine.chunk_samples
        self._processor = og.StreamingProcessor(engine.model)
        self._processor.set_option("use_vad", "false")
        self._generator = og.Generator(engine.model, og.GeneratorParams(engine.model))
        self._generator.set_runtime_option("lang_id", str(lang_id(language)))
        self._tokens = engine.tokenizer.create_stream()
        self._pending = np.zeros(0, dtype=np.float32)
        # Without a lead-in of silence the first seconds of speech are lost
        # (measured: "Hey, I need help with an order" missing from a clip
        # that starts with speech); 0.28 s was enough, one chunk is used.
        self._run(np.zeros(self.chunk, dtype=np.float32))

    def feed(self, audio: np.ndarray) -> str:
        """Add audio; returns the text of every chunk completed by it."""
        self._pending = np.concatenate(
            [self._pending, audio.astype(np.float32).ravel()]
        )
        text = ""
        while len(self._pending) >= self.chunk:
            text += self._run(self._pending[: self.chunk])
            self._pending = self._pending[self.chunk :]
        return text

    def flush(self) -> str:
        """End of recording: returns the text of the audio still buffered."""
        text = ""
        if len(self._pending):
            text += self._run(self._pending)
            self._pending = np.zeros(0, dtype=np.float32)
        text += self._decode(self._processor.flush())
        return text

    def _run(self, chunk: np.ndarray) -> str:
        return self._decode(self._processor.process(chunk))

    def _decode(self, inputs) -> str:
        if inputs is None:
            return ""
        self._generator.set_inputs(inputs)
        text = ""
        while not self._generator.is_done():
            self._generator.generate_next_token()
            tokens = self._generator.get_next_tokens()
            if len(tokens) > 0:
                text += self._tokens.decode(tokens[0])
        return strip_tags(text)


def transcribe(engine: Engine, audio: np.ndarray, language: str | None = None) -> str:
    """Transcribe a whole recording at once (the non-streaming path)."""
    stream = Stream(engine, language)
    return (stream.feed(audio) + stream.flush()).strip()
