"""Write known misrecognitions the way they are meant.

Engines mishear technical terms ("onyx" for "onnx", "cloud code" for
"Claude Code"), and Nemotron and Parakeet take no hints. The replacement
list from the config maps what an engine heard to what should be written.
Matching is whole-word and case-insensitive, the longest phrase wins, and
the replacement keeps its own spelling.

Streamed text arrives in pieces that can split a word ("on" + "yx") or a
phrase ("cloud" + " code"), so a Stream holds back the end of each piece
that a later piece could still change.

No audio or X11 dependencies, so it can be tested on its own.
"""

import re

_TOKEN = re.compile(r"\S+")
_EDGES = re.compile(r"^\W+|\W+$")


def _key(phrase: str) -> str:
    """Compare phrases without case or differences in spacing."""
    return " ".join(phrase.lower().split())


def _core(word: str) -> str:
    """A word without case and without punctuation at its edges."""
    return _EDGES.sub("", word.lower())


def parse(value) -> dict[str, str]:
    """Check the `replacements:` config value; raise ValueError if malformed."""
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise ValueError(
            f"replacements must be a mapping of heard: written, got {value!r}"
        )
    mapping: dict[str, str] = {}
    for heard, written in value.items():
        if not isinstance(heard, str) or not isinstance(written, str):
            raise ValueError(
                f"replacements must map words to words, got {heard!r}: {written!r}"
            )
        key = _key(heard)
        if not key:
            raise ValueError("replacements: an empty word cannot be replaced")
        if key in mapping and mapping[key] != written:
            raise ValueError(f"replacements: {heard!r} is listed twice")
        mapping[key] = written
    return mapping


class Replacer:
    """Applies a replacement list to whole texts; stream() for pieces."""

    def __init__(self, mapping: dict[str, str] | None = None):
        self._mapping = {_key(heard): written for heard, written in (mapping or {}).items()}
        # Alternatives are tried in order, so the longest phrase comes first.
        keys = sorted(self._mapping, key=len, reverse=True)
        self._pattern = (
            re.compile(
                r"(?<!\w)(?:"
                + "|".join(r"\s+".join(map(re.escape, k.split())) for k in keys)
                + r")(?!\w)",
                re.IGNORECASE,
            )
            if keys
            else None
        )
        # Word sequences that begin a phrase of the list without completing it.
        self._starts: set[tuple[str, ...]] = set()
        for key in keys:
            words = tuple(_core(w) for w in key.split())
            for n in range(1, len(words)):
                self._starts.add(words[:n])
        self._longest = max((len(k.split()) for k in keys), default=0)

    def __bool__(self) -> bool:
        return self._pattern is not None

    def apply(self, text: str) -> str:
        """Return `text` with every listed word or phrase replaced."""
        if self._pattern is None:
            return text
        return self._pattern.sub(
            lambda m: self._mapping.get(_key(m.group()), m.group()), text
        )

    def phrase_start(self, words: list[str]) -> int:
        """Index of the first of the trailing `words` that may begin a phrase.

        len(words) if none may: the words after that index could still be
        completed into a listed phrase by the next piece of text.
        """
        end = len(words)
        for start in range(max(0, end - self._longest + 1), end):
            if tuple(_core(w) for w in words[start:]) in self._starts:
                return start
        return end

    def stream(self) -> "Stream":
        return Stream(self)


class Stream:
    """Replaces text that arrives in pieces; nothing is lost or repeated.

    The concatenated output of feed() and flush() equals apply() on the
    concatenated input.
    """

    def __init__(self, replacer: Replacer):
        self._replacer = replacer
        self._pending = ""

    def feed(self, text: str, word_end: bool = False) -> str:
        """Add a piece; return the replaced text no later piece can change.

        The last word waits for the next piece, which may continue it,
        unless `word_end` says the piece ends with a whole word (the next
        piece then starts with a space). Words that may begin a listed
        phrase wait as well. Without a list nothing waits.
        """
        buffered = self._pending + text
        if not self._replacer:
            return buffered
        tokens = list(_TOKEN.finditer(buffered))
        whole = len(tokens)
        if tokens and not word_end and tokens[-1].end() == len(buffered):
            whole -= 1
        hold = self._replacer.phrase_start([t.group() for t in tokens[:whole]])
        if hold == len(tokens):
            cut = len(buffered)
        elif hold:
            cut = tokens[hold - 1].end()
        else:
            cut = 0
        self._pending = buffered[cut:]
        return self._replacer.apply(buffered[:cut])

    def flush(self) -> str:
        """The input has ended: return the rest, replaced."""
        text, self._pending = self._pending, ""
        return self._replacer.apply(text)
