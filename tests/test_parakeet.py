from parakeet import group_words


def test_group_words_joins_subword_tokens():
    tokens = [" He", "y", ",", " uh", " I", " hel", "p"]
    stamps = [0.08, 0.16, 0.24, 0.32, 0.64, 0.96, 1.04]
    assert group_words(tokens, stamps) == (
        ["Hey,", "uh", "I", "help"],
        [0.08, 0.32, 0.64, 0.96],
    )


def test_group_words_first_token_without_space():
    assert group_words(["Ha", "llo", " du"], [0.0, 0.1, 0.4]) == (
        ["Hallo", "du"],
        [0.0, 0.4],
    )


def test_group_words_empty():
    assert group_words([], []) == ([], [])
