"""TalkType reads the profile on top of config.yaml (#89)."""

import os
import sys

import pytest

if not os.environ.get("DISPLAY"):
    pytest.skip(
        "talktype imports pynput, which needs an X display", allow_module_level=True
    )

import talktype as t  # noqa: E402

BASE = """\
hotkeys:
  record: print
transcription:
  mode: local
  streaming: true
  stream_engine: nemotron
  language: en
replacements:
  onyx: onnx
"""

API = """\
transcription:
  mode: api
  api_url: https://api.openai.com/v1/audio/transcriptions
  api_model: gpt-4o-transcribe
  api_key_command: gopass show -o aud/api/openai/openai_api_key
  streaming: false
"""


@pytest.fixture
def home(tmp_path, monkeypatch):
    config = tmp_path / "config.yaml"
    config.write_text(BASE)
    (tmp_path / "profiles").mkdir()
    (tmp_path / "profiles" / "api.yaml").write_text(API)
    monkeypatch.setattr(t, "CONFIG_PATH", config)
    monkeypatch.setattr(t, "PROFILE_PATH", tmp_path / "profile.yaml")
    monkeypatch.setattr(t, "active_profile", None)
    monkeypatch.delenv("TALKTYPE_PROFILE", raising=False)
    monkeypatch.setattr(sys, "argv", ["talktype"])
    return tmp_path


def test_without_a_profile_the_config_is_as_before(home):
    assert t.load_config_file()["transcription"]["mode"] == "local"
    assert t.active_profile is None


def test_a_linked_profile_goes_on_top(home):
    (home / "profile.yaml").symlink_to(home / "profiles" / "api.yaml")
    config = t.load_config_file()
    assert config["transcription"]["mode"] == "api"
    assert config["transcription"]["api_model"] == "gpt-4o-transcribe"
    assert config["transcription"]["language"] == "en"  # from config.yaml
    assert config["replacements"] == {"onyx": "onnx"}
    assert t.active_profile == "api"


def test_the_profile_reaches_the_parsed_arguments(home):
    (home / "profile.yaml").symlink_to(home / "profiles" / "api.yaml")
    args = t.parse_args()
    assert args.api == "https://api.openai.com/v1/audio/transcriptions"
    assert args.api_key_command == "gopass show -o aud/api/openai/openai_api_key"
    assert args.stream is False


def test_the_profile_flag_and_variable_choose_another_file(home, monkeypatch):
    monkeypatch.setattr(
        sys, "argv", ["talktype", "--profile", str(home / "profiles" / "api.yaml")]
    )
    assert t.load_config_file()["transcription"]["mode"] == "api"
    monkeypatch.setattr(sys, "argv", ["talktype"])
    monkeypatch.setenv("TALKTYPE_PROFILE", str(home / "profiles" / "api.yaml"))
    assert t.load_config_file()["transcription"]["mode"] == "api"


def test_profile_none_ignores_the_link(home, monkeypatch):
    (home / "profile.yaml").symlink_to(home / "profiles" / "api.yaml")
    monkeypatch.setattr(sys, "argv", ["talktype", "--profile", "none"])
    assert t.load_config_file()["transcription"]["mode"] == "local"
    assert t.active_profile is None


def test_a_named_profile_that_is_missing_stops(home, monkeypatch, capsys):
    monkeypatch.setattr(
        sys, "argv", ["talktype", "--profile", str(home / "profiles" / "nope.yaml")]
    )
    with pytest.raises(SystemExit):
        t.load_config_file()
    assert "does not exist" in capsys.readouterr().out


def test_a_bad_profile_stops_with_a_config_error(home, capsys):
    (home / "profile.yaml").write_text("- not\n- a mapping\n")
    with pytest.raises(SystemExit):
        t.load_config_file()
    assert "Config error: profile" in capsys.readouterr().out


def test_the_start_up_lines_name_the_profile(home, monkeypatch, capsys):
    (home / "profile.yaml").symlink_to(home / "profiles" / "api.yaml")
    monkeypatch.setattr(t, "config", t.parse_args(), raising=False)
    t.print_banner()
    assert "Profile: api" in capsys.readouterr().out


def test_naming_the_missing_default_path_is_still_an_error(home, monkeypatch, capsys):
    # Reviews on #90: an explicitly named profile.yaml that is missing was ignored.
    monkeypatch.setattr(
        sys, "argv", ["talktype", "--profile", str(home / "profile.yaml")]
    )
    with pytest.raises(SystemExit):
        t.load_config_file()
    assert "does not exist" in capsys.readouterr().out


def test_an_empty_profile_option_wins_over_the_variable(home, monkeypatch):
    monkeypatch.setenv("TALKTYPE_PROFILE", str(home / "profiles" / "api.yaml"))
    monkeypatch.setattr(sys, "argv", ["talktype", "--profile", ""])
    assert t.load_config_file()["transcription"]["mode"] == "local"
    assert t.active_profile is None


def test_help_still_works_with_a_broken_profile(home, monkeypatch, capsys):
    (home / "profile.yaml").write_text("- broken\n")
    monkeypatch.setattr(sys, "argv", ["talktype", "--help"])
    assert t.load_config_file()["transcription"]["mode"] == "local"
    assert "Config error: profile" in capsys.readouterr().out


def test_an_empty_selected_profile_is_named(home):
    (home / "profiles" / "quiet.yaml").write_text("# nothing differs yet\n")
    (home / "profile.yaml").symlink_to(home / "profiles" / "quiet.yaml")
    assert t.load_config_file()["transcription"]["mode"] == "local"
    assert t.active_profile == "quiet"
