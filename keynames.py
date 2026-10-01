"""Names for keys the listener reports, as get_hotkey accepts them.

Shared by talktype.py and the setup wizard, so the wizard can name a key
without importing the whole app.
"""

import functools
import platform

from pynput import keyboard

SYSTEM = platform.system()

if SYSTEM == "Linux":
    import Xlib.keysymdef
    from Xlib import XK


@functools.cache
def _x_keysyms() -> tuple[dict[str, int], dict[int, str]]:
    """All X keysym names python-xlib knows, as name -> keysym and keysym -> name.

    python-xlib spells XF86 keys with an underscore (XF86_Tools); X itself,
    xev and xmodmap write XF86Tools, which is the name used here.
    """
    for group in Xlib.keysymdef.__all__:
        XK.load_keysym_group(group)
    by_name, by_keysym = {}, {}
    for attr, keysym in vars(XK).items():
        if not attr.startswith("XK_") or not isinstance(keysym, int):
            continue
        name = attr[3:]
        if name.startswith("XF86_"):
            name = "XF86" + name[5:]
        by_name[name] = keysym
        by_keysym.setdefault(keysym, name)
    return by_name, by_keysym


def x_keysym(name: str) -> int:
    """The X keysym of a key name such as XF86Tools, xf86tools, XF86_Tools or
    0x1008ff81, or 0 if there is none. Case only matters where it tells two
    keys apart (a and A)."""
    if name.lower().startswith("0x"):
        try:
            keysym = int(name, 16)
        except ValueError:
            return 0
        return max(0, keysym)
    if name.lower().startswith("xf86_"):
        name = name[:4] + name[5:]
    by_name, _ = _x_keysyms()
    if name in by_name:
        return by_name[name]
    matches = {keysym for n, keysym in by_name.items() if n.lower() == name.lower()}
    return matches.pop() if len(matches) == 1 else 0


def x_keysym_name(keysym: int) -> str:
    """The X name of a keysym (XF86Tools), or its number if it has none."""
    return _x_keysyms()[1].get(keysym, f"{keysym:#x}")


def hotkey_label(key_name: str) -> str:
    """How the status lines name a key: F10 for pynput names, XF86Tools for X names."""
    name = key_name.strip()
    if isinstance(getattr(keyboard.Key, name.lower(), None), keyboard.Key):
        return key_name.upper()
    keysym = x_keysym(name) if SYSTEM == "Linux" else 0
    return x_keysym_name(keysym) if keysym else key_name.upper()


def hotkey_name(key) -> str | None:
    """The name get_hotkey accepts for a key from the listener, or None."""
    if isinstance(key, keyboard.Key):
        return key.name
    if SYSTEM == "Linux" and isinstance(key, keyboard.KeyCode) and key.vk:
        return x_keysym_name(key.vk)
    return None
