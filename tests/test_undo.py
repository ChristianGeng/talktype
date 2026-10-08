"""The undo key's decisions (#60): what it removes, and when it refuses.

undo.py has no pynput or X11 dependencies; no display needed.
"""

import pytest

from undo import LastDictation

KITTY = ("x-window", "unix:@kitty", 7)


def dictated(route, *chunks, window=None):
    last = LastDictation()
    last.begin()
    for chunk in chunks:
        last.wrote(route, chunk, window)
    return last


def test_emacs_route_undoes_through_emacs():
    decision = dictated("emacs", " eins", " zwei").undo(busy=False)
    assert (decision.action, decision.route) == ("emacs", "emacs")


def test_emacs_route_has_no_kitty_guards():
    # talktype-undo-last checks the text itself, from any buffer.
    last = dictated("emacs", " eins\nzwei")
    last.key_pressed()
    assert last.undo(busy=False, focused=lambda w: "elsewhere").action == "emacs"


def test_kitty_route_deletes_every_character_written():
    last = dictated("kitty", " Grüße", " aus Köln €", " 🎤", window=KITTY)
    decision = last.undo(busy=False, focused=lambda w: KITTY)
    assert decision.action == "kitty"
    assert decision.chars == len(" Grüße aus Köln € 🎤") == 19
    assert decision.window == KITTY


def test_kitty_counts_code_points_not_bytes():
    decision = dictated("kitty", "ß€🎤", window=KITTY).undo(False, lambda w: KITTY)
    assert decision.chars == 3


def test_kitty_refuses_when_another_window_has_the_focus():
    last = dictated("kitty", " eins", window=KITTY)
    decision = last.undo(False, lambda w: ("x-window", "unix:@kitty", 8))
    assert (decision.action, decision.reason) == ("refuse", "another window has the focus")
    other_x = last.undo(False, lambda w: ("other", "unix:@kitty", 7))
    assert other_x.action == "refuse"
    # A refusal changes nothing: back in the window, the undo works.
    assert last.undo(False, lambda w: KITTY).action == "kitty"


def test_kitty_refuses_after_another_key():
    last = dictated("kitty", " eins", window=KITTY)
    last.key_pressed()
    decision = last.undo(False, lambda w: KITTY)
    assert (decision.action, decision.reason) == ("refuse", "a key was pressed since the dictation")


def test_kitty_refuses_a_key_pressed_while_it_looks_at_the_focus():
    last = dictated("kitty", " eins", window=KITTY)

    def focused(window):
        last.key_pressed()
        return KITTY

    assert last.undo(False, focused).action == "refuse"


def test_keys_before_the_recording_do_not_count():
    last = LastDictation()
    last.key_pressed()
    last.begin()
    last.wrote("kitty", " eins", KITTY)
    assert last.undo(False, lambda w: KITTY).action == "kitty"


def test_kitty_refuses_a_line_break():
    last = dictated("kitty", " eins", "\nzwei", window=KITTY)
    decision = last.undo(False, lambda w: KITTY)
    assert (decision.action, decision.reason) == ("refuse", "the dictation has a line break")


def test_kitty_refuses_without_a_window_id():
    last = dictated("kitty", " eins", window=None)
    assert last.undo(False, lambda w: KITTY).action == "refuse"


def test_a_second_press_has_nothing_to_undo():
    last = dictated("kitty", " eins", window=KITTY)
    assert last.undo(False, lambda w: KITTY).action == "kitty"
    decision = last.undo(False, lambda w: KITTY)
    assert (decision.action, decision.reason) == ("nothing", "nothing to undo")


def test_a_new_recording_replaces_the_last_dictation():
    last = dictated("kitty", " eins", window=KITTY)
    last.begin()  # nothing written yet, e.g. no speech
    assert last.undo(False, lambda w: KITTY).action == "nothing"
    last.wrote("emacs", " zwei")
    assert last.undo(False).action == "emacs"


def test_nothing_to_undo_before_any_dictation():
    assert LastDictation().undo(False).action == "nothing"


@pytest.mark.parametrize("route", ["terminal-paste", "type", "paste", "type-or-paste"])
def test_other_routes_are_not_supported(route):
    last = dictated(route, " eins")
    decision = last.undo(False)
    assert (decision.action, decision.reason) == ("unsupported", f"not supported for route {route}")
    assert last.undo(False).action == "unsupported"


def test_a_kitty_dictation_that_fell_back_to_paste_is_refused():
    last = dictated("kitty", " eins", window=KITTY)
    last.wrote("paste", " zwei")
    decision = last.undo(False, lambda w: KITTY)
    assert decision.action == "refuse"
    assert decision.reason == "the dictation took several routes (kitty, paste)"


def test_nothing_happens_while_recording_or_transcribing():
    last = dictated("kitty", " eins", window=KITTY)

    def focused(window):
        raise AssertionError("looked at the focus while busy")

    assert last.undo(True, focused).action == "busy"
    assert last.undo(False, lambda w: KITTY).action == "kitty"

