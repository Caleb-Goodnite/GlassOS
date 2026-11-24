"""GlassOS sound system: sound packs, event names, and playback.

A sound pack is just a folder:

    my-pack/
      pack.ini            (optional) name, author, description, inherits, per-event volume,
                          and [files] to give an event a file with any name (boot = Startup.wav)
      boot.wav            one file per event; .wav .ogg .oga .flac .mp3 all work
      notification.ogg
      ...

Packs live in ~/.local/share/glassos/soundpacks/ (yours) and
/usr/share/glassos/soundpacks/ (shipped with the system).
"""
import configparser
import os
import shutil
import subprocess
import syslog

EXTS = (".wav", ".ogg", ".oga", ".flac", ".mp3", ".opus")

# name: (when it plays, fallback events tried in order if the pack has no file,
#        freedesktop sound-theme names that GTK apps use for the same thing)
EVENTS = {
    "boot":                  ("Computer starts (before the desktop appears)", [], ["system-bootup"]),
    "login":                 ("Desktop is ready after you log in", [], ["desktop-login", "service-login"]),
    "logout":                ("You log out", [], ["desktop-logout", "service-logout"]),
    "shutdown":              ("Shut Down is chosen", [], ["system-shutdown"]),
    "reboot":                ("Restart is chosen", ["shutdown"], []),
    "lock":                  ("Screen locks", [], []),
    "unlock":                ("Screen unlocks", [], []),
    "notification":          ("An app shows a notification", [],
                              ["message", "message-new-instant", "message-new-email",
                               "dialog-information", "complete"]),
    "notification-low":      ("A low-priority notification", ["notification"], []),
    "notification-critical": ("An urgent notification", ["error", "notification"], []),
    "error":                 ("Something went wrong (error dialogs, the terminal bell)", [],
                              ["dialog-error", "bell", "bell-window-system"]),
    "warning":               ("Something needs attention", ["error"], ["dialog-warning"]),
    "device-added":          ("USB device plugged in", [], ["device-added"]),
    "device-removed":        ("USB device unplugged", [], ["device-removed"]),
    "power-plugged":         ("Charger connected", ["device-added"], ["power-plug"]),
    "power-unplugged":       ("Charger disconnected", ["device-removed"], ["power-unplug"]),
    "battery-low":           ("Battery at 15%", ["warning"], ["battery-low", "battery-caution"]),
    "battery-critical":      ("Battery at 5%", ["battery-low", "warning"], []),
    "network-connected":     ("Connected to a network", [], ["network-connectivity-established"]),
    "network-disconnected":  ("Lost the network connection", [], ["network-connectivity-lost"]),
    "window-open":           ("A window opens", [], ["window-new"]),
    "window-close":          ("A window closes", [], ["window-close"]),
    "workspace":             ("You switch desktops (workspaces)", [], []),
    "launcher":              ("App search opens (Super)", [], []),
    "screenshot":            ("A screenshot is taken", [], ["screen-capture", "camera-shutter"]),
    "volume":                ("Volume changes (plays at the new level)", [], ["audio-volume-change"]),
    "service-failed":        ("A background service crashes", ["error"], []),
    "disk-full":             ("Your disk is almost full", ["warning"], []),
}

HOME = os.path.expanduser("~")
USER_CONF = os.path.join(os.environ.get("XDG_CONFIG_HOME", os.path.join(HOME, ".config")),
                         "glassos", "sounds.conf")
SYSTEM_CONF = "/etc/glassos/sounds.conf"
USER_PACKS = os.path.join(os.environ.get("XDG_DATA_HOME", os.path.join(HOME, ".local", "share")),
                          "glassos", "soundpacks")
SYSTEM_PACKS = "/usr/share/glassos/soundpacks"
USER_THEME = os.path.join(os.environ.get("XDG_DATA_HOME", os.path.join(HOME, ".local", "share")),
                          "sounds", "glassos")
BOOT_SOUND_DIR = "/var/lib/glassos/sounds"


def default_pack_name():
    try:
        for line in open("/usr/share/glassos/build-info"):
            if line.startswith("DEFAULT_SOUNDPACK="):
                return line.split("=", 1)[1].strip()
    except OSError:
        pass
    return "glassos-default"


class Settings:
    def __init__(self):
        cp = configparser.ConfigParser()
        cp.read([SYSTEM_CONF, USER_CONF])
        s = cp["sounds"] if cp.has_section("sounds") else {}
        self.pack = s.get("pack", default_pack_name()).strip()
        self.enabled = str(s.get("enabled", "true")).strip().lower() not in ("0", "false", "no", "off")
        try:
            self.volume = max(0.0, min(1.0, float(s.get("volume", "0.8"))))
        except ValueError:
            self.volume = 0.8
        self.mute = {m.strip() for m in str(s.get("mute", "")).split(",") if m.strip()}

    def save(self):
        os.makedirs(os.path.dirname(USER_CONF), exist_ok=True)
        cp = configparser.ConfigParser()
        cp.read(USER_CONF)
        if not cp.has_section("sounds"):
            cp.add_section("sounds")
        cp["sounds"]["pack"] = self.pack
        cp["sounds"]["enabled"] = "true" if self.enabled else "false"
        cp["sounds"]["volume"] = f"{self.volume:.2f}"
        cp["sounds"]["mute"] = ", ".join(sorted(self.mute))
        with open(USER_CONF, "w") as f:
            f.write("# GlassOS sound settings (also editable in Glass Lens -> Sounds)\n")
            cp.write(f)


class Pack:
    def __init__(self, path):
        self.path = path
        self.id = os.path.basename(os.path.normpath(path))
        self.user = path.startswith(USER_PACKS)
        cp = configparser.ConfigParser()
        cp.read(os.path.join(path, "pack.ini"))
        p = cp["pack"] if cp.has_section("pack") else {}
        self.name = p.get("name", self.id)
        self.author = p.get("author", "")
        self.description = p.get("description", "")
        self.inherits = p.get("inherits", "").strip() or None
        # [files] event = file name inside the pack, for sounds that keep their own names
        self.files = {}
        if cp.has_section("files"):
            root = os.path.realpath(path)
            for ev, name in cp["files"].items():
                f = os.path.realpath(os.path.join(path, name.strip()))
                if ev in EVENTS and f.startswith(root + os.sep) and os.path.splitext(f)[1].lower() in EXTS:
                    self.files[ev] = f
        self.volumes = {}
        if cp.has_section("volume"):
            for k, v in cp["volume"].items():
                try:
                    self.volumes[k] = max(0.0, min(1.0, float(v)))
                except ValueError:
                    pass

    def file_for(self, event):
        if event in self.files and os.path.isfile(self.files[event]):
            return self.files[event]
        for ext in EXTS:
            f = os.path.join(self.path, event + ext)
            if os.path.isfile(f):
                return f
        return None

    def events_present(self):
        return [e for e in EVENTS if self.file_for(e)]

    def unknown_files(self):
        known = set(EVENTS)
        mapped = {os.path.basename(f) for f in self.files.values()}
        out = []
        for f in sorted(os.listdir(self.path)):
            stem, ext = os.path.splitext(f)
            if ext.lower() in EXTS and stem not in known and f not in mapped:
                out.append(f)
        return out


def all_packs():
    packs = {}
    for base in (SYSTEM_PACKS, USER_PACKS):  # user packs override system packs with same id
        if os.path.isdir(base):
            for d in sorted(os.listdir(base)):
                full = os.path.join(base, d)
                if os.path.isdir(full):
                    packs[d] = Pack(full)
    return packs


def find_pack(pack_id):
    return all_packs().get(pack_id)


def resolve(event, settings=None, packs=None):
    """Return (file, volume) for an event, or (None, 0) if it should be silent."""
    settings = settings or Settings()
    if not settings.enabled or event in settings.mute:
        return None, 0.0
    packs = packs or all_packs()
    chain = [event] + (EVENTS.get(event, ("", [], []))[1])
    seen = set()
    pack = packs.get(settings.pack) or packs.get(default_pack_name())
    while pack and pack.id not in seen:
        seen.add(pack.id)
        for ev in chain:
            f = pack.file_for(ev)
            if f:
                return f, settings.volume * pack.volumes.get(ev, 1.0)
        pack = packs.get(pack.inherits) if pack.inherits else None
    return None, 0.0


def player_cmd(path, volume):
    if shutil.which("pw-play"):
        return ["pw-play", "--volume", f"{volume:.3f}", path]
    if shutil.which("paplay"):
        return ["paplay", f"--volume={int(volume * 65536)}", path]
    if shutil.which("play"):
        return ["play", "-q", "-v", f"{volume:.3f}", path]
    if shutil.which("aplay") and path.endswith(".wav"):
        return ["aplay", "-q", path]
    return None


def play_file(path, volume=0.8, wait=False):
    cmd = player_cmd(path, volume)
    if not cmd:
        return False
    if wait:
        try:
            subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=15)
        except subprocess.TimeoutExpired:
            pass
    else:
        subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                         start_new_session=True)
    return True


def play(event, wait=False):
    f, vol = resolve(event)
    if f and vol > 0:
        # one line in the system log per sound (journalctl -t glass-sound shows what played and when)
        try:
            syslog.openlog("glass-sound")
            syslog.syslog(syslog.LOG_INFO, f"{event}: {f}")
        except OSError:
            pass
        return play_file(f, vol, wait)
    return False


def build_sound_theme(pack_id=None, target=USER_THEME):
    """Expose the active pack as a freedesktop sound theme called "glassos", so GTK apps
    (and anything using libcanberra) play your sounds for their own events."""
    settings = Settings()
    if pack_id:
        settings.pack = pack_id
    packs = all_packs()
    stereo = os.path.join(target, "stereo")
    if os.path.isdir(stereo):
        shutil.rmtree(stereo)
    os.makedirs(stereo, exist_ok=True)
    with open(os.path.join(target, "index.theme"), "w") as f:
        f.write("[Sound Theme]\nName=GlassOS\nComment=Generated from your active GlassOS sound pack\n"
                "Inherits=freedesktop\nDirectories=stereo\n\n[stereo]\nOutputProfile=stereo\n")
    n = 0
    for event, (_, _, fd_names) in EVENTS.items():
        src, _ = resolve(event, settings, packs)
        if not src:
            continue
        ext = os.path.splitext(src)[1]
        for fd in fd_names:
            os.symlink(src, os.path.join(stereo, fd + ext))
            n += 1
    return n
