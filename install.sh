#!/usr/bin/env bash
# TalkType installer for Linux; ./install.sh --help lists the options.

set -euo pipefail

readonly REPO_URL="git+https://github.com/ChristianGeng/talktype"
readonly UV_INSTALLER="https://astral.sh/uv/install.sh"

extras="${TALKTYPE_EXTRAS-local}"
python="${TALKTYPE_PYTHON:-3.13}"
dry_run="${INSTALL_DRY_RUN:-0}"

die() {
    echo "install.sh: $*" >&2
    exit 1
}

# A heredoc, not the comment header: piped (curl ... | bash -s -- --help)
# there is no script file to read.
usage() {
    cat <<'USAGE'
TalkType installer for Linux: the system packages, uv, and TalkType as a
uv tool (the `talktype` command in ~/.local/bin).

  ./install.sh                         # extras: local (faster-whisper)
  ./install.sh --extras local,nemotron # or TALKTYPE_EXTRAS=local,nemotron
  INSTALL_DRY_RUN=1 ./install.sh       # print the commands, run nothing
  TALKTYPE_DISTRO=debian ./install.sh  # treat the system as this distro
  TALKTYPE_PYTHON=3.12 ./install.sh    # uv-managed Python (default 3.13)
USAGE
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --extras)
            [[ $# -ge 2 ]] || die "--extras needs a value, e.g. --extras local,nemotron"
            extras="$2"
            shift 2
            ;;
        --extras=*) extras="${1#*=}"; shift ;;
        --dry-run) dry_run=1; shift ;;
        -h|--help) usage; exit 0 ;;
        *) die "unknown option: $1 (see --help)" ;;
    esac
done

extras="${extras// /}"
[[ "$extras" =~ ^[a-z0-9,_-]*$ ]] \
    || die "invalid extras '$extras': use comma-separated names, e.g. local,nemotron"

# Prints the command in dry-run mode, runs it otherwise.
run() {
    if [[ "$dry_run" == 1 ]]; then
        local line="+" arg
        for arg in "$@"; do
            if [[ "$arg" =~ ^[A-Za-z0-9_./:=,+@-]+$ ]]; then
                line+=" $arg"
            else
                line+=" '$arg'"
            fi
        done
        echo "$line"
    else
        "$@"
    fi
}

as_root() {
    if [[ "$(id -u)" == 0 ]]; then
        run "$@"
    else
        run sudo "$@"
    fi
}

[[ "$(uname -s)" == Linux ]] \
    || die "this installer is for Linux; see README.md for Windows and macOS."

detect_distro() {
    if [[ -n "${TALKTYPE_DISTRO:-}" ]]; then
        echo "$TALKTYPE_DISTRO"
    elif [[ -r /etc/os-release ]]; then
        # shellcheck disable=SC1091
        (. /etc/os-release && echo "${ID:-} ${ID_LIKE:-}")
    elif [[ -f /etc/arch-release ]]; then
        echo arch
    fi
}

# The first word of the ID and ID_LIKE list that names a known family.
package_manager=""
read -r -a distro_ids <<< "$(detect_distro | tr '[:upper:]' '[:lower:]')"
for id in "${distro_ids[@]}"; do
    case "$id" in
        debian|ubuntu|linuxmint|pop|elementary|raspbian) package_manager=apt ;;
        fedora|rhel|centos|rocky|almalinux) package_manager=dnf ;;
        arch|manjaro|endeavouros) package_manager=pacman ;;
        opensuse*|suse|sles) package_manager=zypper ;;
        *) continue ;;
    esac
    break
done

echo "Installing TalkType..."
echo "Distribution: ${distro_ids[*]:-unknown} (packages: ${package_manager:-none})"

# xdotool and xclip type and paste, xprop tells which window is focused,
# PortAudio records; git and curl fetch TalkType and uv, gcc builds evdev
# (pynput's Linux backend, no wheels).
case "$package_manager" in
    apt)
        as_root apt-get update -qq
        as_root apt-get install -y -qq xdotool xclip x11-utils libportaudio2 git curl gcc
        ;;
    dnf)
        # xprop is its own package on Fedora 35+ and RHEL 10, where
        # xorg-x11-utils is retired; on RHEL 8/9 xorg-x11-utils provides it.
        packages=(xdotool xclip xprop portaudio git curl gcc)
        if command -v dnf >/dev/null 2>&1; then
            as_root dnf install -y "${packages[@]}"
        else
            as_root yum install -y "${packages[@]}"
        fi
        ;;
    pacman)
        as_root pacman -S --needed --noconfirm xdotool xclip xorg-xprop portaudio git curl gcc
        ;;
    zypper)
        as_root zypper --non-interactive install xdotool xclip xprop libportaudio2 git curl gcc
        ;;
    *)
        die "unsupported distribution '${distro_ids[*]:-unknown}'.
Install xdotool, xclip, xprop, PortAudio, git, curl and gcc with your package
manager, then rerun with TALKTYPE_DISTRO set to the closest of debian,
fedora, arch or opensuse, or install TalkType by hand (README.md)."
        ;;
esac

user_path="$PATH"
# Where the uv installer and `uv tool install` put their commands.
export PATH="$HOME/.local/bin:$PATH"

if command -v uv >/dev/null 2>&1; then
    echo "Using uv: $(command -v uv)"
else
    echo "uv is not installed; installing it with the official installer"
    echo "($UV_INSTALLER) into ~/.local/bin."
    if [[ "$dry_run" == 1 ]]; then
        echo "+ curl -LsSf $UV_INSTALLER | sh"
    else
        curl -LsSf "$UV_INSTALLER" | sh
        command -v uv >/dev/null 2>&1 \
            || die "uv was installed but is not in ~/.local/bin; add its directory to PATH and rerun."
    fi
fi

if [[ -n "$extras" ]]; then
    spec="talktype[$extras] @ $REPO_URL"
else
    spec="talktype @ $REPO_URL"
fi
# A uv-managed Python, never the system's: pynput needs evdev, which has no
# wheels and builds against the Python headers; uv's Pythons ship them,
# system ones often don't (python3-dev). uv before 0.6.17 has no
# --managed-python, only UV_PYTHON_PREFERENCE. The help is read whole
# before matching: grep -q would close the pipe early, and under pipefail
# uv's SIGPIPE would hide the flag. Without uv (a dry run), the fresh uv
# from the installer has the flag.
managed_flag=1
if command -v uv >/dev/null 2>&1; then
    uv_help="$(uv tool install --help 2>/dev/null || true)"
    [[ "$uv_help" == *--managed-python* ]] || managed_flag=0
fi
echo "Installing $spec (uv-managed Python $python)"
if [[ "$managed_flag" == 1 ]]; then
    run uv tool install --force --managed-python --python "$python" "$spec"
else
    run env UV_PYTHON_PREFERENCE=only-managed \
        uv tool install --force --python "$python" "$spec"
fi

echo ""
echo "Installation complete!"
echo ""
echo "Run TalkType (the setup wizard runs on first start):"
echo "  talktype"
echo "Re-run the setup wizard later:"
echo "  talktype --setup"
case ":$user_path:" in
    *":$HOME/.local/bin:"*) ;;
    *)
        echo ""
        echo "$HOME/.local/bin is not on your PATH yet; run 'uv tool update-shell'"
        echo "and open a new terminal, or call $HOME/.local/bin/talktype directly."
        ;;
esac
