"""Write spoken numbers as digits: "ninety nine" as 99, for every engine.

Nemotron writes numbers the way they are spoken, and the other engines do
now and then. text2num's alpha2digit converts them in the languages it
knows; small isolated numbers stay words ("one of the models"), which is
right in running text.

Streamed text arrives in pieces that can split a number ("ninety" +
" nine", "three point" + " five") or even a word ("fo" + "rty"), so a
Stream holds back the number words at the end of a piece until the next
piece shows whether the number goes on. Converting the part before them
on its own gives the same text as converting the whole, because that part
ends with a word that is not a number.

No audio or X11 dependencies, so it can be tested on its own.
"""

import re

from text_to_num import alpha2digit, text2num

# The languages alpha2digit knows; others are left as they are.
LANGUAGES = ("en", "de", "fr", "es", "pt", "it", "nl")

# Words that continue a number after a number word: "a hundred and five",
# "three point five", "minus two".
CONNECTORS = {
    "en": {"and", "point", "minus"},
    "de": {"und", "komma", "minus"},
}

# The words numbers are made of, to tell whether the start of a word cut
# off at the end of a piece can still become one ("fo" of "forty",
# "neunund" of "neunundneunzig"). Only for the languages listed here; in
# the others a cut-off word is not held back.
ATOMS = {
    "en": (
        "zero one two three four five six seven eight nine ten eleven twelve "
        "thirteen fourteen fifteen sixteen seventeen eighteen nineteen twenty "
        "thirty forty fifty sixty seventy eighty ninety hundred thousand "
        "million billion trillion first second third fourth fifth sixth "
        "seventh eighth ninth tenth eleventh twelfth twentieth thirtieth "
        "fortieth fiftieth sixtieth seventieth eightieth ninetieth hundredth "
        "thousandth millionth"
    ).split(),
    "de": (
        "null ein eins eine zwei zwo drei vier fünf sechs sieben acht neun "
        "zehn elf zwölf sechzehn siebzehn zwanzig dreißig dreissig vierzig "
        "fünfzig sechzig siebzig achtzig neunzig hundert tausend million "
        "millionen milliarde milliarden und ste te sten ten"
    ).split(),
}

_TOKEN = re.compile(r"\S+")


class Numerals:
    """Converts spoken numbers in whole texts; stream() for pieces.

    Off (falsy) for a language alpha2digit does not know, an unset
    language, or enabled=False: apply() then returns the text unchanged.
    """

    def __init__(self, language: str | None = None, enabled: bool = True):
        language = (language or "").lower().split("-")[0].split("_")[0]
        self.language = language if enabled and language in LANGUAGES else None
        self._connectors = CONNECTORS.get(self.language, set())
        # Longest first, so a word is taken apart into the longest atoms.
        self._atoms = sorted(ATOMS.get(self.language, ()), key=len, reverse=True)

    def __bool__(self) -> bool:
        return self.language is not None

    def apply(self, text: str) -> str:
        """Return `text` with its spoken numbers as digits."""
        if not self or not text.strip():
            return text
        return alpha2digit(text, self.language)

    def is_number(self, word: str) -> bool:
        """Whether `word` on its own is a number word ("ninety", "Nine")."""
        try:
            text2num(word.lower(), self.language)
        except ValueError:
            return False
        return True

    def may_continue(self, word: str) -> bool:
        """Whether a later piece could make the cut-off `word` a number word.

        "fo" can become "forty", "seven" "seventeen", "neunund"
        "neunundneunzig"; "dupli" cannot become a number.
        """
        if not self._atoms:
            return False
        *whole, rest = word.lower().split("-")
        if not all(self.is_number(piece) for piece in whole):
            return False
        while rest:
            if any(atom.startswith(rest) for atom in self._atoms):
                return True
            atom = next((a for a in self._atoms if rest.startswith(a)), None)
            if atom is None:
                return False
            rest = rest[len(atom) :]
        return True

    def hold_from(self, text: str, word_end: bool = False) -> int:
        """Where the end of `text` that a later piece may still change starts.

        That end is the number words `text` ends with, the connectors
        between them ("hundred and", "three point"), and a cut-off last
        word that may become a number word, or a connector after one ("a"
        of "and" after "hundred"), unless `word_end` says the last word is
        whole. A connector without a number before it ("cats and") is not
        held. Returns len(text) when nothing is held.
        """
        tokens = list(_TOKEN.finditer(text))
        held = len(tokens)
        if tokens and not word_end and tokens[-1].end() == len(text):
            word = tokens[-1].group()
            after_number = held > 1 and self.is_number(tokens[-2].group())
            may_connect = after_number and any(
                c.startswith(word.lower()) for c in self._connectors
            )
            if not (self.may_continue(word) or may_connect):
                return len(text)
            held -= 1
        while held and (
            self.is_number(tokens[held - 1].group())
            or tokens[held - 1].group().lower() in self._connectors
        ):
            held -= 1
        # A run of held words starts with a number word, not a connector.
        while held < len(tokens) and tokens[held].group().lower() in self._connectors:
            held += 1
        if held == len(tokens):
            return len(text)
        return tokens[held - 1].end() if held else 0

    def stream(self) -> "Stream":
        return Stream(self)


class Stream:
    """Converts text that arrives in pieces; nothing is lost or repeated.

    The concatenated output of feed() and flush() equals apply() on the
    concatenated input.
    """

    def __init__(self, numerals: Numerals):
        self._numerals = numerals
        self._pending = ""

    @property
    def holding(self) -> bool:
        """Whether text is held back: what was returned ends with a whole word."""
        return bool(self._pending)

    def feed(self, text: str, word_end: bool = False) -> str:
        """Add a piece; return the converted text no later piece can change.

        `word_end` says the piece ends with a whole word.
        """
        if not self._numerals:
            return text
        buffered = self._pending + text
        cut = self._numerals.hold_from(buffered, word_end)
        self._pending = buffered[cut:]
        return self._numerals.apply(buffered[:cut])

    def preview(self, text: str = "") -> str:
        """What feed(text) and flush() would return together; nothing changes."""
        return self._numerals.apply(self._pending + text)

    def flush(self) -> str:
        """The input has ended: return the rest, converted."""
        text, self._pending = self._pending, ""
        return self._numerals.apply(text)


class Chain:
    """A numerals Stream feeding a replacements Stream, one stream for both.

    Numbers are converted first, so a replacement sees "gpt 4", not "gpt
    four". Same interface as the two streams: feed(), preview(), flush().
    """

    def __init__(self, numbers: Stream, replacing):
        self._numbers = numbers
        self._replacing = replacing

    def feed(self, text: str, word_end: bool = False) -> str:
        converted = self._numbers.feed(text, word_end)
        if not converted:
            return ""
        # Text held back by the numbers starts with a new word, so what
        # came through ends with a whole one.
        return self._replacing.feed(
            converted, word_end=word_end or self._numbers.holding
        )

    def preview(self, text: str = "") -> str:
        return self._replacing.preview(self._numbers.preview(text))

    def flush(self) -> str:
        rest = self._numbers.flush()
        written = self._replacing.feed(rest, word_end=True) if rest else ""
        return written + self._replacing.flush()
