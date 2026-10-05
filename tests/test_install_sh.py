"""install.sh: syntax, shellcheck, and the commands its dry run prints."""

import os
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "install.sh"
SPEC = "'talktype[local] @ git+https://github.com/ChristianGeng/talktype'"


def dry_run(tmp_path, path, *args, **env):
    """Run install.sh in dry-run mode from tmp_path, with HOME in tmp_path."""
    home = tmp_path / "home"
    home.mkdir(exist_ok=True)
    return subprocess.run(
        ["bash", str(SCRIPT), *args],
        cwd=tmp_path,
        env={"PATH": path, "HOME": str(home), "INSTALL_DRY_RUN": "1", **env},
        capture_output=True,
        text=True,
        check=False,
    )


def commands(result):
    return [line[2:] for line in result.stdout.splitlines() if line.startswith("+ ")]


UV_STUB = """#!/bin/sh
if [ "$*" = "tool install --help" ]; then
    echo "      {flag}"
    exit 0
fi
echo 'uv must not install in a dry run' >&2
exit 1
"""


def uv_stub(tmp_path, flag):
    """A PATH whose uv answers `uv tool install --help` and fails otherwise."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    uv = bin_dir / "uv"
    uv.write_text(UV_STUB.format(flag=flag))
    uv.chmod(0o755)
    return f"{bin_dir}:/usr/bin:/bin"


@pytest.fixture
def fake_uv(tmp_path):
    """A uv recent enough for --managed-python."""
    return uv_stub(tmp_path, "--managed-python   Require use of uv-managed Python")


@pytest.fixture
def old_uv(tmp_path):
    """A uv before 0.6.17, without --managed-python."""
    return uv_stub(tmp_path, "--python-preference <PYTHON_PREFERENCE>")


def test_syntax():
    subprocess.run(["bash", "-n", str(SCRIPT)], check=True)


@pytest.mark.skipif(not shutil.which("shellcheck"), reason="shellcheck not installed")
def test_shellcheck():
    subprocess.run(["shellcheck", str(SCRIPT)], check=True)


def test_apt_with_uv_installed(tmp_path, fake_uv):
    result = dry_run(tmp_path, fake_uv, TALKTYPE_DISTRO="ubuntu")
    assert result.returncode == 0, result.stderr
    install = next(c for c in commands(result) if "apt-get install" in c).split()
    assert {"xdotool", "xclip", "x11-utils", "libportaudio2", "git", "gcc"} <= set(
        install
    )
    assert not any("venv" in package for package in install)
    assert (
        commands(result)[-1]
        == f"uv tool install --force --managed-python --python 3.13 {SPEC}"
    )
    assert not any("uv/install.sh" in c for c in commands(result))
    assert "talktype --setup" in result.stdout
    assert "venv" not in result.stdout


def test_apt_installs_what_the_readme_lists(tmp_path, fake_uv):
    readme = next(
        line
        for line in (ROOT / "README.md").read_text().splitlines()
        if line.startswith("sudo apt install")
    ).split()[3:]
    result = dry_run(tmp_path, fake_uv, TALKTYPE_DISTRO="debian")
    install = next(c for c in commands(result) if "apt-get install" in c).split()
    assert set(readme) <= set(install)


def test_installs_uv_when_missing(tmp_path):
    path = "/usr/bin:/bin"
    if shutil.which("uv", path=path):
        pytest.skip("uv is installed system-wide")
    result = dry_run(tmp_path, path, TALKTYPE_DISTRO="ubuntu")
    assert result.returncode == 0, result.stderr
    assert "uv is not installed" in result.stdout
    assert commands(result)[-2:] == [
        "curl -LsSf https://astral.sh/uv/install.sh | sh",
        f"uv tool install --force --managed-python --python 3.13 {SPEC}",
    ]


def test_finds_uv_in_local_bin(tmp_path):
    local_bin = tmp_path / "home" / ".local" / "bin"
    local_bin.mkdir(parents=True)
    (local_bin / "uv").write_text("#!/bin/sh\nexit 1\n")
    (local_bin / "uv").chmod(0o755)
    result = dry_run(tmp_path, "/usr/bin:/bin", TALKTYPE_DISTRO="ubuntu")
    assert f"Using uv: {local_bin / 'uv'}" in result.stdout
    assert not any("uv/install.sh" in c for c in commands(result))
    assert "is not on your PATH yet" in result.stdout


@pytest.mark.parametrize(
    "args, env, spec",
    [
        ((), {"TALKTYPE_EXTRAS": "local,nemotron"}, "talktype[local,nemotron]"),
        (("--extras", "local,parakeet"), {}, "talktype[local,parakeet]"),
        (("--extras=all",), {"TALKTYPE_EXTRAS": "local"}, "talktype[all]"),
        (("--extras", ""), {}, "talktype"),
    ],
)
def test_extras(tmp_path, fake_uv, args, env, spec):
    result = dry_run(tmp_path, fake_uv, *args, TALKTYPE_DISTRO="ubuntu", **env)
    assert result.returncode == 0, result.stderr
    assert commands(result)[-1] == (
        f"uv tool install --force --managed-python --python 3.13 '{spec} @ git+https://github.com/ChristianGeng/talktype'"
    )


def test_invalid_extras(tmp_path, fake_uv):
    result = dry_run(
        tmp_path, fake_uv, "--extras", "local;rm", TALKTYPE_DISTRO="ubuntu"
    )
    assert result.returncode == 1
    assert "invalid extras" in result.stderr


BUILD = ["git", "curl", "gcc"]


@pytest.mark.parametrize(
    "distro, install",
    [
        (
            "ubuntu",
            "apt-get install -y -qq xdotool xclip x11-utils libportaudio2",
        ),
        (
            "pop ubuntu debian",
            "apt-get install -y -qq xdotool xclip x11-utils libportaudio2",
        ),
        ("fedora", "yum install -y xdotool xclip xprop portaudio"),
        (
            "rocky rhel centos fedora",
            "yum install -y xdotool xclip xprop portaudio",
        ),
        (
            "manjaro arch",
            "pacman -S --needed --noconfirm xdotool xclip xorg-xprop portaudio",
        ),
        (
            "opensuse-tumbleweed opensuse suse",
            "zypper --non-interactive install xdotool xclip xprop libportaudio2",
        ),
    ],
)
def test_packages_per_distro(tmp_path, fake_uv, distro, install):
    result = dry_run(tmp_path, fake_uv, TALKTYPE_DISTRO=distro)
    assert result.returncode == 0, result.stderr
    installs = [
        c for c in commands(result) if c.startswith("sudo ") and "update" not in c
    ]
    assert installs == [f"sudo {install} {' '.join(BUILD)}"]


def test_dnf_when_there_is_one(tmp_path, fake_uv):
    bin_dir = fake_uv.split(":")[0]
    dnf = Path(bin_dir) / "dnf"
    dnf.write_text("#!/bin/sh\nexit 1\n")
    dnf.chmod(0o755)
    result = dry_run(tmp_path, fake_uv, TALKTYPE_DISTRO="fedora")
    assert "sudo dnf install -y xdotool xclip xprop portaudio git curl gcc" in commands(
        result
    )


def test_unknown_distro(tmp_path, fake_uv):
    result = dry_run(tmp_path, fake_uv, TALKTYPE_DISTRO="gentoo")
    assert result.returncode == 1
    assert "unsupported distribution 'gentoo'" in result.stderr
    assert "TALKTYPE_DISTRO" in result.stderr
    assert not commands(result)


def test_unknown_option(tmp_path, fake_uv):
    result = dry_run(tmp_path, fake_uv, "--bogus", TALKTYPE_DISTRO="ubuntu")
    assert result.returncode == 1
    assert "unknown option: --bogus" in result.stderr


def test_uses_sudo_unless_root(tmp_path, fake_uv):
    if os.geteuid() == 0:
        pytest.skip("already root")
    result = dry_run(tmp_path, fake_uv, TALKTYPE_DISTRO="ubuntu")
    assert all(c.startswith(("sudo ", "uv ")) for c in commands(result)), commands(
        result
    )


def test_python_version(tmp_path, fake_uv):
    result = dry_run(
        tmp_path, fake_uv, TALKTYPE_DISTRO="ubuntu", TALKTYPE_PYTHON="3.12"
    )
    assert (
        commands(result)[-1]
        == f"uv tool install --force --managed-python --python 3.12 {SPEC}"
    )


def test_piped_into_bash(tmp_path, fake_uv):
    """`curl … | bash` runs the script from stdin, with no file to read."""
    home = tmp_path / "home"
    home.mkdir()
    result = subprocess.run(
        ["bash", "-s", "--", "--extras", "local"],
        input=SCRIPT.read_text(),
        cwd=tmp_path,
        env={
            "PATH": fake_uv,
            "HOME": str(home),
            "INSTALL_DRY_RUN": "1",
            "TALKTYPE_DISTRO": "ubuntu",
        },
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert (
        commands(result)[-1]
        == f"uv tool install --force --managed-python --python 3.13 {SPEC}"
    )


def test_old_uv_gets_only_managed_pythons(tmp_path, old_uv):
    """Without --managed-python, uv may pick a system Python without headers."""
    result = dry_run(tmp_path, old_uv, TALKTYPE_DISTRO="ubuntu")
    assert result.returncode == 0, result.stderr
    assert commands(result)[-1] == (
        f"env UV_PYTHON_PREFERENCE=only-managed uv tool install --force --python 3.13 {SPEC}"
    )


def test_fresh_uv_gets_managed_python(tmp_path):
    """The uv the official installer brings has --managed-python."""
    path = "/usr/bin:/bin"
    if shutil.which("uv", path=path):
        pytest.skip("uv is installed system-wide")
    result = dry_run(tmp_path, path, TALKTYPE_DISTRO="ubuntu")
    assert "--managed-python" in commands(result)[-1]


@pytest.mark.parametrize("piped", [False, True], ids=["file", "piped"])
def test_help(tmp_path, fake_uv, piped):
    """`curl … | bash -s -- --help` has no script file in $0 to read."""
    argv = ["bash", "-s", "--", "--help"] if piped else ["bash", str(SCRIPT), "--help"]
    result = subprocess.run(
        argv,
        input=SCRIPT.read_text() if piped else None,
        cwd=tmp_path,
        env={"PATH": fake_uv, "HOME": str(tmp_path)},
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.startswith("TalkType installer for Linux")
    assert "TALKTYPE_EXTRAS=local,nemotron" in result.stdout
    assert "INSTALL_DRY_RUN=1" in result.stdout
