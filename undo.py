"""What the undo key removes: the last dictation, if that is still safe.

Each recording starts a new dictation; the words it writes are noted with
the route they took. The undo key then removes them where they went:

emacs: talktype.el's `talktype-undo-last`, which checks the text itself.
kitty: one DEL per character written (code points, after replacements),
    sent into the same kitty window, only while that window still has the
    focus, no other key was pressed since the recording started (a moved
    cursor or typed text would make the count wrong), and the dictation
    wrote no line break (DEL doesn't join lines in a shell prompt).
Other routes (terminal-paste, type, paste) can't undo.

A dictation is undone once: a decision to remove it forgets it, also if
the removal then fails (it may have half happened). A refusal here
changes nothing, so pressing again gives the same answer. No pynput or X11 dependencies, so it can be tested
on its own; the caller runs the commands.
"""

import threading
from dataclasses import dataclass

UNDOABLE = ("emacs", "kitty")


@dataclass
class Decision:
    """What one press of the undo key does.

    action: "emacs" or "kitty" (remove it), "refuse", "unsupported",
    "nothing" (nothing to undo) or "busy" (recording or transcribing).
    """

    action: str
    reason: str = ""
    route: str = ""
    chars: int = 0
    window: object = None  # the kitty window to send the DELs to
    text: str = ""  # what the dictation wrote, for talktype-undo-last


class _Dictation:
    def __init__(self):
        self.routes = []  # in the order they were first used
        self.text = ""
        self.window = None


class LastDictation:
    """The last dictation and the keys pressed since its recording started.

    Thread-safe: the key listener, the writing thread and the undo key's
    thread call it. Calls never wait for anything but the short lock, so
    the key listener is not held up.
    """

    def __init__(self):
        self._lock = threading.Lock()
        self._current = None
        self._keys = 0

    def begin(self):
        """A recording started: it replaces what is remembered."""
        with self._lock:
            self._current = _Dictation()
            self._keys = 0

    def wrote(self, route: str, text: str, window=None):
        """text reached the window by route; window identifies a kitty window."""
        with self._lock:
            d = self._current
            if d is None or not text:
                return
            if route not in d.routes:
                d.routes.append(route)
            if route == "kitty" and d.window is None:
                d.window = window
            d.text += text

    def key_pressed(self):
        """A key other than TalkType's own went down."""
        with self._lock:
            self._keys += 1

    def undo(self, busy: bool, focused=None) -> Decision:
        """Decide what the undo key does now.

        focused(window) returns the kitty window that has the focus, in the
        same form as the window passed to wrote(); it runs without the lock
        held, so it may take a while. A decision to remove forgets the
        dictation, so it is removed only once.
        """
        if busy:
            return Decision("busy", "recording or transcribing")
        with self._lock:
            d, keys = self._current, self._keys
        if d is None or not d.routes:
            return Decision("nothing", "nothing to undo")
        if len(d.routes) > 1:
            return Decision("refuse", "the dictation took several routes (" + ", ".join(d.routes) + ")")
        route = d.routes[0]
        if route not in UNDOABLE:
            return Decision("unsupported", f"not supported for route {route}", route=route)
        if route == "kitty":
            if "\n" in d.text or "\r" in d.text:
                return Decision("refuse", "the dictation has a line break", route=route)
            if keys:
                return Decision("refuse", "a key was pressed since the dictation", route=route)
            if d.window is None:
                return Decision("refuse", "the kitty window is unknown", route=route)
            now = focused(d.window) if focused is not None else None
            if now != d.window:
                return Decision("refuse", "another window has the focus", route=route)
        with self._lock:
            if self._current is not d:
                return Decision("nothing", "nothing to undo")
            if self._keys != keys:
                return Decision("refuse", "a key was pressed since the dictation", route=route)
            self._current = None
        return Decision(route, route=route, chars=len(d.text), window=d.window, text=d.text)
