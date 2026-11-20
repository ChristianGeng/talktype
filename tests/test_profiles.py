"""Profiles merged on top of the config (#89). No display needed."""

import pytest

import profiles


def test_mappings_merge_key_by_key_at_every_depth():
    base = {
        "transcription": {"mode": "local", "model": "base", "inner": {"a": 1, "b": 2}}
    }
    overlay = {"transcription": {"mode": "api", "inner": {"b": 3}}}
    assert profiles.merge(base, overlay) == {
        "transcription": {"mode": "api", "model": "base", "inner": {"a": 1, "b": 3}}
    }


def test_other_values_and_lists_replace():
    base = {
        "text": {"vocabulary": ["ONNX", "LiveKit"]},
        "replacements": {"onyx": "onnx"},
    }
    overlay = {"text": {"vocabulary": ["Parakeet"]}, "replacements": None}
    assert profiles.merge(base, overlay) == {
        "text": {"vocabulary": ["Parakeet"]},
        "replacements": None,
    }


def test_merge_changes_neither_input():
    base = {"a": {"b": 1}}
    overlay = {"a": {"c": 2}}
    profiles.merge(base, overlay)
    assert base == {"a": {"b": 1}} and overlay == {"a": {"c": 2}}


def test_a_missing_or_empty_profile_is_empty(tmp_path):
    assert profiles.load(tmp_path / "profile.yaml") == {}
    (tmp_path / "empty.yaml").write_text("# nothing yet\n")
    assert profiles.load(tmp_path / "empty.yaml") == {}


def test_a_dangling_link_is_no_profile(tmp_path):
    (tmp_path / "profile.yaml").symlink_to(tmp_path / "gone.yaml")
    assert profiles.load(tmp_path / "profile.yaml") == {}


@pytest.mark.parametrize(
    "text, message", [("- a\n- b\n", "must be a mapping"), ("a: [\n", "can't be read")]
)
def test_a_bad_profile_is_an_error(tmp_path, text, message):
    path = tmp_path / "profile.yaml"
    path.write_text(text)
    with pytest.raises(profiles.ProfileError, match=message):
        profiles.load(path)


def test_the_name_is_the_link_target(tmp_path):
    (tmp_path / "profiles").mkdir()
    (tmp_path / "profiles" / "api.yaml").write_text("transcription: {mode: api}\n")
    link = tmp_path / "profile.yaml"
    link.symlink_to(tmp_path / "profiles" / "api.yaml")
    assert profiles.name(link) == "api"
    assert profiles.name(tmp_path / "profiles" / "api.yaml") == "api"
