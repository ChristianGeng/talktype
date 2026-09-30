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
