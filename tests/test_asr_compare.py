"""Scoring of bench/asr_compare.py (#47); no models or audio needed."""

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location(
    "asr_compare", ROOT / "bench" / "asr_compare.py"
)
ac = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ac)


def test_words_drop_case_and_punctuation_but_keep_inner_hyphens():
    assert ac.words("Open the onnx-asr file, then let's go!") == [
        "open",
        "the",
        "onnx-asr",
        "file",
        "then",
        "let's",
        "go",
    ]
    assert ac.words("Grüße aus Köln.") == ["grüße", "aus", "köln"]


def test_edit_distance_counts_substitutions_insertions_deletions():
    ref = "the onnx model loads".split()
    assert ac.edit_distance(ref, ref) == 0
    assert ac.edit_distance(ref, "the onyx model loads".split()) == 1
    assert ac.edit_distance(ref, "the model loads".split()) == 1
    assert ac.edit_distance(ref, "the onnx model loads fast".split()) == 1
    assert ac.edit_distance(ref, []) == 4


def test_term_found_needs_the_whole_term_in_order():
    hyp = ac.words("Claude Code runs in kitty")
    assert ac.term_found("Claude Code", hyp)
    assert ac.term_found("kitty", hyp)
    assert not ac.term_found("Code Claude", hyp)
    assert not ac.term_found("byobu", hyp)


def test_every_sentence_has_a_language_and_its_terms_in_the_text():
    sentences = ac.load_sentences()
    assert {s["lang"] for s in sentences} == {"en", "de"}
    for s in sentences:
        for term in s["terms"]:
            assert ac.term_found(term, ac.words(s["text"])), (term, s["text"])


def test_replacer_comes_from_the_config_or_is_empty(tmp_path):
    config = tmp_path / "config.yaml"
    config.write_text("replacements:\n  onyx: onnx\n", encoding="utf-8")
    assert ac.load_replacer(config).apply("the onyx model") == "the onnx model"
    assert (
        ac.load_replacer(tmp_path / "missing.yaml").apply("the onyx model")
        == "the onyx model"
    )


def test_score_totals_wer_terms_and_real_time_factor():
    rows = [
        {
            "edits": 1,
            "edits_replaced": 0,
            "ref_words": 4,
            "terms": 1,
            "terms_right": 0,
            "terms_right_replaced": 1,
            "seconds": 1.0,
            "audio_s": 4.0,
        },
        {
            "edits": 0,
            "edits_replaced": 0,
            "ref_words": 6,
            "terms": 0,
            "terms_right": 0,
            "terms_right_replaced": 0,
            "seconds": 1.0,
            "audio_s": 6.0,
        },
    ]
    assert ac.score(rows, "") == {"wer": 0.1, "terms": "0/1", "rtf": 0.2}
    assert ac.score(rows, "_replaced") == {"wer": 0.0, "terms": "1/1", "rtf": 0.2}
