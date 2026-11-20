"""Profiles merged on top of the config (#89). No display needed."""

import os

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


def test_a_missing_profile_is_none_and_a_dangling_link_too(tmp_path):
    assert profiles.read(tmp_path / "profile.yaml") is None
    (tmp_path / "link.yaml").symlink_to(tmp_path / "gone.yaml")
    assert profiles.read(tmp_path / "link.yaml") is None


def test_an_empty_or_comment_only_profile_is_named_and_empty(tmp_path):
    path = tmp_path / "quiet.yaml"
    path.write_text("# nothing yet\n\n")
    assert profiles.read(path) == profiles.Profile("quiet", {})


def test_a_linked_profile_is_named_after_its_target(tmp_path):
    (tmp_path / "profiles").mkdir()
    (tmp_path / "profiles" / "api.yaml").write_text("transcription: {mode: api}\n")
    link = tmp_path / "profile.yaml"
    link.symlink_to(tmp_path / "profiles" / "api.yaml")
    assert profiles.read(link) == profiles.Profile(
        "api", {"transcription": {"mode": "api"}}
    )


@pytest.mark.parametrize(
    "content, message",
    [
        (b"- a\n- b\n", "must be a mapping, got list"),
        (b"a: [\n", "can't be read"),
        (b"null\n", "must be a mapping, got null"),
        (b"~\n", "must be a mapping, got null"),
        (b"transcription: 5\n", "transcription must be a mapping, got int"),
        (b"hotkeys: [print]\n", "hotkeys must be a mapping, got list"),
        (b"transcription: {mode: api}\n\xff\xfe\n", "can't be read"),  # not UTF-8
    ],
)
def test_a_bad_profile_is_an_error(tmp_path, content, message):
    path = tmp_path / "profile.yaml"
    path.write_bytes(content)
    with pytest.raises(profiles.ProfileError, match=message):
        profiles.read(path)


def test_a_fifo_is_refused_instead_of_blocking(tmp_path):
    fifo = tmp_path / "profile.yaml"
    os.mkfifo(fifo)
    with pytest.raises(profiles.ProfileError, match="not a regular file"):
        profiles.read(fifo)


@pytest.mark.skipif(os.geteuid() == 0, reason="root reads any directory")
def test_an_unreadable_directory_is_an_error_not_no_profile(tmp_path):
    locked = tmp_path / "locked"
    locked.mkdir()
    (locked / "profile.yaml").write_text("transcription: {mode: api}\n")
    locked.chmod(0)
    try:
        with pytest.raises(profiles.ProfileError, match="can't be checked"):
            profiles.read(locked / "profile.yaml")
    finally:
        locked.chmod(0o700)
