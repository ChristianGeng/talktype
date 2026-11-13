"""Spoken numbers as digits (#70), whole and streamed."""

import pytest

import numerals
import replacements

EN = numerals.Numerals("en")


@pytest.mark.parametrize(
    "spoken, written",
    [
        ("we need ninety nine samples", "we need 99 samples"),
        ("version three point five", "version 3.5"),
        ("the twenty first run", "the 21st run"),
        ("about one thousand two hundred and thirty four files", "about 1234 files"),
        ("Ninety nine bottles.", "99 bottles."),
        ("twenty-one pilots", "21 pilots"),
        # Small isolated numbers stay words in running text.
        ("one of the models", "one of the models"),
        ("it took two hours", "it took two hours"),
    ],
)
def test_english(spoken, written):
    assert EN.apply(spoken) == written


@pytest.mark.parametrize(
    "spoken, written",
    [
        ("wir brauchen neunundneunzig Beispiele", "wir brauchen 99 Beispiele"),
        ("zweihundertdreiundvierzig Dateien", "243 Dateien"),
        ("eins von den Modellen", "eins von den Modellen"),
    ],
)
def test_german(spoken, written):
    assert numerals.Numerals("de").apply(spoken) == written


@pytest.mark.parametrize("language", [None, "", "ja", "xx"])
def test_unknown_or_unset_language_leaves_text_alone(language):
    off = numerals.Numerals(language)
    assert not off
    assert off.apply("ninety nine") == "ninety nine"
    assert off.stream().feed("ninety") == "ninety"


def test_disabled_leaves_text_alone():
    assert numerals.Numerals("en", enabled=False).apply("ninety nine") == "ninety nine"


@pytest.mark.parametrize("language", ["en-US", "EN", "de_DE"])
def test_language_variants_count(language):
    assert numerals.Numerals(language)


@pytest.mark.parametrize(
    "text, held",
    [
        ("we need ninety", " ninety"),
        ("we need ninety nine", " ninety nine"),
        ("a hundred and", " hundred and"),
        ("three point", "three point"),
        ("we need ninety nine samples", ""),
        ("cats and", ""),  # a connector without a number before it
        ("ninety nine.", ""),  # punctuation ends the number
    ],
)
def test_what_the_end_of_a_whole_word_piece_holds(text, held):
    assert text[EN.hold_from(text, word_end=True) :] == held


@pytest.mark.parametrize(
    "text, held",
    [
        ("we need fo", " fo"),  # may become "forty"
        ("seven", "seven"),  # may become "seventeen"
        ("There's a dupli", ""),  # cannot become a number
        ("we got twenty fir", " twenty fir"),  # may become "twenty first"
        ("the", ""),
    ],
)
def test_a_cut_off_last_word_is_held_if_it_may_become_a_number(text, held):
    assert text[EN.hold_from(text) :] == held


def test_german_compounds_cut_off_are_held():
    de = numerals.Numerals("de")
    assert de.may_continue("neunund")
    assert de.may_continue("zweihundertdrei")
    assert not de.may_continue("Beisp")


SENTENCES = [
    "we need ninety nine samples and the one thing costs three point five euros.",
    "About one thousand two hundred and thirty four files, then twenty first place.",
    "It took two hours and forty five minutes for seventeen runs",
]


@pytest.mark.parametrize("sentence", SENTENCES)
def test_every_split_into_two_pieces_gives_the_whole_text(sentence):
    whole = EN.apply(sentence)
    for i in range(len(sentence) + 1):
        stream = EN.stream()
        out = stream.feed(sentence[:i]) + stream.feed(sentence[i:]) + stream.flush()
        assert out == whole, (i, sentence[:i], sentence[i:])


@pytest.mark.parametrize("sentence", SENTENCES)
def test_word_by_word_with_word_ends_gives_the_whole_text(sentence):
    # How the Whisper and Parakeet sessions feed: whole words, word_end=True.
    stream = EN.stream()
    out = "".join(stream.feed(" " + word, word_end=True) for word in sentence.split())
    out += stream.flush()
    assert out.strip() == EN.apply(sentence)


def test_pieces_come_out_as_soon_as_no_number_can_follow():
    stream = EN.stream()
    assert stream.feed("we need ninety") == "we need"
    assert stream.holding
    assert stream.feed(" nine") == ""
    assert stream.feed(" samples") == " 99 samples"
    assert not stream.holding


def test_preview_shows_held_numbers_without_changing_the_stream():
    stream = EN.stream()
    stream.feed("we need ninety")
    assert stream.preview(" nine samples") == " 99 samples"
    assert stream.feed(" nine samples", word_end=True) == " 99 samples"


def test_chain_converts_numbers_before_replacements():
    replacer = replacements.Replacer({"onyx": "onnx", "gpt 4": "GPT-4"})
    chain = numerals.Chain(EN.stream(), replacer.stream())
    pieces = ["we need ninety", " nine onyx", " models and gpt", " four"]
    out = "".join(chain.feed(p) for p in pieces) + chain.flush()
    assert out == "we need 99 onnx models and GPT-4"


@pytest.mark.parametrize(
    "sentence", SENTENCES + ["the onyx model needs ninety nine runs of cloud code"]
)
def test_chain_over_every_split_equals_whole_text(sentence):
    replacer = replacements.Replacer({"onyx": "onnx", "cloud code": "Claude Code"})
    whole = replacer.apply(EN.apply(sentence))
    for i in range(len(sentence) + 1):
        chain = numerals.Chain(EN.stream(), replacer.stream())
        out = chain.feed(sentence[:i]) + chain.feed(sentence[i:]) + chain.flush()
        assert out == whole, (i, sentence[:i], sentence[i:])


def test_chain_preview():
    replacer = replacements.Replacer({"onyx": "onnx"})
    chain = numerals.Chain(EN.stream(), replacer.stream())
    chain.feed("we need ninety")
    assert chain.preview(" nine onyx") == " 99 onnx"


def test_every_split_into_three_pieces_gives_the_whole_text():
    sentence = "costs three point five and a hundred and five, not twenty one"
    whole = EN.apply(sentence)
    for i in range(len(sentence) + 1):
        for j in range(i, len(sentence) + 1):
            stream = EN.stream()
            pieces = (sentence[:i], sentence[i:j], sentence[j:])
            out = "".join(stream.feed(p) for p in pieces) + stream.flush()
            assert out == whole, pieces


def test_german_every_split_gives_the_whole_text():
    de = numerals.Numerals("de")
    sentence = "wir brauchen neunundneunzig Beispiele und zweihundertdrei Dateien"
    whole = de.apply(sentence)
    for i in range(len(sentence) + 1):
        stream = de.stream()
        out = stream.feed(sentence[:i]) + stream.feed(sentence[i:]) + stream.flush()
        assert out == whole, (sentence[:i], sentence[i:])
