from streaming import remainder, sentence_cut, stable_prefix


def test_stable_prefix_holds_back_last_word():
    assert stable_prefix("hello world".split(), "hello world".split()) == ["hello"]


def test_stable_prefix_stops_at_disagreement():
    prev = "the quick brown fax".split()
    cur = "the quick brown fox jumps".split()
    assert stable_prefix(prev, cur) == ["the", "quick", "brown"]


def test_stable_prefix_ignores_case_and_punctuation():
    assert stable_prefix(["Hello,", "there"], ["hello", "there", "friend"]) == [
        "hello",
        "there",
    ]


def test_stable_prefix_first_pass_types_nothing():
    assert stable_prefix([], "hello there".split()) == []


def test_remainder_simple_continuation():
    assert remainder(["a", "b"], ["a", "b", "c", "d"]) == ["c", "d"]


def test_remainder_after_revised_typed_word():
    typed = "I want to by".split()
    transcript = "I want to buy some milk".split()
    assert remainder(typed, transcript) == ["some", "milk"]


def test_remainder_nothing_new():
    assert remainder(["a", "b"], ["a", "b"]) == []


def test_remainder_empty_typed():
    assert remainder([], ["x"]) == ["x"]


def test_sentence_cut_after_last_sentence_end():
    words = "Hey, I placed an order. My plans changed. So I".split()
    assert sentence_cut(words) == 8


def test_sentence_cut_none():
    assert sentence_cut("no sentence end here,".split()) == 0
    assert sentence_cut([]) == 0


def test_sentence_cut_question_and_quote():
    assert sentence_cut(['Is', 'it', 'done?"', 'Yes']) == 3
