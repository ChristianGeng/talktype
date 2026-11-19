"""The API key for the API mode (#87). No display needed."""

import sys

import pytest

import apikey

SECRET = "sk-test-0123456789"


def printing(text, exit=0, stderr=""):
    """A command that prints `text` and exits with `exit`."""
    code = f"import sys; sys.stdout.write({text!r}); sys.stderr.write({stderr!r}); sys.exit({exit})"
    return f"{sys.executable} -c {code!r}"


def test_off_without_settings_sends_no_header():
    key = apikey.ApiKey()
    assert not key
    assert key.headers() == {}


def test_key_from_the_environment(monkeypatch):
    monkeypatch.setenv("TT_TEST_KEY", f"  {SECRET}\n")
    assert apikey.ApiKey(env="TT_TEST_KEY").headers() == {
        "Authorization": f"Bearer {SECRET}"
    }


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
