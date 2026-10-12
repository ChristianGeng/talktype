"""Which engines run, given the configured ones and the extras installed.

An engine whose extra is missing used to stop TalkType at start, and as a
systemd service it then restarted every 5 s. `choose` falls back to an
installed engine instead (stream: nemotron, else parakeet, else whisper;
final: whisper; nemotron streams only when the final engine is unset or
nemotron, as it runs no final pass of another engine) and words the install command for the missing extras. No
pynput, X11 or audio dependencies; the engines' modules are not imported.
"""

import importlib.util
from collections.abc import Callable, Iterable
from typing import NamedTuple

SOURCE = "git+https://github.com/ChristianGeng/talktype"

# The module each extra brings, in pyproject.toml's order.
EXTRA_MODULE = {
    "local": "faster_whisper",
    "parakeet": "onnx_asr",
    "nemotron": "onnxruntime_genai",
    "server": "fastapi",
}
ENGINE_EXTRA = {"whisper": "local", "parakeet": "parakeet", "nemotron": "nemotron"}
STREAM_FALLBACK = ("nemotron", "parakeet", "whisper")


def installed(extra: str) -> bool:
    """Whether the extra's module can be imported, without importing it."""
    try:
        return importlib.util.find_spec(EXTRA_MODULE[extra]) is not None
    except ValueError:  # imported already, without a __spec__
        return True


def extras(
    engines: Iterable[str], installed: Callable[[str], bool] = installed
) -> list[str]:
    """The extras the engines need plus those installed already.

    `local` is always among them: Whisper is loaded whatever the engines.
    """
    needed = {"local"} | {ENGINE_EXTRA[engine] for engine in engines}
    return [extra for extra in EXTRA_MODULE if extra in needed or installed(extra)]


def install_command(extras: Iterable[str]) -> str:
    return f"uv tool install --force 'talktype[{','.join(extras)}] @ {SOURCE}'"


def whisper_missing(command: str) -> str:
    """Why TalkType cannot run locally without faster-whisper."""
    return (
        "faster-whisper is not installed (the 'local' extra).\n"
        f"Install with: {command}\n"
        "Or use --api to connect to a Whisper API server."
    )


class Choice(NamedTuple):
    stream_engine: str
    final_engine: str
    warning: str | None  # an engine fell back
    error: str | None  # nothing usable is installed


def choose(
    stream: bool,
    stream_engine: str,
    final_engine: str | None,
    installed: Callable[[str], bool] = installed,
) -> Choice:
    """The engines to run with and what to tell the user about them.

    final_engine None is the default: the engine that streams, else whisper.
    The streaming engine matters only with stream on.
    """
    wanted = ([stream_engine] if stream else []) + [final_engine or "whisper"]
    command = install_command(extras(wanted, installed))
    present = {extra for extra in EXTRA_MODULE if installed(extra)}
    if "local" not in present:
        return Choice(stream_engine, final_engine or stream_engine, None, whisper_missing(command))

    notes = []
    if final_engine is not None and ENGINE_EXTRA[final_engine] not in present:
        notes.append(
            f"final_engine {final_engine} needs the '{ENGINE_EXTRA[final_engine]}' "
            "extra, which is not installed; final_engine whisper instead."
        )
        final_engine = "whisper"
    if stream and ENGINE_EXTRA[stream_engine] not in present:
        # NemotronSession has no final pass of another engine, so it only
        # stands in when the final engine is unset or nemotron itself.
        fallback = [e for e in STREAM_FALLBACK if final_engine in (None, "nemotron") or e != "nemotron"]
        used = next(e for e in fallback if ENGINE_EXTRA[e] in present)
        notes.append(
            f"stream_engine {stream_engine} needs the '{ENGINE_EXTRA[stream_engine]}' "
            f"extra, which is not installed; streaming with {used} instead."
        )
        stream_engine = used
    if final_engine is None:
        final_engine = stream_engine if stream else "whisper"
    warning = "\n".join([*notes, f"Install with: {command}"]) if notes else None
    return Choice(stream_engine, final_engine, warning, None)
