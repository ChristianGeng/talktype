"""Start-up with an engine whose extra is missing: warn, beep once, run (#66)."""

import argparse
import importlib.machinery
import os
import sys
import types

import pytest

if not os.environ.get("DISPLAY"):
    pytest.skip(
        "talktype imports pynput, which needs an X display", allow_module_level=True
    )

import engines  # noqa: E402
import talktype as t  # noqa: E402

COMMAND = (
    "uv tool install --force "
    "'talktype[local,parakeet] @ git+https://github.com/ChristianGeng/talktype'"
)


@pytest.fixture
def start(monkeypatch):
    """Configure TalkType with only the given extras importable; collect beeps."""
    beeps = []
    monkeypatch.setattr(t, "beep_error", lambda: beeps.append("error"))

    def configure(installed=("local",), **options):
        settings = {"api": None, "stream": True, "stream_engine": "parakeet",
                    "final_engine": None, "stream_interval": 1.0}
        settings.update(options)
        monkeypatch.setattr(t, "config", argparse.Namespace(**settings), raising=False)
        for extra, module in engines.EXTRA_MODULE.items():
            stub = None  # import fails
            if extra in installed:
                stub = types.ModuleType(module)
                stub.__spec__ = importlib.machinery.ModuleSpec(module, None)
            monkeypatch.setitem(sys.modules, module, stub)
        return beeps

    return configure


def test_a_missing_extra_starts_on_whisper_with_the_command(start, capsys):
    beeps = start()
    warning = t.resolve_engines()
    t.print_banner(warning)
    assert (t.config.stream_engine, t.config.final_engine) == ("whisper", "whisper")
    out = capsys.readouterr().out
    assert "Streaming: types while you speak, every 1 s (whisper)" in out
    assert "Warning: stream_engine parakeet needs the 'parakeet' extra" in out
    assert f"Install with: {COMMAND}" in out
    assert beeps == ["error"]


def test_a_missing_extra_streams_with_nemotron_when_it_is_there(start, capsys):
    beeps = start(installed=("local", "nemotron"))
    t.print_banner(t.resolve_engines())
    assert (t.config.stream_engine, t.config.final_engine) == ("nemotron", "nemotron")
    assert "Streaming: types while you speak (nemotron" in capsys.readouterr().out
    assert beeps == ["error"]


def test_installed_engines_start_without_warning_or_beep(start, capsys):
    beeps = start(installed=("local", "parakeet"))
    t.print_banner(t.resolve_engines())
    assert (t.config.stream_engine, t.config.final_engine) == ("parakeet", "parakeet")
    assert "Warning" not in capsys.readouterr().out
    assert beeps == []


def test_without_faster_whisper_it_exits_with_the_command(start):
    beeps = start(installed=("parakeet",))
    with pytest.raises(SystemExit) as stopped:
        t.resolve_engines()
    assert str(stopped.value).startswith("faster-whisper is not installed")
    assert f"Install with: {COMMAND}" in str(stopped.value)
    assert beeps == []


def test_the_api_needs_no_local_engine(start):
    start(installed=(), api="http://localhost:8002/transcribe", stream=False)
    assert t.resolve_engines() is None
    assert t.config.final_engine == "whisper"


def test_a_failing_faster_whisper_import_names_the_uv_command(start, monkeypatch, capsys):
    start(installed=("local", "parakeet"), stream_engine="parakeet", final_engine="parakeet")
    monkeypatch.setitem(sys.modules, "faster_whisper", None)
    with pytest.raises(SystemExit) as stopped:
        t.load_whisper_model()
    assert f"Install with: {COMMAND}" in str(stopped.value)
    assert "pip" not in str(stopped.value) + capsys.readouterr().out


def fake_whisper(monkeypatch):
    """faster_whisper whose WhisperModel loads nothing."""
    module = types.ModuleType("faster_whisper")
    module.WhisperModel = lambda *args, **kwargs: "whisper"
    monkeypatch.setitem(sys.modules, "faster_whisper", module)


def test_an_engine_import_error_is_not_reported_as_faster_whisper(start, monkeypatch, capsys):
    start(installed=("local", "parakeet"), cpu_threads=1, model="tiny")
    t.resolve_engines()
    fake_whisper(monkeypatch)

    def broken():
        raise ImportError("No module named 'onnxruntime'")

    monkeypatch.setattr(t, "load_stream_model", broken)
    with pytest.raises(ImportError, match="onnxruntime"):
        t.load_whisper_model()
    assert "faster-whisper" not in capsys.readouterr().out


def parse(monkeypatch, transcription):
    monkeypatch.setattr(t, "load_config_file", lambda: {"transcription": transcription})
    monkeypatch.setattr(sys, "argv", ["talktype"])
    return t.parse_args()


@pytest.mark.parametrize("key", ["stream_engine", "final_engine"])
@pytest.mark.parametrize("value", ["parakeat", "Whisper", 3])
def test_an_unknown_engine_in_the_config_is_a_config_error(monkeypatch, capsys, key, value):
    with pytest.raises(SystemExit):
        parse(monkeypatch, {key: value})
    err = capsys.readouterr().err
    assert f"transcription.{key} must be one of whisper, parakeet, nemotron, got {value!r}" in err


def test_null_engines_in_the_config_are_the_defaults(monkeypatch):
    args = parse(monkeypatch, {"stream_engine": None, "final_engine": None})
    assert (args.stream_engine, args.final_engine) == ("whisper", None)


def test_nemotron_streaming_loads_no_final_engine(start, monkeypatch, capsys):
    beeps = start(installed=("local", "nemotron"), stream_engine="nemotron",
                  final_engine="parakeet", cpu_threads=1, model="tiny")
    t.print_banner(t.resolve_engines())
    fake_whisper(monkeypatch)
    loaded = []
    monkeypatch.setattr(t, "load_stream_model", lambda: loaded.append("parakeet"))
    monkeypatch.setattr(t, "load_nemotron", lambda: loaded.append("nemotron"))
    t.load_whisper_model()
    assert loaded == ["nemotron"]
    assert beeps == [] and "Warning" not in capsys.readouterr().out
