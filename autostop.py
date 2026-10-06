"""Stop a recording that nobody stops.

A key that sends press and release at once (Fn+P on a ThinkPad) turned
"hold to talk" into "tap to start", and recordings ran for hours. AutoStop
ends a recording after a stretch without speech, or at a maximum length,
with a warning shortly before the silence stop. Speech means a 50 ms
segment above the RMS threshold that has_speech() uses.

No pynput, X11 or sounddevice dependencies, so it can be tested on its own.
"""

import numpy as np

SPEECH_RMS = 0.01  # has_speech()'s threshold
SEGMENT_S = 0.05
WARN_BEFORE_S = 10  # the warning comes this long before the silence stop


def is_loud(block: np.ndarray, sample_rate: int = 16000,
            threshold: float = SPEECH_RMS, segment_s: float = SEGMENT_S) -> bool:
    """True if a 50 ms segment of the audio block is above the threshold.

    Like has_speech(), a trailing piece shorter than half a segment is
    skipped; a block shorter than that counts as one segment.
    """
    block = np.asarray(block, dtype=np.float32).reshape(-1)
    seg = max(1, int(sample_rate * segment_s))
    full = len(block) // seg * seg
    pieces = [block[:full].reshape(-1, seg)] if full else []
    tail = block[full:]
    if len(tail) >= seg // 2 or (not full and len(tail)):
        pieces.append(tail.reshape(1, -1))
    return any(
        bool(np.any(np.sqrt(np.mean(p ** 2, axis=1)) > threshold)) for p in pieces
    )


class AutoStop:
    """When a recording should warn or stop by itself.

    silence_stop_s: seconds without speech until the stop (0: never).
    max_s:          longest recording in seconds (0: no limit).
    warn_s:         seconds of silence until the warning; by default
                    WARN_BEFORE_S before the stop, none for a stop that short.

    heard(now) marks speech; check(now, held) answers None, "warn",
    "stop-silence" or "stop-max". The warning comes once per stretch of
    silence. While the record key is held there is no silence warning or
    stop, but the maximum length still applies.
    """

    def __init__(self, silence_stop_s: float = 60, max_s: float = 600,
                 warn_s: float | None = None, now: float = 0.0):
        self.silence_stop_s = silence_stop_s
        self.max_s = max_s
        if warn_s is None and silence_stop_s > WARN_BEFORE_S:
            warn_s = silence_stop_s - WARN_BEFORE_S
        self.warn_s = warn_s if silence_stop_s else None
        self._started = now
        self._last_speech = now
        # Speech is marked from the audio thread and checked from another;
        # remembering which silence was warned about needs no lock.
        self._warned_for = None

    def heard(self, now: float):
        self._last_speech = now

    def check(self, now: float, held: bool = False):
        if self.max_s and now - self._started >= self.max_s:
            return "stop-max"
        if held or not self.silence_stop_s:
            return None
        last = self._last_speech
        silence = now - last
        if silence >= self.silence_stop_s:
            return "stop-silence"
        if self.warn_s is not None and silence >= self.warn_s and self._warned_for != last:
            self._warned_for = last
            return "warn"
        return None

    def describe(self, verdict: str) -> str:
        """Why the recording ended, for the log."""
        if verdict == "stop-max":
            return f"max length {self.max_s:g} s"
        return f"silence {self.silence_stop_s:g} s"
