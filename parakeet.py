"""NVIDIA Parakeet TDT as a local transcription engine, through onnx-asr.

Parakeet is a FastConformer transducer. On a laptop CPU it transcribes a
few seconds of audio several times faster than faster-whisper, which is what
streaming needs: every pass re-reads the whole recording so far.

`parakeet-tdt-0.6b-v3` covers English and 24 other European languages,
German among them, and detects the language itself. Installed with the
optional extra `talktype[parakeet]`; the model (about 640 MB with int8
weights) is downloaded from Hugging Face on first use.
"""

import numpy as np

DEFAULT_MODEL = "nemo-parakeet-tdt-0.6b-v3"
SAMPLE_RATE = 16000


def load(
    model: str = DEFAULT_MODEL, quantization: str | None = "int8", cpu_threads: int = 0
):
    """Load a Parakeet model; cpu_threads 0 leaves the choice to onnxruntime."""
    try:
        import onnx_asr
        import onnxruntime as rt
    except ImportError:
        raise SystemExit(
            "The parakeet engine needs the 'parakeet' extra: "
            "uv tool install 'talktype[local,parakeet] @ ...'"
        )
    options = rt.SessionOptions()
    if cpu_threads:
        options.intra_op_num_threads = cpu_threads
    asr = onnx_asr.load_model(model, quantization=quantization, sess_options=options)
    return asr.with_timestamps()


def transcribe(model, audio: np.ndarray) -> str:
    """Transcribe 16 kHz mono float32 audio."""
    return _recognize(model, audio).text.strip()


def transcribe_words(model, audio: np.ndarray) -> tuple[list[str], list[float]]:
    """Transcribe audio into words and the time (s) at which each one starts."""
    result = _recognize(model, audio)
    return group_words(result.tokens, result.timestamps)


def group_words(tokens: list[str], timestamps: list[float]) -> tuple[list[str], list[float]]:
    """Join subword tokens into words; a token with a leading space starts one."""
    words: list[str] = []
    starts: list[float] = []
    for token, at in zip(tokens, timestamps):
        if token.startswith(" ") or not words:
            words.append(token.strip())
            starts.append(at)
        else:
            words[-1] += token
    return words, starts


def _recognize(model, audio: np.ndarray):
    return model.recognize(audio.astype(np.float32), sample_rate=SAMPLE_RATE)
