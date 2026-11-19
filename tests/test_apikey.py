"""The API key for the API mode (#87). No display needed."""

import argparse
import sys

import pytest

import apikey

SECRET = "sk-test-0123456789"


def printing(text, exit=0, stderr=""):
    """A command that prints `text` and exits with `exit`."""
    code = f"import sys; sys.stdout.write({text!r}); sys.stderr.write({stderr!r}); sys.exit({exit})"
    return f"{sys.executable} -c {code!r}"


def header(key):
    """The headers key.auth() puts on a request."""
    request = argparse.Namespace(headers={})
    key.auth()(request)
    return request.headers


def test_off_without_settings_sends_no_header():
    key = apikey.ApiKey()
    assert not key
    assert key.auth() is None


def test_key_from_the_environment(monkeypatch):
    monkeypatch.setenv("TT_TEST_KEY", f"  {SECRET}\n")
    assert header(apikey.ApiKey(env="TT_TEST_KEY")) == {"Authorization": f"Bearer {SECRET}"}


@pytest.mark.parametrize("value", [None, "", "   "])
def test_a_missing_or_blank_variable_is_an_error_naming_it(monkeypatch, value):
    if value is None:
        monkeypatch.delenv("TT_TEST_KEY", raising=False)
    else:
        monkeypatch.setenv("TT_TEST_KEY", value)
    with pytest.raises(apikey.ApiKeyError, match="TT_TEST_KEY is not set or empty"):
        apikey.ApiKey(env="TT_TEST_KEY").get()


def test_key_from_a_command_first_line_only():
    key = apikey.ApiKey(command=printing(f"{SECRET}\nlogin: me\n"))
    assert key.get() == SECRET


def test_the_command_runs_once_on_first_use(monkeypatch):
    runs = []
    real = apikey.subprocess.run
    monkeypatch.setattr(
        apikey.subprocess, "run", lambda *a, **kw: runs.append(1) or real(*a, **kw)
    )
    key = apikey.ApiKey(command=printing(SECRET))
    assert runs == []  # not at construction, when a store may be locked
    key.get()
    key.get()
    assert runs == [1]
    key.forget()  # the API refused it
    key.get()
    assert runs == [1, 1]


def test_the_variable_wins_and_the_command_is_the_fallback(monkeypatch):
    monkeypatch.setenv("TT_TEST_KEY", "from-env")
    assert (
        apikey.ApiKey(env="TT_TEST_KEY", command=printing("from-cmd")).get()
        == "from-env"
    )
    monkeypatch.delenv("TT_TEST_KEY")
    assert (
        apikey.ApiKey(env="TT_TEST_KEY", command=printing("from-cmd")).get()
        == "from-cmd"
    )


def test_a_failing_command_names_its_stderr_not_its_stdout():
    key = apikey.ApiKey(
        command=printing(SECRET, exit=1, stderr="gpg: decryption failed\n")
    )
    with pytest.raises(apikey.ApiKeyError) as e:
        key.get()
    assert "exit 1" in str(e.value) and "decryption failed" in str(e.value)
    assert SECRET not in str(e.value)


def test_an_empty_command_output_is_an_error():
    with pytest.raises(apikey.ApiKeyError, match="no API key from command"):
        apikey.ApiKey(command=printing("")).get()


def test_a_command_that_cannot_run_is_an_error():
    with pytest.raises(apikey.ApiKeyError, match="could not run"):
        apikey.ApiKey(command="/nonexistent/gopass show -o x").get()


def test_a_hanging_command_times_out(monkeypatch):
    monkeypatch.setattr(apikey, "COMMAND_TIMEOUT_S", 0.2)
    with pytest.raises(apikey.ApiKeyError, match="longer than"):
        apikey.ApiKey(command=f"{sys.executable} -c 'import time; time.sleep(5)'").get()


def test_describe_names_the_settings_never_the_key(monkeypatch):
    monkeypatch.setenv("TT_TEST_KEY", SECRET)
    key = apikey.ApiKey(env="TT_TEST_KEY", command="gopass show -o x")
    key.get()
    assert SECRET not in key.describe()
    assert "TT_TEST_KEY" in key.describe() and "gopass show -o x" in key.describe()


def test_netrc_credentials_do_not_replace_the_key(monkeypatch, tmp_path):
    # Devin Review on #88: requests swaps an Authorization header for
    # matching ~/.netrc credentials, but not its own auth.
    import requests

    netrc = tmp_path / ".netrc"
    netrc.write_text("machine api.mistral.ai login me password netrc-secret\n")
    netrc.chmod(0o600)
    monkeypatch.setenv("NETRC", str(netrc))
    monkeypatch.setenv("TT_TEST_KEY", SECRET)
    key = apikey.ApiKey(env="TT_TEST_KEY")
    request = requests.Request(
        "POST", "https://api.mistral.ai/v1/audio/transcriptions", auth=key.auth()
    )
    prepared = requests.Session().prepare_request(request)
    assert prepared.headers["Authorization"] == f"Bearer {SECRET}"


def test_windows_runs_the_command_line_unsplit(monkeypatch):
    # Devin Review on #88: shlex.split drops the backslashes of C:\tools\op.exe.
    seen = []
    monkeypatch.setattr(apikey.os, "name", "nt")
    monkeypatch.setattr(
        apikey.subprocess,
        "run",
        lambda args, **kw: seen.append(args)
        or argparse.Namespace(returncode=0, stdout="k\n", stderr=""),
    )
    command = r"C:\tools\op.exe read op://api/mistral"
    assert apikey.ApiKey(command=command).get() == "k"
    assert seen == [command]
def test_an_unmatched_quote_names_the_setting():
    # Devin Review on #88: the bare ValueError said only "No closing quotation".
    with pytest.raises(
        apikey.ApiKeyError, match="api_key_command could not run: No closing quotation"
    ):
        apikey.ApiKey(command="gopass show -o 'personal/api").get()
def test_a_blank_first_line_is_no_key():
    # CodeRabbit on #88: stripping the whole output made "login: me" the key.
    with pytest.raises(apikey.ApiKeyError, match="no API key"):
        apikey.ApiKey(command=printing("\nlogin: me\n")).get()


def test_a_key_echoed_to_stderr_stays_out_of_the_message():
    # CodeRabbit on #88: a failing command that also writes its key to stderr.
    key = apikey.ApiKey(
        command=printing(SECRET + "\n", exit=2, stderr=f"got {SECRET}\nstore locked\n")
    )
    with pytest.raises(apikey.ApiKeyError) as e:
        key.get()
    assert SECRET not in str(e.value)
    assert "store locked" in str(e.value)
