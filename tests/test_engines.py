"""Falling back from an engine whose extra is missing (#66). No display needed."""

import importlib.machinery
import sys
import types

import pytest

import engines

SOURCE = "@ git+https://github.com/ChristianGeng/talktype'"


def only(*extras):
    return lambda extra: extra in extras


def test_missing_parakeet_streams_with_nemotron():
    choice = engines.choose(True, "parakeet", None, only("local", "nemotron"))
    assert (choice.stream_engine, choice.final_engine, choice.error) == (
        "nemotron", "nemotron", None
    )
    assert "stream_engine parakeet needs the 'parakeet' extra" in choice.warning
    assert "streaming with nemotron instead" in choice.warning
    assert choice.warning.endswith(
        "Install with: uv tool install --force "
        "'talktype[local,parakeet,nemotron] @ git+https://github.com/ChristianGeng/talktype'"
    )


def test_missing_parakeet_streams_with_whisper_when_nothing_else_is_there():
    choice = engines.choose(True, "parakeet", None, only("local"))
    assert (choice.stream_engine, choice.final_engine) == ("whisper", "whisper")
    assert f"'talktype[local,parakeet] {SOURCE}" in choice.warning
    assert "@ ...'" not in choice.warning


def test_missing_nemotron_streams_with_parakeet():
    choice = engines.choose(True, "nemotron", None, only("local", "parakeet"))
    assert (choice.stream_engine, choice.final_engine) == ("parakeet", "parakeet")
    assert f"'talktype[local,parakeet,nemotron] {SOURCE}" in choice.warning


def test_a_set_final_engine_falls_back_to_whisper():
    choice = engines.choose(True, "parakeet", "nemotron", only("local", "parakeet"))
    assert (choice.stream_engine, choice.final_engine) == ("parakeet", "whisper")
    assert "final_engine nemotron needs the 'nemotron' extra" in choice.warning
    assert "final_engine whisper instead" in choice.warning
    assert f"'talktype[local,parakeet,nemotron] {SOURCE}" in choice.warning


@pytest.mark.parametrize("final", ["whisper", "parakeet"])
def test_nemotron_does_not_stand_in_when_another_final_engine_is_set(final):
    # NemotronSession finishes without a final pass, so final_engine whisper
    # would never run.
    choice = engines.choose(True, "parakeet", final, only("local", "nemotron"))
    assert (choice.stream_engine, choice.final_engine) == ("whisper", "whisper")
    assert "streaming with whisper instead" in choice.warning


def test_nemotron_stands_in_when_the_final_engine_is_nemotron():
    choice = engines.choose(True, "parakeet", "nemotron", only("local", "nemotron"))
    assert (choice.stream_engine, choice.final_engine) == ("nemotron", "nemotron")


def test_without_streaming_only_the_final_engine_counts():
    choice = engines.choose(False, "parakeet", "nemotron", only("local"))
    assert (choice.final_engine, choice.error) == ("whisper", None)
    assert "stream_engine" not in choice.warning
    assert f"'talktype[local,nemotron] {SOURCE}" in choice.warning


def test_both_engines_missing_name_both_extras():
    choice = engines.choose(True, "parakeet", "nemotron", only("local"))
    assert (choice.stream_engine, choice.final_engine) == ("whisper", "whisper")
    assert len(choice.warning.splitlines()) == 3
    assert f"'talktype[local,parakeet,nemotron] {SOURCE}" in choice.warning


def test_installed_engines_need_no_warning():
    choice = engines.choose(True, "parakeet", None, only("local", "parakeet"))
    assert choice == engines.Choice("parakeet", "parakeet", None, None)
    assert engines.choose(False, "whisper", None, only("local")) == engines.Choice(
        "whisper", "whisper", None, None
    )


def test_the_command_keeps_the_extras_installed_already():
    choice = engines.choose(True, "parakeet", None, only("local", "server"))
    assert f"'talktype[local,parakeet,server] {SOURCE}" in choice.warning


def test_nothing_usable_is_an_error_with_the_command():
    choice = engines.choose(True, "parakeet", None, only("parakeet"))
    assert choice.warning is None
    assert choice.error.startswith("faster-whisper is not installed")
    assert f"Install with: uv tool install --force 'talktype[local,parakeet] {SOURCE}" in choice.error


def test_the_faster_whisper_message_is_uv_only():
    message = engines.whisper_missing(engines.install_command(["local"]))
    assert "uv tool install" in message
    assert "pip" not in message


@pytest.fixture
def imports(monkeypatch):
    """Make each extra's module importable (a stub) or missing (None)."""

    def set_modules(**present):
        for extra, module in engines.EXTRA_MODULE.items():
            stub = None
            if present.get(extra):
                stub = types.ModuleType(module)
                stub.__spec__ = importlib.machinery.ModuleSpec(module, None)
            monkeypatch.setitem(sys.modules, module, stub)

    return set_modules


def test_installed_follows_the_imports(imports):
    imports(local=True, nemotron=True)
    assert [e for e in engines.EXTRA_MODULE if engines.installed(e)] == ["local", "nemotron"]


def test_missing_parakeet_module_falls_back_without_exiting(imports):
    imports(local=True)
    choice = engines.choose(True, "parakeet", None)
    assert (choice.stream_engine, choice.final_engine, choice.error) == ("whisper", "whisper", None)
    assert f"'talktype[local,parakeet] {SOURCE}" in choice.warning


def test_an_imported_module_without_a_spec_counts_as_installed(monkeypatch):
    monkeypatch.setitem(sys.modules, "onnx_asr", types.ModuleType("onnx_asr"))
    assert engines.installed("parakeet")


@pytest.mark.parametrize("engine", ["parakeet", "nemotron"])
def test_loading_without_the_extra_names_the_full_command(monkeypatch, engine):
    module = __import__(engine)
    monkeypatch.setitem(sys.modules, engines.EXTRA_MODULE[engine], None)
    with pytest.raises(SystemExit) as stopped:
        module.Engine("/nowhere", 1) if engine == "nemotron" else module.load()
    message = str(stopped.value)
    assert f"needs the '{engine}' extra: uv tool install --force 'talktype[" in message
    assert message.endswith(SOURCE)


@pytest.mark.parametrize("final", ["whisper", "parakeet"])
def test_a_missing_final_engine_is_not_warned_about_while_nemotron_streams(final):
    # NemotronSession.finish() is the final pass; final_engine is never used.
    choice = engines.choose(True, "nemotron", final, only("local", "nemotron"))
    assert choice == engines.Choice("nemotron", final, None, None)


def test_a_final_engine_counts_again_once_nemotron_falls_back():
    choice = engines.choose(True, "nemotron", "parakeet", only("local"))
    assert (choice.stream_engine, choice.final_engine) == ("whisper", "whisper")
    assert "final_engine parakeet needs the 'parakeet' extra" in choice.warning
    assert "talktype[local,parakeet,nemotron]" in choice.warning
