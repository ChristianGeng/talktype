"""Tell a real key press from keyboard auto-repeat.

Holding a key makes X send repeated press events (typically after 500 ms,
then about 30 per second) with no release in between. The record hotkey is a
toggle, so acting on those repeats starts and stops recording over and over
when the key is held a little too long, for example until the start beep.
A press therefore only counts once the key has been released since the last
one.

No pynput or X11 dependencies, so it can be tested on its own.
"""


class PressGate:
    """Let through the first press of a key and nothing until its release."""

    def __init__(self):
        self._held = set()

    def press(self, key) -> bool:
        """Return True for a new press, False for an auto-repeat."""
        if key in self._held:
            return False
        self._held.add(key)
        return True

    def release(self, key):
        """Forget the key, so its next press counts again."""
        self._held.discard(key)


MODES = ("toggle", "hold", "auto")


class RecordKey:
    """Decide what a press or a release of the record key does.

    toggle: a press starts recording, the next press stops it (upstream).
    hold:   a press starts, its release stops (push-to-talk).
    auto:   a press starts at once; releasing after at least hold_s stops
            (hold to talk), a shorter tap keeps recording until the next
            press (tap to toggle). No start delay and no second key.

    Returns "start", "stop" or None; the caller owns the recording state and
    passes it in, and ignores auto-repeat presses (PressGate) before this.
    """

    def __init__(self, mode: str = "toggle", hold_s: float = 0.5):
        if mode not in MODES:
            raise ValueError(f"record mode must be one of {', '.join(MODES)}, not {mode!r}")
        self.mode = mode
        self.hold_s = hold_s
        self._started_at = None  # time of the press that started this recording
        self._down = False

    @property
    def held(self) -> bool:
        """The record key is down: its press was seen, its release not yet."""
        return self._down

    def press(self, now: float, recording: bool):
        self._down = True
        if recording:
            self._started_at = None
            return "stop"
        self._started_at = now
        return "start"

    def release(self, now: float, recording: bool):
        self._down = False
        started, self._started_at = self._started_at, None
        if not recording or started is None or self.mode == "toggle":
            return None
        if self.mode == "hold" or now - started >= self.hold_s:
            return "stop"
        return None
