import pytest

from replacements import Replacer, parse

LIST = {
    "onyx": "onnx",
    "onix": "onnx",
    "cloud code": "Claude Code",
    "cloud code max": "Claude Code Max",
    "grüsse": "Grüße",
    "peter frank": "Peter Frank",
}


@pytest.fixture
def r():
    return Replacer(parse(LIST))


def fed(r, pieces, word_end=False):
    stream = r.stream()
    out = [stream.feed(p, word_end=word_end) for p in pieces]
    out.append(stream.flush())
    return out


def test_case_is_ignored_and_the_replacement_keeps_its_spelling(r):
    assert r.apply("Onyx and ONYX and onix") == "onnx and onnx and onnx"
    assert r.apply("I use CLOUD CODE") == "I use Claude Code"


def test_only_whole_words_match(r):
    assert r.apply("onyxes bonyx onyx2 ponix") == "onyxes bonyx onyx2 ponix"


def test_the_longest_phrase_wins(r):
    assert r.apply("cloud code max plan") == "Claude Code Max plan"
    assert r.apply("cloud code, max") == "Claude Code, max"
    assert r.apply("the cloud is grey") == "the cloud is grey"


def test_punctuation_next_to_a_word_does_not_prevent_a_match(r):
    assert r.apply('onyx, "onyx" (onix). onyx-asr') == 'onnx, "onnx" (onnx). onnx-asr'


def test_umlauts(r):
    assert r.apply("Grüsse aus Köln") == "Grüße aus Köln"
    assert r.apply("Grüssen") == "Grüssen"
    assert Replacer({"köln": "Cologne"}).apply("KÖLN, Kölner") == "Cologne, Kölner"


def test_phrases_match_across_line_breaks_and_spaces(r):
    assert r.apply("cloud\n  code") == "Claude Code"


def test_an_empty_list_changes_nothing_and_holds_nothing_back():
    assert Replacer().apply(" onyx ") == " onyx "
    assert fed(Replacer(), [" on", "yx"]) == [" on", "yx", ""]


def test_a_word_split_across_chunks(r):
    out = fed(r, [" on", "yx is fast"])
    assert out == ["", " onnx is", " fast"]


def test_a_phrase_split_across_chunks(r):
    out = fed(r, [" I use cloud", " code now", " and then"])
    # "cloud code" may still become "cloud code max" until "now" arrives
    assert out == [" I use", "", " Claude Code now and", " then"]


def test_a_longer_phrase_split_across_three_chunks(r):
    out = fed(r, [" cloud", " code", " max"])
    assert "".join(out) == " Claude Code Max"
    assert out[:2] == ["", ""]


def test_a_phrase_start_that_is_not_continued_goes_out(r):
    assert fed(r, [" the cloud", " is grey"]) == [" the", " cloud is", " grey"]


def test_flush_at_stop_writes_the_held_word(r):
    assert fed(r, [" it runs on onyx"]) == [" it runs on", " onnx"]
    assert fed(r, [" peter"]) == ["", " peter"]
    assert fed(r, [" peter frank"]) == ["", " Peter Frank"]


def test_whole_words_do_not_wait_unless_they_may_begin_a_phrase(r):
    assert fed(r, [" it runs on onyx", " fast"], word_end=True) == [
        " it runs on onnx",
        " fast",
        "",
    ]
    assert fed(r, [" I use cloud"], word_end=True) == [" I use", " cloud"]


@pytest.mark.parametrize(
    "text",
    [
        " Peter Frank uses onyx, cloud code max and the cloud. Grüsse!",
        "onix\ncloud  code onyx-asr cloud",
    ],
)
def test_any_split_gives_the_same_text_as_a_whole(r, text):
    whole = r.apply(text)
    for i in range(len(text) + 1):
        for j in range(i, len(text) + 1):
            assert "".join(fed(r, [text[:i], text[i:j], text[j:]])) == whole


def test_parse_accepts_a_missing_list():
    assert parse(None) == {}


def test_parse_normalizes_case_and_spaces():
    assert parse({"Cloud  Code": "Claude Code"}) == {"cloud code": "Claude Code"}


@pytest.mark.parametrize(
    "value",
    [["onyx"], "onyx: onnx", 1, {"onyx": None}, {"onyx": 1}, {1: "one"}, {True: "yes"}],
)
def test_parse_rejects_what_is_not_a_mapping_of_strings(value):
    with pytest.raises(ValueError, match="replacements"):
        parse(value)


def test_parse_rejects_an_empty_word():
    with pytest.raises(ValueError, match="empty"):
        parse({"  ": "x"})


def test_parse_rejects_the_same_word_with_two_replacements():
    with pytest.raises(ValueError, match="twice"):
        parse({"onyx": "onnx", "Onyx": "ONNX"})
