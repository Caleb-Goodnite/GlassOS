"""GlassOS keyboard shortcuts: the actions you can bind, the ready-made styles, and your choice.

Settings > Keyboard Shortcuts picks a style (GlassOS, Windows, Linux, macOS) or your own
Custom set. The choice is kept in ~/.config/glassos/settings.json ("keys_preset", and the
whole Custom set in "keys_custom") and written out for the desktop as ~/.config/hypr/glass-keys.lua,
which hyprland.lua reads to make the bindings.

A shortcut is written the way Hyprland writes it: "SUPER + SHIFT + S". Two special forms:
  "SUPER"          tap Super on its own (it fires when Super is let go, if nothing else was pressed)
  "... + {n}"      the keys 1 to 9 (desktop number), for actions marked "n"
  "... + {dir}"    the four arrow keys, for actions marked "dir"
An action can have more than one shortcut; an empty list means it has none.
"""
import json
import os

HOME = os.path.expanduser("~")
CFG = os.environ.get("XDG_CONFIG_HOME", os.path.join(HOME, ".config"))
STATE = os.path.join(CFG, "glassos", "settings.json")
LUA = os.path.join(CFG, "hypr", "glass-keys.lua")

# (id, section, description, kind) - kind is "" for a plain key, "n" for 1..9, "dir" for arrows.
# hyprland.lua has the same ids, and says what each one does.
ACTIONS = [
    ("search",        "Apps",     "Search and open apps", ""),
    ("terminal",      "Apps",     "Terminal", ""),
    ("files",         "Apps",     "Files", ""),
    ("browser",       "Apps",     "Web browser", ""),
    ("lens",          "Apps",     "Glass Lens (what's using my computer)", ""),
    ("settings",      "Apps",     "Settings", ""),
    ("close",         "Windows",  "Close window", ""),
    ("fullscreen",    "Windows",  "Full screen", ""),
    ("minimize",      "Windows",  "Minimize window", ""),
    ("float",         "Windows",  "Tile / float window", ""),
    ("center",        "Windows",  "Center window", ""),
    ("snap_left",     "Windows",  "Snap window to the left half", ""),
    ("snap_right",    "Windows",  "Snap window to the right half", ""),
    ("focus",         "Windows",  "Move focus to the window in that direction", "dir"),
    ("cycle",         "Windows",  "Switch to the next window", ""),
    ("ws_go",         "Desktops", "Go to desktop 1–9", "n"),
    ("ws_move",       "Desktops", "Move window to desktop 1–9", "n"),
    ("ws_next",       "Desktops", "Next desktop", ""),
    ("ws_prev",       "Desktops", "Previous desktop", ""),
    ("lock",          "System",   "Lock screen", ""),
    ("power",         "System",   "Shut down, restart or log out", ""),
    ("shot_screen",   "System",   "Screenshot of the whole screen", ""),
    ("shot_area",     "System",   "Screenshot of an area", ""),
    ("notif_clear",   "System",   "Clear notifications", ""),
    ("notif_restore", "System",   "Show last notification", ""),
    ("shortcuts",     "System",   "Show keyboard shortcuts", ""),
]
SECTIONS = ["Apps", "Windows", "Desktops", "System"]
KIND = {a[0]: a[3] for a in ACTIONS}
DESC = {a[0]: a[2] for a in ACTIONS}

# The styles. "glassos" is what GlassOS has always used (and hyprland.lua's fallback).
PRESETS = {
    "glassos": {
        "search": ["SUPER"], "terminal": ["SUPER + RETURN"], "files": ["SUPER + E"], "browser": ["SUPER + B"],
        "lens": ["SUPER + U"], "settings": ["SUPER + I"],
        "close": ["SUPER + Q"], "fullscreen": ["SUPER + F"], "minimize": ["SUPER + M"], "float": ["SUPER + T"],
        "center": ["SUPER + C"], "snap_left": ["SUPER + left"], "snap_right": ["SUPER + right"],
        "focus": ["SUPER + ALT + {dir}"], "cycle": ["ALT + TAB"],
        "ws_go": ["SUPER + {n}"], "ws_move": ["SUPER + SHIFT + {n}"],
        "ws_next": ["SUPER + CTRL + right"], "ws_prev": ["SUPER + CTRL + left"],
        "lock": ["SUPER + L"], "power": ["SUPER + ALT + BACKSPACE", "SUPER + ALT + DELETE"],
        "shot_screen": ["Print"], "shot_area": ["SUPER + SHIFT + S"],
        "notif_clear": ["SUPER + N"], "notif_restore": ["SUPER + SHIFT + N"], "shortcuts": ["SUPER + SLASH"],
    },
    "windows": {
        "search": ["SUPER"], "terminal": ["SUPER + RETURN"], "files": ["SUPER + E"], "browser": ["SUPER + B"],
        "lens": ["CTRL + SHIFT + ESCAPE"], "settings": ["SUPER + I"],
        "close": ["ALT + F4"], "fullscreen": ["SUPER + up"], "minimize": ["SUPER + down"], "float": ["SUPER + T"],
        "center": ["SUPER + C"], "snap_left": ["SUPER + left"], "snap_right": ["SUPER + right"],
        "focus": ["SUPER + ALT + {dir}"], "cycle": ["ALT + TAB"],
        "ws_go": ["SUPER + {n}"], "ws_move": ["SUPER + SHIFT + {n}"],
        "ws_next": ["SUPER + CTRL + right"], "ws_prev": ["SUPER + CTRL + left"],
        "lock": ["SUPER + L"], "power": ["CTRL + ALT + DELETE"],
        "shot_screen": ["Print"], "shot_area": ["SUPER + SHIFT + S"],
        "notif_clear": ["SUPER + N"], "notif_restore": ["SUPER + SHIFT + N"], "shortcuts": ["SUPER + SLASH"],
    },
    "linux": {  # GNOME and KDE's usual keys
        "search": ["SUPER"], "terminal": ["CTRL + ALT + T"], "files": ["SUPER + E"], "browser": ["SUPER + B"],
        "lens": ["CTRL + ESCAPE"], "settings": ["SUPER + I"],
        "close": ["ALT + F4"], "fullscreen": ["SUPER + up"], "minimize": ["SUPER + H"], "float": ["SUPER + T"],
        "center": ["SUPER + C"], "snap_left": ["SUPER + left"], "snap_right": ["SUPER + right"],
        "focus": ["SUPER + ALT + {dir}"], "cycle": ["ALT + TAB"],
        "ws_go": ["SUPER + {n}"], "ws_move": ["SUPER + SHIFT + {n}"],
        "ws_next": ["SUPER + PAGE_DOWN", "CTRL + ALT + right"], "ws_prev": ["SUPER + PAGE_UP", "CTRL + ALT + left"],
        "lock": ["SUPER + L"], "power": ["CTRL + ALT + DELETE"],
        "shot_screen": ["Print"], "shot_area": ["SHIFT + Print"],
        "notif_clear": ["SUPER + N"], "notif_restore": ["SUPER + SHIFT + N"], "shortcuts": ["SUPER + SLASH"],
    },
    "macos": {  # Super is the ⌘ Command key, Alt is ⌥ Option
        "search": ["SUPER + SPACE"], "terminal": ["SUPER + RETURN"], "files": ["SUPER + ALT + SPACE"],
        "browser": ["SUPER + B"], "lens": ["SUPER + ALT + ESCAPE"], "settings": ["SUPER + COMMA"],
        "close": ["SUPER + W", "SUPER + Q"], "fullscreen": ["CTRL + SUPER + F"], "minimize": ["SUPER + M"],
        "float": ["SUPER + T"], "center": ["CTRL + ALT + C"],
        "snap_left": ["CTRL + ALT + left"], "snap_right": ["CTRL + ALT + right"],
        "focus": ["SUPER + ALT + {dir}"], "cycle": ["SUPER + TAB"],
        "ws_go": ["SUPER + {n}"], "ws_move": ["CTRL + SHIFT + {n}"],
        "ws_next": ["CTRL + right"], "ws_prev": ["CTRL + left"],
        "lock": ["CTRL + SUPER + Q"], "power": ["CTRL + SUPER + ALT + BACKSPACE"],
        "shot_screen": ["SUPER + SHIFT + 3"], "shot_area": ["SUPER + SHIFT + 4"],
        "notif_clear": ["SUPER + N"], "notif_restore": ["SUPER + SHIFT + N"], "shortcuts": ["SUPER + SHIFT + SLASH"],
    },
}
STYLES = [  # (id, name, one-line description) in the order Settings shows them
    ("glassos", "GlassOS", "GlassOS's own keys: Super with a letter for almost everything."),
    ("windows", "Windows", "Like Windows: Alt+F4 closes, Super+L locks, Ctrl+Shift+Esc for Glass Lens, Ctrl+Alt+Del for power."),
    ("linux", "Linux", "Like GNOME and KDE: Ctrl+Alt+T for a terminal, Super+Page Up/Down for desktops."),
    ("macos", "macOS", "Like a Mac, with Super as ⌘: ⌘Space to search, ⌘W closes, ⌃⌘Q locks, ⌘⇧3/4 for screenshots."),
    ("custom", "Custom", "Your own: change any shortcut below."),
]
DEFAULT = "glassos"

MODS = ["SUPER", "CTRL", "ALT", "SHIFT"]
_MOD_ALIASES = {"SUPER": "SUPER", "WIN": "SUPER", "META": "SUPER", "CMD": "SUPER", "COMMAND": "SUPER", "LOGO": "SUPER",
                "MOD4": "SUPER", "CTRL": "CTRL", "CONTROL": "CTRL", "ALT": "ALT", "OPTION": "ALT", "MOD1": "ALT",
                "SHIFT": "SHIFT"}
_PRETTY = {"SUPER": "Super", "CTRL": "Ctrl", "ALT": "Alt", "SHIFT": "Shift", "RETURN": "Return", "SLASH": "/",
           "COMMA": ",", "PERIOD": ".", "BACKSPACE": "Backspace", "DELETE": "Delete", "ESCAPE": "Esc",
           "SPACE": "Space", "TAB": "Tab", "left": "←", "right": "→", "up": "↑", "down": "↓",
           "PAGE_UP": "Page Up", "PAGE_DOWN": "Page Down", "PRIOR": "Page Up", "NEXT": "Page Down",
           "PRINT": "Print Screen", "MINUS": "-", "EQUAL": "=", "GRAVE": "`", "SEMICOLON": ";",
           "APOSTROPHE": "'", "BRACKETLEFT": "[", "BRACKETRIGHT": "]", "BACKSLASH": "\\", "HOME": "Home",
           "END": "End", "INSERT": "Insert", "{n}": "1…9", "{dir}": "arrows"}
_SYMBOLS = {",": "COMMA", ".": "PERIOD", "/": "SLASH", "-": "MINUS", "=": "EQUAL", ";": "SEMICOLON",
            "'": "APOSTROPHE", "[": "BRACKETLEFT", "]": "BRACKETRIGHT", "\\": "BACKSLASH", "`": "GRAVE",
            "ESC": "ESCAPE", "ENTER": "RETURN", "DEL": "DELETE", "PGUP": "PAGE_UP", "PGDN": "PAGE_DOWN"}


# --------------------------------------------------------------------------- writing shortcuts
def normalize(combo):
    """Tidy a shortcut someone typed ("ctrl+alt+t", "Super + l") into Hyprland's form, or None if it isn't one."""
    parts = [p.strip() for p in str(combo).replace("+", " + ").split("+")]
    parts = [p for p in parts if p]
    if not parts:
        return None
    mods, key = [], None
    for p in parts:
        m = _MOD_ALIASES.get(p.upper())
        if m and key is None and m not in mods:
            mods.append(m)
        elif key is None:
            key = p
        else:
            return None  # two plain keys
    mods = [m for m in MODS if m in mods]
    if key is None:
        return "SUPER" if mods == ["SUPER"] else None  # only Super can be tapped on its own
    if key.lower() in ("left", "right", "up", "down"):
        key = key.lower()
    elif key in ("{n}", "{dir}"):
        pass
    elif key.lower() in ("print", "sys_req"):
        key = "Print"
    else:
        key = _SYMBOLS.get(key.upper(), key.upper())
    return " + ".join(mods + [key])


def pretty_key(p):
    if p in _PRETTY:
        return _PRETTY[p]
    if p.upper() in _PRETTY:
        return _PRETTY[p.upper()]
    if len(p) <= 1 or (p[0] in "Ff" and p[1:].isdigit()):
        return p.upper()
    return p.replace("_", " ").title()


def pretty(combo):
    """"SUPER + SHIFT + S" -> "Super + Shift + S" for showing on screen."""
    if combo == "SUPER":
        return "Super (tap)"
    return " + ".join(pretty_key(p.strip()) for p in combo.split("+"))


def expand(combo, kind):
    """Every concrete key a shortcut stands for (1..9 or the arrows), for spotting clashes."""
    if kind == "n" or "{n}" in combo:
        return [combo.replace("{n}", str(i)) for i in range(1, 10)]
    if kind == "dir" or "{dir}" in combo:
        return [combo.replace("{dir}", d) for d in ("left", "right", "up", "down")]
    return [combo]


# --------------------------------------------------------------------------- your choice
def _load():
    try:
        with open(STATE) as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def current_preset(st=None):
    st = _load() if st is None else st
    p = st.get("keys_preset", DEFAULT)
    return p if p in PRESETS or p == "custom" else DEFAULT


def effective(st=None):
    """The shortcuts in use now: {action id: [combo, ...]}."""
    st = _load() if st is None else st
    p = current_preset(st)
    if p != "custom":
        return {k: list(v) for k, v in PRESETS[p].items()}
    keys = {k: list(v) for k, v in PRESETS[DEFAULT].items()}  # (anything missing from your set)
    for k, v in (st.get("keys_custom") or {}).items():
        if k in KIND and isinstance(v, list):
            keys[k] = [c for c in (normalize(x) for x in v) if c]
    return keys


def clashes(keys):
    """{action id: [other action ids that share one of its keys]}."""
    owner = {}
    for aid, combos in keys.items():
        for c in combos:
            for k in expand(c, KIND.get(aid, "")):
                owner.setdefault(k.upper(), []).append(aid)
    out = {}
    for ids in owner.values():
        if len(set(ids)) > 1:
            for a in ids:
                out.setdefault(a, set()).update(set(ids) - {a})
    return {a: sorted(v) for a, v in out.items()}


def write_lua(keys, preset):
    """Write ~/.config/hypr/glass-keys.lua for hyprland.lua to read."""
    def q(s):
        return json.dumps(s, ensure_ascii=False)
    lines = ["-- Written by GlassOS Settings > Keyboard Shortcuts. It's rewritten whenever you change a",
             "-- shortcut there, so put your own bindings in custom.lua instead.",
             "return {", f"    preset = {q(preset)},", "    keys = {"]
    for aid, *_ in ACTIONS:
        combos = keys.get(aid, [])
        lines.append(f"        {aid} = {{ {', '.join(q(c) for c in combos)} }},")
    lines += ["    },", "}"]
    os.makedirs(os.path.dirname(LUA), exist_ok=True)
    with open(LUA + ".tmp", "w") as f:
        f.write("\n".join(lines) + "\n")
    os.replace(LUA + ".tmp", LUA)
