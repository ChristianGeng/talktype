"""Decide which words of a growing transcript are safe to type.

While recording, the whole recording so far is transcribed again every
second or so. Whisper revises its guess as more audio arrives, so a word is
only typed once two consecutive transcripts agree on it (the LocalAgreement-2
policy of whisper_streaming). Typed words cannot be taken back, so every
later transcript is aligned against what has already been typed.

No audio or X11 dependencies, so it can be tested on its own.
"""

import difflib
import re

_NOT_WORD = re.compile(r"[^\w']+")
_SENTENCE_END = re.compile(r"[.?!][\"')\]]*$")


def normalize(word: str) -> str:
    """Compare words without case or surrounding punctuation."""
    return _NOT_WORD.sub("", word.lower())


def stable_prefix(previous: list[str], current: list[str]) -> list[str]:
    """Return the leading words of `current` that `previous` agrees with.

    The last word of `current` is always held back: it may be cut off mid-word.
    """
    agreed = 0
    for old, new in zip(previous, current[:-1]):
        if normalize(old) != normalize(new):
            break
        agreed += 1
    return current[:agreed]


def sentence_cut(stable: list[str]) -> int:
    """Return the index after the last sentence-final word of `stable`, or 0.

    Audio before that point can be dropped from later passes: its words are
    typed and settled, and a sentence end is usually a pause, so the next
    pass does not start in the middle of a word.
    """
    for i in range(len(stable) - 1, -1, -1):
        if _SENTENCE_END.search(stable[i]):
            return i + 1
    return 0


def remainder(typed: list[str], transcript: list[str]) -> list[str]:
    """Return the words of `transcript` after the already typed ones.

    Usually `transcript` starts with `typed`. If Whisper has since revised a
    word that is already on screen, typed words are aligned to the transcript
    and typing continues after the last match, so nothing is typed twice.
    """
    if not typed:
        return transcript
    a = [normalize(w) for w in typed]
    b = [normalize(w) for w in transcript]
    if b[: len(a)] == a:
        return transcript[len(a) :]
    matcher = difflib.SequenceMatcher(a=a, b=b, autojunk=False)
    blocks = [m for m in matcher.get_matching_blocks() if m.size]
    if not blocks:
        return transcript[len(typed) :]
    last = blocks[-1]
    # Typed words after the last match have no counterpart; skip as many.
    end = last.b + last.size + (len(a) - (last.a + last.size))
    return transcript[min(end, len(transcript)) :]
