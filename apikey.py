"""The API key for the API mode, from an environment variable or a command.

TalkType usually runs as a systemd user service, which doesn't see the
variables a login shell exports, and the key should not sit in the config,
the unit or the journal. So besides an environment variable, a command can
print it (`gopass show -o personal/api/mistral/mistral_api_key`). The
command runs on the first request, not at start, when a password store may
still be locked; the key is kept in memory only and never printed.

No audio or X11 dependencies, so it can be tested on its own.
"""

import os
import shlex
import subprocess

COMMAND_TIMEOUT_S = 60  # time for a pinentry prompt, if the store is locked


class ApiKeyError(Exception):
    """The key could not be read; the message never contains it."""


class ApiKey:
    """The key the API mode sends as `Authorization: Bearer <key>`.

    Off (falsy) without an environment variable or a command: requests go
    without the header, as to a local server.
    """

    def __init__(self, env: str | None = None, command: str | None = None):
        self.env = env or None
        self.command = command or None
        self._key: str | None = None

    def __bool__(self) -> bool:
        return bool(self.env or self.command)

    def get(self) -> str:
        """The key: the variable if it is set, else the command's first line."""
        if self._key:
            return self._key
        value = os.environ.get(self.env, "").strip() if self.env else ""
        if not value and self.command:
            value = self._run()
        if not value:
            raise ApiKeyError(self._missing())
        self._key = value
        return value

    def auth(self):
        """The key as a requests `auth=`, None when off.

        As auth rather than a header: requests replaces an Authorization
        header with matching ~/.netrc credentials, but not its own auth.
        """
        if not self:
            return None
        key = self.get()

        def bearer(request):
            request.headers["Authorization"] = f"Bearer {key}"
            return request

        return bearer

    def forget(self):
        """The API refused the key: read it again on the next request."""
        self._key = None

    def describe(self) -> str:
        """Where the key comes from, for messages: the setting, never the key."""
        sources = []
        if self.env:
            sources.append(f"environment variable {self.env}")
        if self.command:
            sources.append(f"command '{self.command}'")
        return " or ".join(sources) or "no api_key_env or api_key_command"

    def _run(self) -> str:
        # Windows takes the command line as it is; shlex.split would drop
        # the backslashes of C:\tools\op.exe.
        args = self.command if os.name == "nt" else shlex.split(self.command)
        try:
            done = subprocess.run(
                args,
                capture_output=True,
                text=True,
                timeout=COMMAND_TIMEOUT_S,
                check=False,
            )
        except (OSError, ValueError) as e:
            raise ApiKeyError(f"api_key_command could not run: {e}") from None
        except subprocess.TimeoutExpired:
            raise ApiKeyError(
                f"api_key_command took longer than {COMMAND_TIMEOUT_S} s"
            ) from None
        if done.returncode != 0:
            # stderr only: stdout would be the key, if half of it came out.
            reason = (done.stderr or "").strip().splitlines()
            raise ApiKeyError(
                f"api_key_command failed (exit {done.returncode})"
                + (f": {reason[0]}" if reason else "")
            )
        lines = (done.stdout or "").strip().splitlines()
        return lines[0].strip() if lines else ""

    def _missing(self) -> str:
        if self.env and not self.command:
            return f"environment variable {self.env} is not set or empty"
        return f"no API key from {self.describe()}"
