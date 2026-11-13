"""Field terms in their spelling from a vocabulary (#71)."""

import os
import sys

import pytest

import numerals
import replacements

TERMS = ["ONNX", "LiveKit", "Parakeet TDT", "Claude Code"]


def test_terms_are_written_as_listed_in_any_case_and_spacing():
    r = replacements.Replacer(replacements.vocabulary(TERMS))
    assert r.apply("the onnx runtime in livekit") == "the ONNX runtime in LiveKit"
    assert r.apply("parakeet   tdt, Onnx.") == "Parakeet TDT, ONNX."
    assert (
        r.apply("onnxruntime and livekits") == "onnxruntime and livekits"
    )  # whole words


def test_two_spellings_of_the_same_words_are_an_error():
    with pytest.raises(ValueError, match="'Onnx' and 'ONNX'"):
        replacements.vocabulary(["Onnx", "ONNX"])


def test_the_same_spelling_twice_is_fine():
    assert replacements.vocabulary(["ONNX", "ONNX"]) == {"onnx": "ONNX"}


def test_files_hold_one_term_per_line(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    (tmp_path / "terms.txt").write_text(
        "# project terms\nLiveKit\n\n  ONNX  \n#Skip\nLiveKit\n"
    )
    terms, warnings = replacements.read_vocabulary(["Claude Code"], ["~/terms.txt"])
    assert terms == ["Claude Code", "LiveKit", "ONNX"]
    assert warnings == []


def test_a_single_file_path_is_accepted(tmp_path):
    path = tmp_path / "terms.txt"
    path.write_text("ONNX\n")
    assert replacements.read_vocabulary(None, str(path)) == (["ONNX"], [])


def test_a_missing_file_warns_and_the_rest_is_used(tmp_path):
    terms, warnings = replacements.read_vocabulary(
        ["ONNX"], [str(tmp_path / "nope.txt")]
    )
    assert terms == ["ONNX"]
    assert len(warnings) == 1 and "nope.txt" in warnings[0]


@pytest.mark.parametrize(
    "terms, files",
    [("ONNX", None), (["ONNX", 3], None), (None, [1]), (None, {"a": "b"})],
)
def test_malformed_values_are_errors(terms, files):
    with pytest.raises(ValueError):
        replacements.read_vocabulary(terms, files)


@pytest.mark.parametrize(
    "cut", range(1, len("the onnx models in parakeet tdt and livekit"))
)
def test_streamed_pieces_get_the_spelling(cut):
    r = replacements.Replacer(replacements.vocabulary(TERMS))
    text = "the onnx models in parakeet tdt and livekit"
    stream = r.stream()
    out = stream.feed(text[:cut]) + stream.feed(text[cut:]) + stream.flush()
    assert out == "the ONNX models in Parakeet TDT and LiveKit"


def test_numbers_come_first():
    r = replacements.Replacer(replacements.vocabulary(TERMS))
    chain = numerals.Chain(numerals.Numerals("en").stream(), r.stream())
    out = chain.feed("ninety nine onnx") + chain.feed(" models") + chain.flush()
    assert out == "99 ONNX models"


if os.environ.get("DISPLAY"):
    import talktype as t

    def config(monkeypatch, file_config, argv=("talktype",)):
        monkeypatch.setattr(sys, "argv", list(argv))
        monkeypatch.setattr(t, "load_config_file", lambda: file_config)
        return t.parse_args()

    def test_vocabulary_comes_from_the_config(monkeypatch, tmp_path):
        path = tmp_path / "terms.txt"
        path.write_text("LiveKit\n")
        args = config(
            monkeypatch,
            {"text": {"vocabulary": ["ONNX"], "vocabulary_files": [str(path)]}},
        )
        assert args.vocabulary == ["ONNX", "LiveKit"]
        assert t.build_replacer(args).apply("onnx in livekit") == "ONNX in LiveKit"

    def test_no_vocabulary_by_default(monkeypatch):
        args = config(monkeypatch, {})
        assert args.vocabulary == [] and args.spellings == {}

    def test_a_replacement_wins_over_the_vocabulary(monkeypatch):
        args = config(
            monkeypatch,
            {"text": {"vocabulary": ["Onyx"]}, "replacements": {"onyx": "onnx"}},
        )
        assert t.build_replacer(args).apply("the onyx model") == "the onnx model"

    def test_conflicting_spellings_stop_with_a_config_error(monkeypatch, capsys):
        with pytest.raises(SystemExit):
            config(monkeypatch, {"text": {"vocabulary": ["Onnx", "ONNX"]}})
        assert "Config error: text.vocabulary" in capsys.readouterr().out

    def test_a_missing_file_is_a_warning_at_start(monkeypatch, capsys, tmp_path):
        args = config(
            monkeypatch,
            {
                "text": {
                    "vocabulary": ["ONNX"],
                    "vocabulary_files": [str(tmp_path / "x.txt")],
                }
            },
        )
        assert args.vocabulary == ["ONNX"]
        assert "Warning: vocabulary file" in capsys.readouterr().out
