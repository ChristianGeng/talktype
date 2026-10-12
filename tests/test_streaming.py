from streaming import remainder, sentence_cut, stable_prefix, tail


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


def test_tail_is_the_pass_beyond_the_written_words():
    assert tail(["hello", "world"], "hello world how are".split()) == ["how", "are"]


def test_tail_is_the_whole_pass_before_anything_is_written():
    assert tail([], "hello world".split()) == ["hello", "world"]


def test_tail_is_empty_when_the_pass_adds_nothing():
    assert tail(["hello", "world"], ["Hello,", "world"]) == []
    assert tail([], []) == []


def test_tail_follows_a_revised_written_word():
    written = "I want to by".split()
    assert tail(written, "I want to buy some milk".split()) == ["some", "milk"]


def test_tail_is_rewritten_by_the_next_pass():
    written = ["the", "quick"]
    assert tail(written, "the quick brown fax".split()) == ["brown", "fax"]
    assert tail(written, "the quick brown fox jumps".split()) == ["brown", "fox", "jumps"]
