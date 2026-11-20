"""Settings for every test."""

import pytest


@pytest.fixture(autouse=True)
def no_profile_of_the_developer(monkeypatch):
    """A profile.yaml on the machine running the tests must not change them (#89).

    Tests of the profile itself remove the variable again.
    """
    monkeypatch.setenv("TALKTYPE_PROFILE", "none")
