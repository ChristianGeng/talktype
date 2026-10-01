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


@pytest.mark.parametrize(
    "word, expected",
    [
        ("on", True),
        ("ONI", True),
        ("onyx", True),
        ("hello", False),
        ("now", False),
        ('"ONI",', True),
        ("hey,cl", True),
        ("onyx-asr", False),
        ("onyxes", False),
        ("GRÜSS", True),
        ("...", False),
        ("", False),
    ],
)
def test_could_continue_uses_the_trailing_word(r, word, expected):
    assert r.could_continue(word) is expected


@pytest.mark.parametrize("text", ["cl", " cloud CO", "Cloud\tcode  ma", " cloud code max"])
def test_could_continue_follows_a_normalized_phrase_from_its_start(text):
    assert Replacer({" Cloud\tCODE  Max ": "Claude Code Max"}).could_continue(text)


@pytest.mark.parametrize("text", ["CO", "code", " write code", "ma", " the max"])
def test_later_words_of_a_phrase_alone_cannot_continue_it(text):
    # #27: only "cloud" can start "cloud code max"
    assert not Replacer({" Cloud\tCODE  Max ": "Claude Code Max"}).could_continue(text)


def test_could_continue_with_an_empty_list_is_false():
    assert Replacer().could_continue("text") is False


@pytest.mark.parametrize(
    "pieces, whole",
    [
        ([" write code", "cloud code"], " write codecloud code"),
        ([" write hello", "cloud code"], " write hellocloud code"),
        ([" write hello", "onyx now"], " write helloonyx now"),
    ],
)
def test_a_piece_glued_to_a_word_already_written_does_not_match(pieces, whole):
    # Devin's review of #29: "codecloud" is one word, so no "cloud code"
    r = Replacer({"cloud code": "Claude Code", "onyx": "onnx"})
    assert "".join(fed(r, pieces)) == r.apply(whole) == whole


@pytest.mark.parametrize(
    "text",
    [
        " write codecloud code now",
        " hello helloonyx onyx, cloud code",
        "onyxonyx cloud cloudcode code",
    ],
)
def test_any_split_through_glued_words_gives_the_same_text(text):
    r = Replacer({"cloud code": "Claude Code", "onyx": "onnx"})
    whole = r.apply(text)
    for i in range(len(text) + 1):
        for j in range(i, len(text) + 1):
            assert "".join(fed(r, [text[:i], text[i:j], text[j:]])) == whole


def test_a_later_word_of_a_phrase_does_not_wait():
    # #27: nothing can put "cloud" before "code" any more
    r = Replacer({"cloud code": "Claude Code"})
    assert fed(r, [" write code", " now"]) == [" write code", " now", ""]


def test_a_punctuated_key_split_across_chunks():
    r = Replacer({"foo-bar": "FIXED"})
    assert fed(r, [" foo-b", "ar now"]) == ["", " FIXED now", ""]


def test_a_punctuated_key_does_not_cross_an_emitted_word_boundary():
    r = Replacer(
        {"foo-bar": "FIXED", ".net": "NET", "c++": "CPP", "(foo)": "PAREN"}
    )
    assert "".join(fed(r, ["afoo", "-b", "ar"])) == "afoo-bar"
    assert "".join(fed(r, ["a", ".", "net"])) == "a.net"
    assert "".join(fed(r, ["a", "c", "++"])) == "ac++"
    assert "".join(fed(r, ["a", "(", "foo)"])) == "a(foo)"


@pytest.mark.parametrize(
    "text",
    [
        " foo-bar now",
        " use FOO-BAR now",
        ' "foo-bar", c++ .net (foo) now',
        "hey,foo-bar now",
        "afoo-bar a.net ac++ a(foo)",
    ],
)
def test_any_split_with_punctuated_keys_gives_the_same_text(text):
    r = Replacer(
        {
            "foo": "FOO",
            "foo-bar": "FIXED",
            "use foo-bar": "USE FIXED",
            "c++": "CPP",
            ".net": "NET",
            "(foo)": "PAREN",
        }
    )
    whole = r.apply(text)
    for i in range(len(text) + 1):
        for j in range(i, len(text) + 1):
            assert "".join(fed(r, [text[:i], text[i:j], text[j:]])) == whole


def test_phrases_match_across_line_breaks_and_spaces(r):
    assert r.apply("cloud\n  code") == "Claude Code"


def test_an_empty_list_changes_nothing_and_holds_nothing_back():
    assert Replacer().apply(" onyx ") == " onyx "
    assert fed(Replacer(), [" on", "yx"]) == [" on", "yx", ""]


def test_a_word_split_across_chunks(r):
    out = fed(r, [" on", "yx is fast"])
    assert out == ["", " onnx is fast", ""]


def test_a_phrase_split_across_chunks(r):
    out = fed(r, [" I use cloud", " code now", " and then"])
    # "cloud code" may still become "cloud code max" until "now" arrives
    assert out == [" I use", " Claude Code now", " and then", ""]


def test_a_longer_phrase_split_across_three_chunks(r):
    out = fed(r, [" cloud", " code", " max"])
    assert "".join(out) == " Claude Code Max"
    assert out[:2] == ["", ""]


def test_a_phrase_start_that_is_not_continued_goes_out(r):
    assert fed(r, [" the cloud", " is grey"]) == [" the", " cloud is grey", ""]


def test_flush_at_stop_writes_the_held_word(r):
    assert fed(r, [" it runs on onyx"]) == [" it runs on", " onnx"]
    assert fed(r, [" peter"]) == ["", " peter"]
    assert fed(r, [" peter frank"]) == ["", " Peter Frank"]


def test_a_last_word_that_cannot_become_a_listed_word_does_not_wait(r):
    # #25: "world" can't grow into onyx, onix, cloud, grüsse or peter
    assert fed(r, [" hello world", " again"]) == [" hello world", " again", ""]


def test_a_last_word_that_may_still_become_a_listed_word_waits(r):
    # "on" may continue to "onyx", and "onyx" to "onyxes"
    assert fed(r, [" it runs on", "yx"]) == [" it runs", "", " onnx"]
    assert fed(r, [" ONI", "X now"]) == ["", " onnx now", ""]


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


def test_a_phrase_after_punctuation_waits_for_its_end(r):
    assert "".join(fed(r, [" hey,cloud ", "code"])) == " hey,Claude Code"
    assert "".join(fed(r, [' "cloud', ' code"'])) == ' "Claude Code"'


OVERLAPPING = Replacer(parse({"a b": "AB", "b c": "BC", "b c d": "BCD"}))


def test_a_complete_phrase_is_not_split_by_a_phrase_it_overlaps():
    assert fed(OVERLAPPING, [" a b "]) == [" AB", " "]
    assert "".join(fed(OVERLAPPING, [" a b ", "c"])) == " AB c"
    assert "".join(fed(OVERLAPPING, [" x b ", "c d"])) == " x BCD"


@pytest.mark.parametrize("text", [" a b c d b c, a b.", "b c a b c d a,b c"])
def test_any_split_with_overlapping_phrases_gives_the_same_text(text):
    whole = OVERLAPPING.apply(text)
    for i in range(len(text) + 1):
        for j in range(i, len(text) + 1):
            assert "".join(fed(OVERLAPPING, [text[:i], text[i:j], text[j:]])) == whole


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
