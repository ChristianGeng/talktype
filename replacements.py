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
_WORD = re.compile(r"\w")
_TRAILING_WORD = re.compile(r"(\w+)\W*$")


def _key(phrase: str) -> str:
    """Compare phrases without case or differences in spacing."""
    return " ".join(phrase.lower().split())


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
        # What a phrase of the list begins with, without completing it.
        self._prefixes: set[str] = set()
        for key in keys:
            words = key.split()
            for n in range(1, len(words)):
                self._prefixes.add(" ".join(words[:n]))
        self._longest = max((len(k.split()) for k in keys), default=0)
        self._words = {word for key in keys for word in key.split()}

    def __bool__(self) -> bool:
        return self._pattern is not None

    def apply(self, text: str) -> str:
        """Return `text` with every listed word or phrase replaced."""
        if self._pattern is None:
            return text
        return self._pattern.sub(
            lambda m: self._mapping.get(_key(m.group()), m.group()), text
        )

    def could_continue(self, word: str) -> bool:
        """Whether the trailing word may still become a listed word."""
        trailing = _TRAILING_WORD.search(word)
        if trailing is None:
            return False
        prefix = _key(trailing.group(1))
        return any(listed.startswith(prefix) for listed in self._words)

    def phrase_start(self, text: str) -> int | None:
        """Where the end of `text` may begin a phrase of the list, or None.

        `text` ends with a whole word; the next piece of text could still
        complete a phrase that starts at the returned index. The earliest
        such index is returned.
        """
        if not self._prefixes:
            return None
        tokens = list(_TOKEN.finditer(text))
        first = tokens[max(0, len(tokens) - self._longest + 1)].start() if tokens else 0
        for start in range(first, len(text)):
            if text[start].isspace() or (start and _WORD.match(text, start - 1)):
                continue
            if _key(text[start:]) in self._prefixes:
                return start
        return None

    def matches(self, text: str) -> list[re.Match]:
        """The listed words and phrases in `text`, as apply() finds them."""
        return list(self._pattern.finditer(text)) if self._pattern else []

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

        The last word waits only if it may still become a listed word,
        unless `word_end` says the piece ends with a whole word (the next
        piece then starts with a space). Words that may begin a listed
        phrase wait as well. Without a list nothing waits.
        """
        buffered = self._pending + text
        if not self._replacer:
            return buffered
        tokens = list(_TOKEN.finditer(buffered))
        whole = len(tokens)
        if (
            tokens
            and not word_end
            and tokens[-1].end() == len(buffered)
            and self._replacer.could_continue(tokens[-1].group())
        ):
            whole -= 1
        end = tokens[whole - 1].end() if whole else 0
        start = self._replacer.phrase_start(buffered[:end])
        if start is not None:
            # Hold the whole word the phrase starts in.
            held = next(i for i, t in enumerate(tokens) if t.end() > start)
        else:
            held = whole
        if held == len(tokens):
            cut = len(buffered)
        elif held:
            cut = tokens[held - 1].end()
        else:
            cut = 0
        # A complete match the cut would split is written whole: nothing
        # later can change it, and the words it holds cannot begin another.
        for match in self._replacer.matches(buffered[:end]):
            if match.start() < cut < match.end():
                cut = match.end()
        self._pending = buffered[cut:]
        return self._replacer.apply(buffered[:cut])

    def flush(self) -> str:
        """The input has ended: return the rest, replaced."""
        text, self._pending = self._pending, ""
        return self._replacer.apply(text)
