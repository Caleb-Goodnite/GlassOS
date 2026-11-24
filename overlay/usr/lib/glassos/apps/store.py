#!/usr/bin/python3
"""Glass App Store: find, install, update and remove apps from Flathub.

  glass-store [--app APP_ID] [--installed] [--search TEXT]

Apps install for your account only (Flatpak's "user" installation, in
~/.local/share/flatpak), so no admin password is needed.

What it talks to, and when: only while it's open. The catalogue, icons and screenshots come
from flathub.org (its public API, v2), and apps download from dl.flathub.org. Nothing runs in
the background, and nothing updates until you press Update.
"""
import concurrent.futures
import hashlib
import html
import html.parser
import json
import os
import shutil
import subprocess
import sys
import urllib.parse
import urllib.request

sys.path.insert(0, "/usr/lib/glassos")
import gi  # noqa: E402

gi.require_version("Gtk", "4.0")
gi.require_version("Gdk", "4.0")
try:
    gi.require_version("Flatpak", "1.0")
    from gi.repository import Flatpak  # noqa: E402
except (ValueError, ImportError):
    Flatpak = None
from gi.repository import Gdk, Gio, GLib, Gtk, Pango  # noqa: E402

import glassui as ui  # noqa: E402
from glassui import hbox, label, vbox  # noqa: E402

APP_ID = "os.glass.Store"
API = "https://flathub.org/api/v2"
REPO_FILE = "/usr/share/glassos/flathub.flatpakrepo"
REPO_URL = "https://dl.flathub.org/repo/flathub.flatpakrepo"
UA = "GlassOS-AppStore/0.1"
PER_PAGE = 30
CACHE = os.path.join(os.environ.get("XDG_CACHE_HOME", os.path.expanduser("~/.cache")), "glassos", "store")
DATA_HOME = os.environ.get("XDG_DATA_HOME", os.path.expanduser("~/.local/share"))
OVERRIDES = os.path.join(DATA_HOME, "flatpak", "overrides")
ARCH = (Flatpak.get_default_arch() if Flatpak else
        {"arm64": "aarch64", "amd64": "x86_64"}.get(os.uname().machine, os.uname().machine))
ARCH_NAME = {"aarch64": "ARM", "x86_64": "Intel and AMD"}.get(ARCH, ARCH)

# Flathub's main categories, in the order people look for them
CATEGORIES = [("office", "Office", "x-office-document-symbolic"),
              ("graphics", "Graphics and photos", "applications-graphics-symbolic"),
              ("audiovideo", "Music and video", "applications-multimedia-symbolic"),
              ("network", "Internet", "network-workgroup-symbolic"),
              ("game", "Games", "applications-games-symbolic"),
              ("development", "Developer tools", "applications-engineering-symbolic"),
              ("education", "Education", "applications-education-symbolic"),
              ("science", "Science", "applications-science-symbolic"),
              ("utility", "Utilities", "applications-utilities-symbolic"),
              ("system", "System", "applications-system-symbolic")]

CSS = """
.app-tile { background: alpha(#ffffff, 0.06); border: 1px solid alpha(#ffffff, 0.09);
            border-top-color: alpha(#ffffff, 0.2); border-radius: 16px; padding: 14px; color: #fff; }
.app-tile:hover { background: alpha(#ffffff, 0.11); }
.app-tile:active { background: alpha(#ffffff, 0.15); }
.app-tile:focus-visible { outline: 2px solid #ffffff; outline-offset: 2px; }
.tile-name { font-weight: 700; }
.verified { color: #7fd4ff; }
.installed-tag { color: #5fe3a1; font-size: 12px; font-weight: 700; }
.detail-name { font-size: 28px; font-weight: 800; }
.shot { border-radius: 12px; }
.section-title { font-weight: 700; font-size: 15px; margin-top: 6px; }
.desc { color: alpha(#ffffff, 0.88); }
.risky { color: #ffd479; }
progressbar trough { min-height: 6px; border-radius: 99px; background: alpha(#ffffff, 0.14); }
progressbar progress { min-height: 6px; border-radius: 99px; background: #ffffff; }
.sidebar-pane .group-head { font-size: 12px; font-weight: 700; color: alpha(#ffffff, 0.85); padding: 14px 22px 4px 22px; }
"""

# data and installs on one pool, pictures on another, so a page never waits behind 30 icons
pool = concurrent.futures.ThreadPoolExecutor(max_workers=4)
img_pool = concurrent.futures.ThreadPoolExecutor(max_workers=6)


# --------------------------------------------------------------------------- background work
def bg(fn, done=None, on=None):
    """Run fn() on a worker thread, then done(result) on the UI thread (result may be an Exception)."""
    def work():
        try:
            res = fn()
        except Exception as e:  # network down, Flathub error, Flatpak error...
            res = e
        if done:
            GLib.idle_add(lambda: (done(res), False)[1])
    (on or pool).submit(work)


def api(path, body=None):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(API + path, data=data, headers={
        "User-Agent": UA, "Accept": "application/json", "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=20) as r:
        return json.load(r)


def cached_file(url):
    """Download url once into ~/.cache/glassos/store and return the local path."""
    ext = os.path.splitext(urllib.parse.urlparse(url).path)[1][:6] or ".img"
    path = os.path.join(CACHE, hashlib.sha1(url.encode()).hexdigest() + ext)
    if os.path.exists(path):
        return path
    os.makedirs(CACHE, exist_ok=True)
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=30) as r, open(path + ".part", "wb") as f:
        shutil.copyfileobj(r, f)
    os.replace(path + ".part", path)
    return path


def load_picture(widget, url):
    """Fill a Gtk.Image or Gtk.Picture from a web image, without blocking the window."""
    if not url:
        return

    def done(res):
        if isinstance(res, Exception):
            return
        try:
            tex = Gdk.Texture.new_from_filename(res)
        except GLib.Error:
            return
        widget.set_paintable(tex) if isinstance(widget, Gtk.Picture) else widget.set_from_paintable(tex)
    bg(lambda: cached_file(url), done, on=img_pool)


def human_bytes(n):
    n = float(n or 0)
    for unit in ("B", "KB", "MB"):
        if n < 1024:
            return f"{n:.0f} {unit}"
        n /= 1024
    return f"{n:.1f} GB"


def supported(hit):
    arches = hit.get("arches")
    return not arches or ARCH in arches


# --------------------------------------------------------------------------- Flatpak
def installation():
    return Flatpak.Installation.new_user(None)


def ensure_flathub(inst):
    if any(r.get_name() == "flathub" for r in inst.list_remotes(None)):
        return
    src = REPO_FILE if os.path.exists(REPO_FILE) else REPO_URL
    r = subprocess.run(["flatpak", "remote-add", "--user", "--if-not-exists", "flathub", src],
                       capture_output=True, text=True, timeout=120)
    if r.returncode != 0:
        raise RuntimeError(r.stderr.strip() or "Couldn't add Flathub.")
    inst.drop_caches(None)


def installed_apps():
    """{app_id: Flatpak.InstalledRef} for apps installed for this user."""
    if not Flatpak:
        return {}
    try:
        return {r.get_name(): r for r in installation().list_installed_refs_by_kind(Flatpak.RefKind.APP, None)}
    except GLib.Error:
        return {}


def installed_runtimes():
    if not Flatpak:
        return set()
    out = set()
    for inst in (installation(), Flatpak.Installation.new_system(None)):
        try:
            for r in inst.list_installed_refs_by_kind(Flatpak.RefKind.RUNTIME, None):
                out.add(f"{r.get_name()}/{r.get_branch()}")
        except GLib.Error:
            pass
    return out


def pending_updates():
    """[(kind, name, full ref)] for everything in the user installation with an update (asks Flathub)."""
    out = []
    for r in installation().list_installed_refs_for_update(None):
        out.append(("app" if r.get_kind() == Flatpak.RefKind.APP else "runtime", r.get_name(), r.format_ref()))
    return out


def run_transaction(kind, app_id, progress, refs=None):
    """kind: install | update | remove (app_id), or update-all (refs = full refs).
    progress(fraction 0..1, status text) is called on the UI thread."""
    inst = installation()
    if kind == "install":
        ensure_flathub(inst)
    t = Flatpak.Transaction.new_for_installation(inst, None)
    state = {"total": 1, "done": 0}
    if kind == "install":
        t.add_install("flathub", f"app/{app_id}/{ARCH}/stable", None)
    elif kind == "update":
        t.add_update(installed_apps()[app_id].format_ref(), None, None)
    elif kind == "update-all":
        for ref in refs:
            t.add_update(ref, None, None)
    else:
        t.add_uninstall(installed_apps()[app_id].format_ref())

    def ready(tr):
        state["total"] = max(1, len(tr.get_operations()))
        return True

    def new_op(_tr, op, prog):
        prog.set_update_frequency(150)
        name = op.get_ref().split("/")[1] if "/" in op.get_ref() else op.get_ref()
        part = "the app" if name == app_id else "shared parts it needs"

        def changed(p):
            frac = (state["done"] + p.get_progress() / 100) / state["total"]
            verb = {"install": "Downloading", "remove": "Removing"}.get(kind, "Updating")
            GLib.idle_add(progress, min(frac, 1.0), f"{verb} {part}…")
        prog.connect("changed", changed)

    def op_done(*_a):
        state["done"] += 1

    t.connect("ready", ready)
    t.connect("new-operation", new_op)
    t.connect("operation-done", op_done)
    # a runtime offered by more than one place: take the first (Flathub is the only one we add)
    t.connect("choose-remote-for-ref", lambda *_a: 0)
    t.run(None)


def plain_error(msg):
    """Flatpak's error text, said the way a person would say it."""
    low = msg.lower()
    if "min-free-space" in low or "no space left" in low:
        return ("There isn't enough free space. Flatpak always leaves 500 MB free so the rest of "
                "the system keeps working. Free up some space and try again.")
    if any(w in low for w in ("resolve", "failed to connect", "network is unreachable", "timeout", "timed out")):
        return "Couldn't reach Flathub. Check that you're connected to the internet, then try again."
    if "already installed" in low:
        return "It's already installed."
    return f"That didn't work: {msg}"


# --------------------------------------------------------------------------- permissions
FOLDERS = {"home": "Everything in your home folder", "host": "All your files, and the system's",
           "host-os": "The system's programs (read only)", "host-etc": "The system's settings files",
           "xdg-download": "Your Downloads folder", "xdg-documents": "Your Documents folder",
           "xdg-music": "Your Music folder", "xdg-pictures": "Your Pictures folder",
           "xdg-videos": "Your Videos folder", "xdg-desktop": "Your Desktop folder"}


def permissions(meta):
    """Plain-language list of what an app asks to reach:
    [(icon, text, control or None, risky)] where control = (section, value) for an on/off switch."""
    p = (meta or {}).get("permissions") or {}
    shared, sockets = p.get("shared") or [], p.get("sockets") or []
    devices, files = p.get("devices") or [], p.get("filesystems") or []
    talk = ((p.get("session-bus") or {}).get("talk") or []) + ((p.get("session-bus") or {}).get("own") or [])
    out = []
    if "network" in shared:
        out.append(("network-wireless-symbolic", "The internet", ("shared", "network"), False))
    if "pulseaudio" in sockets:
        out.append(("audio-speakers-symbolic", "Speakers and microphone", ("sockets", "pulseaudio"), False))
    if "all" in devices:
        out.append(("camera-web-symbolic", "All devices, including cameras and game controllers",
                    ("devices", "all"), False))
    elif "input" in devices:
        out.append(("input-gaming-symbolic", "Game controllers", ("devices", "input"), False))
    seen = set()
    for f in files:
        base, _, mode = f.partition(":")
        base = base.rstrip("/")
        if base in FOLDERS and base not in seen:
            seen.add(base)
            text = FOLDERS[base] + (" (read only)" if mode == "ro" and base not in ("host-os",) else "")
            control = ("filesystems", base) if base in ("home", "host") else None
            out.append(("folder-symbolic", text, control, base in ("home", "host")))
    if "x11" in sockets and "wayland" not in sockets:
        out.append(("video-display-symbolic", "Uses the older X11 display system, which lets it see other "
                    "X11 apps' windows and keystrokes", None, True))
    if "ssh-auth" in sockets:
        out.append(("dialog-password-symbolic", "Your SSH keys", None, True))
    if "cups" in sockets:
        out.append(("printer-symbolic", "Printers", None, False))
    if any(n.startswith("org.freedesktop.secrets") for n in talk):
        out.append(("dialog-password-symbolic", "Your saved passwords (the keyring)", None, True))
    if any(n.startswith("org.freedesktop.Flatpak") for n in talk) or "session-bus" in sockets \
            or "system-bus" in sockets:
        out.append(("dialog-warning-symbolic", "Can run programs outside its sandbox, so it can reach "
                    "anything your account can", None, True))
    return out


def overrides_path(app_id):
    return os.path.join(OVERRIDES, app_id)


def blocked(app_id, section, value):
    kf = GLib.KeyFile()
    try:
        kf.load_from_file(overrides_path(app_id), GLib.KeyFileFlags.KEEP_COMMENTS)
        return "!" + value in kf.get_string_list("Context", section)
    except GLib.Error:
        return False


def set_blocked(app_id, section, value, block):
    """Write Flatpak's own override file (the same one `flatpak override --user` writes):
    "!network" in [Context] shared= means the app no longer gets the network, and so on."""
    kf = GLib.KeyFile()
    p = overrides_path(app_id)
    try:
        kf.load_from_file(p, GLib.KeyFileFlags.KEEP_COMMENTS)
    except GLib.Error:
        pass
    try:
        items = kf.get_string_list("Context", section)
    except GLib.Error:
        items = []
    items = [x for x in items if x.split(":")[0] not in (value, "!" + value)]
    if block:
        items.append("!" + value)
    if items:
        kf.set_string_list("Context", section, items)
    else:
        try:
            kf.remove_key("Context", section)
        except GLib.Error:
            pass
    os.makedirs(OVERRIDES, exist_ok=True)
    kf.save_to_file(p)


# --------------------------------------------------------------------------- description text
class Blocks(html.parser.HTMLParser):
    """AppStream descriptions are a small subset of HTML (p, ul/ol, li, em, code).
    Turns them into [("p"|"li", pango_markup)]."""

    def __init__(self):
        super().__init__()
        self.blocks, self.cur, self.kind = [], [], "p"

    def flush(self):
        text = " ".join("".join(self.cur).split())
        if text:
            self.blocks.append((self.kind, text))
        self.cur = []

    def handle_starttag(self, tag, _attrs):
        if tag in ("p", "li"):
            self.flush()
            self.kind = tag
        elif tag == "em":
            self.cur.append("<i>")
        elif tag == "code":
            self.cur.append("<tt>")

    def handle_endtag(self, tag):
        if tag in ("p", "li"):
            self.flush()
            self.kind = "p"
        elif tag == "em":
            self.cur.append("</i>")
        elif tag == "code":
            self.cur.append("</tt>")

    def handle_data(self, data):
        self.cur.append(GLib.markup_escape_text(data))


def description_widgets(text):
    box = vbox(8)
    p = Blocks()
    try:
        p.feed(text or "")
        p.close()
        p.flush()
    except Exception:
        p.blocks = [("p", GLib.markup_escape_text(html.unescape(text or "")))]
    for kind, markup in p.blocks[:40]:
        lb = label(("•  " if kind == "li" else "") + markup, "desc", wrap=True, markup=True)
        if kind == "li":
            lb.set_margin_start(12)
        box.append(lb)
    return box


# --------------------------------------------------------------------------- widgets
def state_box(kind, text, retry=None):
    """Loading / empty / error states, the same everywhere in the store."""
    b = vbox(12)
    b.set_halign(Gtk.Align.CENTER)
    b.set_margin_top(60)
    if kind == "loading":
        sp = Gtk.Spinner()
        sp.set_size_request(28, 28)
        sp.start()
        b.append(sp)
    else:
        icon = Gtk.Image.new_from_icon_name("network-offline-symbolic" if kind == "error" else "system-search-symbolic")
        icon.set_pixel_size(40)
        b.append(icon)
    lb = label(text, "dim", xalign=0.5, wrap=True)
    lb.set_max_width_chars(48)
    b.append(lb)
    if retry:
        btn = ui.button("Try again", retry)
        btn.set_halign(Gtk.Align.CENTER)
        b.append(btn)
    return b


def app_icon(url, size, app_id=None):
    img = Gtk.Image()
    img.set_pixel_size(size)
    if app_id and Gtk.IconTheme.get_for_display(Gdk.Display.get_default()).has_icon(app_id):
        img.set_from_icon_name(app_id)
    else:
        img.set_from_icon_name("application-x-executable")
        load_picture(img, url)
    return img


class Tile(Gtk.Button):
    def __init__(self, hit, win, installed):
        super().__init__()
        self.add_css_class("app-tile")
        self.set_size_request(290, -1)
        row = hbox(14)
        row.append(app_icon(hit.get("icon"), 56))
        t = vbox(3)
        t.set_hexpand(True)
        t.set_valign(Gtk.Align.CENTER)
        # FlowBox sizes children by their natural width; capping each label lets tiles sit
        # side by side instead of one long tile per row
        name = label(hit.get("name") or hit["app_id"], "tile-name", ellipsize=True)
        name.set_max_width_chars(18)
        t.append(name)
        s = label(hit.get("summary") or "", "dim small", wrap=True)
        s.set_lines(2)
        s.set_ellipsize(Pango.EllipsizeMode.END)
        s.set_max_width_chars(24)
        t.append(s)
        meta = hbox(6)
        if hit["app_id"] in installed:
            meta.append(label("Installed", "installed-tag"))
        elif hit.get("verification_verified"):
            v = Gtk.Image.new_from_icon_name("emblem-ok-symbolic")
            v.add_css_class("verified")
            v.set_tooltip_text("Verified: published by the people who make it")
            meta.append(v)
            dev = label(hit.get("developer_name") or "Verified", "dim small", ellipsize=True)
            dev.set_max_width_chars(20)
            meta.append(dev)
        elif hit.get("developer_name"):
            dev = label(hit["developer_name"], "dim small", ellipsize=True)
            dev.set_max_width_chars(20)
            meta.append(dev)
        t.append(meta)
        row.append(t)
        self.set_child(row)
        self.update_property([Gtk.AccessibleProperty.LABEL], [f"{hit.get('name')}: {hit.get('summary') or ''}"])
        self.connect("clicked", lambda *_: win.show_app(hit["app_id"], hit))
        self.set_cursor_from_name("pointer")


# --------------------------------------------------------------------------- pages
class Scroller(Gtk.ScrolledWindow):
    def __init__(self):
        super().__init__()
        self.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
        self.body = vbox(16, "page")
        self.set_child(self.body)


class BrowsePage(Scroller):
    """Popular apps, a category, or search results: a grid of tiles with paging."""

    def __init__(self, win):
        super().__init__()
        self.win = win
        self.title = label("", "page-title")
        self.sub = label("", "page-sub", wrap=True)
        self.body.append(self.title)
        self.body.append(self.sub)
        self.state = vbox(0)
        self.body.append(self.state)
        self.grid = Gtk.FlowBox(selection_mode=Gtk.SelectionMode.NONE, homogeneous=True,
                                min_children_per_line=1, max_children_per_line=3,
                                column_spacing=14, row_spacing=14)
        self.body.append(self.grid)
        self.more = ui.button("Show more apps", self.load_more)
        self.more.set_halign(Gtk.Align.CENTER)
        self.body.append(self.more)
        self.token = 0

    def show(self, title, sub, fetch):
        """fetch(page) -> Flathub result dict with "hits" and "totalPages"."""
        self.token += 1
        self.title.set_text(title)
        self.sub.set_text(sub or "")
        self.sub.set_visible(bool(sub))
        self.fetch, self.page = fetch, 1
        ui.clear(self.grid)
        self.more.set_visible(False)
        self.get_vadjustment().set_value(0)
        self.load()

    def load(self):
        token = self.token
        ui.clear(self.state)
        self.state.append(state_box("loading", "Loading apps from Flathub…"))
        self.more.set_sensitive(False)

        def done(res):
            if token != self.token:
                return
            ui.clear(self.state)
            self.more.set_sensitive(True)
            if isinstance(res, Exception):
                if self.page == 1:
                    self.state.append(state_box("error", "Couldn't reach Flathub. Check that you're connected "
                                                "to the internet.", self.load))
                else:
                    self.more.set_label("Couldn't load more. Try again")
                return
            data, installed = res
            hits = [h for h in data.get("hits", []) if supported(h)]
            if self.page == 1 and not hits:
                self.state.append(state_box("empty", "No apps found."))
            for h in hits:
                self.grid.append(Tile(h, self.win, installed))
            self.more.set_label("Show more apps")
            self.more.set_visible(self.page < (data.get("totalPages") or 1))

        page = self.page
        bg(lambda: (self.fetch(page), installed_apps()), done)

    def load_more(self):
        self.page += 1
        self.load()


class DetailPage(Scroller):
    def __init__(self, win):
        super().__init__()
        self.win = win
        self.token = 0
        self.busy = False

    def show(self, app_id, hit=None):
        self.token += 1
        token = self.token
        self.app_id, self.hit = app_id, hit or {}
        ui.clear(self.body)
        self.body.append(state_box("loading", "Loading…"))
        self.get_vadjustment().set_value(0)

        def fetch():
            q = urllib.parse.quote(app_id)
            out = {}
            with concurrent.futures.ThreadPoolExecutor(max_workers=3) as ex:
                futs = {k: ex.submit(api, path) for k, path in (
                    ("appstream", f"/appstream/{q}"), ("summary", f"/summary/{q}"),
                    ("verified", f"/verification/{q}/status"))}
                for k, f in futs.items():
                    try:
                        out[k] = f.result(timeout=40)
                    except Exception:
                        if k == "appstream":   # without this there's no page to show
                            raise
                        out[k] = {}
            out["runtimes"] = installed_runtimes()
            out["installed"] = installed_apps()
            return out

        def done(res):
            if token != self.token:
                return
            ui.clear(self.body)
            if isinstance(res, Exception):
                self.body.append(state_box("error", "Couldn't load this app's page from Flathub. Check that "
                                           "you're connected to the internet.", lambda: self.show(app_id, hit)))
                return
            self.build(res)

        bg(fetch, done)

    def build(self, d):
        a, s, v = d["appstream"] or {}, d["summary"] or {}, d["verified"] or {}
        self.data = d
        self.name = a.get("name") or self.app_id
        installed = self.app_id in d["installed"]
        arches = s.get("arches") or self.hit.get("arches")
        runs_here = not arches or ARCH in arches

        head = hbox(18)
        head.append(app_icon(a.get("icon") or self.hit.get("icon"), 96, self.app_id if installed else None))
        t = vbox(4)
        t.set_hexpand(True)
        t.set_valign(Gtk.Align.CENTER)
        t.append(label(self.name, "detail-name", wrap=True))
        dev = hbox(6)
        if v.get("verified"):
            ic = Gtk.Image.new_from_icon_name("emblem-ok-symbolic")
            ic.add_css_class("verified")
            dev.append(ic)
            who = a.get("developer_name") or v.get("website") or "the developer"
            dev.append(label(f"{who} · Verified", "dim small", wrap=True))
            dev.set_tooltip_text("Flathub has checked that this app is published by the people who make it"
                                 + (f" ({v['website']})" if v.get("website") else "") + ".")
        elif a.get("developer_name"):
            dev.append(label(f"{a['developer_name']} · Not verified", "dim small", wrap=True))
            dev.set_tooltip_text("Published on Flathub, but not confirmed to come from the people who make it.")
        t.append(dev)
        if a.get("summary"):
            t.append(label(a["summary"], "dim", wrap=True))
        head.append(t)

        # action area: buttons, or a progress bar while working
        self.actions = vbox(8)
        self.actions.set_valign(Gtk.Align.CENTER)
        head.append(self.actions)
        self.body.append(head)
        self.fill_actions(installed, runs_here)

        facts = []
        rel = (a.get("releases") or [{}])[0]
        if rel.get("version"):
            facts.append(f"Version {rel['version']}")
        if s.get("download_size"):
            facts.append(f"{human_bytes(s['download_size'])} download")
        if s.get("installed_size"):
            facts.append(f"{human_bytes(s['installed_size'])} on disk")
        facts.append("Free and open source" if a.get("is_free_license") else "Proprietary")
        self.body.append(label("  ·  ".join(facts), "dim small", wrap=True))
        meta = s.get("metadata") or {}
        rt = meta.get("runtime") or ""
        if rt and not installed:
            parts = rt.split("/")
            if len(parts) == 3 and f"{parts[0]}/{parts[2]}" not in d["runtimes"]:
                extra = f" ({human_bytes(meta['runtimeInstalledSize'])} on disk)" if meta.get("runtimeInstalledSize") else ""
                self.body.append(label(f"The first install also downloads {meta.get('runtimeName') or parts[0]}"
                                       f"{extra}, which other apps share.", "dim small", wrap=True))
        if a.get("is_eol"):
            self.body.append(label("Its developer has stopped updating this app.", "warn small", wrap=True))
        if not runs_here:
            self.body.append(label(f"This app isn't made for this computer's processor ({ARCH_NAME}), so it "
                                   "can't be installed here.", "warn", wrap=True))

        shots = [sc for sc in (a.get("screenshots") or []) if sc.get("sizes")][:6]
        if shots:
            row = hbox(12)
            for sc in shots:
                sizes = sorted(sc["sizes"], key=lambda z: abs(int(z.get("width") or 0) - 752))
                best = sizes[0]
                w, h = int(best.get("width") or 752), int(best.get("height") or 423)
                pic = Gtk.Picture()
                pic.set_content_fit(Gtk.ContentFit.CONTAIN)
                pic.add_css_class("shot")
                pic.set_size_request(int(260 * w / max(h, 1)), 260)
                pic.set_can_shrink(True)
                if sc.get("caption"):
                    pic.set_alternative_text(sc["caption"])
                load_picture(pic, best.get("src"))
                row.append(pic)
            sw = Gtk.ScrolledWindow()
            sw.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.NEVER)
            sw.set_min_content_height(270)
            sw.set_child(row)
            self.body.append(sw)

        if a.get("description"):
            self.body.append(description_widgets(a["description"]))

        self.perm_card = None
        self.build_permissions(meta, installed)

        links = [(k, t) for k, t in (("homepage", "Website"), ("help", "Help"), ("bugtracker", "Report a problem"),
                                     ("donation", "Donate")) if (a.get("urls") or {}).get(k)]
        lrow = hbox(8)
        for k, text in links:
            lrow.append(ui.button(text, lambda u=a["urls"][k]: self.open_url(u)))
        lrow.append(ui.button("See it on flathub.org",
                              lambda: self.open_url(f"https://flathub.org/apps/{self.app_id}")))
        self.body.append(lrow)

    def build_permissions(self, meta, installed):
        perms = permissions(meta)
        sub = ("Apps from the App Store run in a sandbox. This is everything beyond its own window and files "
               "that this one asks for.")
        if installed and any(c for _, _, c, _ in perms):
            sub += " Switch any of these off; it takes effect the next time you open the app."
        c = ui.card("What it can reach", sub)
        if not perms:
            c.append(label("Nothing beyond its own window and its own files. It can still open a file you "
                           "pick for it.", "dim small", wrap=True))
        for icon, text, control, risky in perms:
            r = hbox(12, "row")
            im = Gtk.Image.new_from_icon_name(icon)
            r.append(im)
            lb = label(text, "risky" if risky else None, wrap=True)
            lb.set_hexpand(True)
            r.append(lb)
            if installed and control:
                sw = Gtk.Switch()
                sw.set_active(not blocked(self.app_id, *control))
                sw.set_valign(Gtk.Align.CENTER)
                sw.update_property([Gtk.AccessibleProperty.LABEL], [f"Allow: {text}"])
                sw.connect("notify::active", lambda w, _p, ctl=control: set_blocked(self.app_id, *ctl,
                                                                                      not w.get_active()))
                r.append(sw)
            c.append(r)
        self.body.append(c)

    def fill_actions(self, installed, runs_here=True):
        ui.clear(self.actions)
        if self.busy:
            return
        if installed:
            row = hbox(8)
            row.append(ui.button("Open", self.launch, "pill accent"))
            row.append(ui.button("Remove…", self.ask_remove))
            self.actions.append(row)
        else:
            b = ui.button("Install", lambda: self.start("install"), "pill accent")
            b.set_sensitive(bool(Flatpak) and runs_here)
            if not Flatpak:
                b.set_tooltip_text("Flatpak isn't installed on this computer.")
            self.actions.append(b)

    def ask_remove(self):
        ui.clear(self.actions)
        self.actions.append(label(f"Remove {self.name}?", "card-title"))
        keep = Gtk.CheckButton(label="Also delete its settings and saved data")
        self.actions.append(keep)
        row = hbox(8)
        row.append(ui.button("Cancel", lambda: self.fill_actions(True)))
        row.append(ui.button("Remove", lambda: self.start("remove", delete_data=keep.get_active()), "pill accent"))
        self.actions.append(row)

    def start(self, kind, delete_data=False):
        self.busy = True
        ui.clear(self.actions)
        bar = Gtk.ProgressBar()
        bar.set_size_request(200, -1)
        status = label({"install": "Starting download…", "remove": "Removing…", "update": "Updating…"}[kind],
                       "dim small")
        self.actions.append(bar)
        self.actions.append(status)
        pulse = GLib.timeout_add(120, lambda: (bar.pulse(), bar.get_fraction() == 0)[1])

        def progress(frac, text):
            nonlocal pulse
            if frac > 0 and pulse:
                GLib.source_remove(pulse)
                pulse = 0
            if frac > 0:
                bar.set_fraction(frac)
            status.set_text(text)
            return False

        app_id, token = self.app_id, self.token

        def work():
            run_transaction(kind, app_id, progress)
            if kind == "remove" and delete_data:
                shutil.rmtree(os.path.expanduser(f"~/.var/app/{app_id}"), ignore_errors=True)
                try:
                    os.remove(overrides_path(app_id))
                except OSError:
                    pass

        def done(res):
            if pulse:
                GLib.source_remove(pulse)
            self.busy = False
            self.win.refresh_installed()
            if token != self.token:
                return
            if isinstance(res, Exception):
                msg = res.message if isinstance(res, GLib.Error) else str(res)
                self.fill_actions(kind == "remove" or kind == "update")
                note = label(plain_error(msg), "warn small", wrap=True)
                note.set_tooltip_text(msg)   # Flatpak's own words, for anyone reporting a problem
                self.actions.append(note)
                return
            self.show(app_id, self.hit)

        bg(work, done)

    def launch(self):
        subprocess.Popen(["flatpak", "run", self.app_id], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                         start_new_session=True)

    def open_url(self, url):
        if url.startswith("https://") or url.startswith("http://"):
            subprocess.Popen(["xdg-open", url], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                             start_new_session=True)


class InstalledPage(Scroller):
    def __init__(self, win):
        super().__init__()
        self.win = win
        self.body.append(label("Installed", "page-title"))
        self.body.append(label("Apps from the App Store, installed for your account. Nothing updates until "
                               "you press Update.", "page-sub", wrap=True))
        bar = hbox(10)
        self.check = ui.button("Check for updates", self.check_updates)
        bar.append(self.check)
        self.update_all = ui.button("Update all", self.do_update_all, "pill accent")
        self.update_all.set_visible(False)
        bar.append(self.update_all)
        self.note = label("", "dim small", wrap=True)
        self.note.set_valign(Gtk.Align.CENTER)
        bar.append(self.note)
        self.body.append(bar)
        self.list = vbox(0)
        self.body.append(self.list)
        self.updates = set()

    def refresh(self):
        apps = installed_apps()
        ui.clear(self.list)
        if not Flatpak:
            self.list.append(state_box("error", "Flatpak isn't installed, so the App Store can't install apps."))
            return
        if not apps:
            b = state_box("empty", "Nothing installed from the App Store yet.")
            go = ui.button("See popular apps", lambda: self.win.select("home"))
            go.set_halign(Gtk.Align.CENTER)
            b.append(go)
            self.list.append(b)
            return
        for app_id, ref in sorted(apps.items(), key=lambda kv: (kv[1].get_appdata_name() or kv[0]).lower()):
            r = hbox(12, "row")
            r.append(app_icon(None, 40, app_id))
            t = vbox(2)
            t.set_hexpand(True)
            t.append(label(ref.get_appdata_name() or app_id, "tile-name"))
            bits = [b for b in (ref.get_appdata_version() and f"Version {ref.get_appdata_version()}",
                                human_bytes(ref.get_installed_size()) + " on disk") if b]
            if app_id in self.updates:
                bits.append("Update available")
            t.append(label("  ·  ".join(bits), "dim small"))
            r.append(t)
            buttons = []
            if app_id in self.updates:
                buttons.append(ui.button("Update", lambda a=app_id: self.update_one(a), "pill accent"))
            buttons.append(ui.button("Open", lambda a=app_id: subprocess.Popen(
                ["flatpak", "run", a], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)))
            buttons.append(ui.button("Details", lambda a=app_id: self.win.show_app(a)))
            for b in buttons:
                b.set_valign(Gtk.Align.CENTER)
                r.append(b)
            self.list.append(r)

    def check_updates(self):
        self.check.set_sensitive(False)
        self.note.set_text("Asking Flathub for updates…")

        def done(res):
            self.check.set_sensitive(True)
            if isinstance(res, Exception):
                self.note.set_text("Couldn't reach Flathub. Check that you're connected to the internet.")
                return
            self.pending = res
            self.updates = {name for kind, name, _ref in res if kind == "app"}
            shared = len(res) - len(self.updates)
            if not res:
                self.note.set_text("Everything is up to date.")
            else:
                parts = []
                if self.updates:
                    parts.append(f"{len(self.updates)} app{'s' if len(self.updates) != 1 else ''}")
                if shared:
                    parts.append(f"{shared} shared part{'s' if shared != 1 else ''} apps use")
                self.note.set_text("Updates for " + " and ".join(parts) + ".")
            self.update_all.set_visible(bool(res))
            self.refresh()

        bg(pending_updates, done)

    def update_one(self, app_id):
        self.note.set_text(f"Updating {app_id}…")
        self.check.set_sensitive(False)
        self.update_all.set_sensitive(False)

        def done(res):
            self.check.set_sensitive(True)
            self.update_all.set_sensitive(True)
            if isinstance(res, Exception):
                msg = res.message if isinstance(res, GLib.Error) else str(res)
                self.note.set_text(f"Updating {app_id} didn't work: {msg}")
                return
            self.updates.discard(app_id)
            self.pending = [p for p in getattr(self, "pending", []) if p[1] != app_id]
            self.update_all.set_visible(bool(self.pending))
            self.note.set_text(f"{len(self.pending)} left to update." if self.pending else "Everything is up to date.")
            self.refresh()

        bg(lambda: run_transaction("update", app_id, lambda *_a: False), done)

    def do_update_all(self):
        refs = [ref for _k, _n, ref in getattr(self, "pending", [])]
        if not refs:
            return
        self.check.set_sensitive(False)
        self.update_all.set_sensitive(False)

        def progress(frac, text):
            self.note.set_text(f"{text} {frac * 100:.0f}%")
            return False

        def done(res):
            self.check.set_sensitive(True)
            self.update_all.set_sensitive(True)
            if isinstance(res, Exception):
                msg = res.message if isinstance(res, GLib.Error) else str(res)
                self.note.set_text(f"Updating didn't finish: {msg}")
                return
            self.pending, self.updates = [], set()
            self.update_all.set_visible(False)
            self.note.set_text("Everything is up to date.")
            self.refresh()

        bg(lambda: run_transaction("update-all", None, progress, refs), done)


# --------------------------------------------------------------------------- window
class StoreWindow(Gtk.ApplicationWindow):
    def __init__(self, app):
        super().__init__(application=app, title="App Store")
        self.add_css_class("glass")
        ui.fit_size(self, 1080, 740)
        hb = Gtk.HeaderBar()
        self.back = Gtk.Button.new_from_icon_name("go-previous-symbolic")
        self.back.add_css_class("round")
        self.back.set_tooltip_text("Back (Esc)")
        self.back.update_property([Gtk.AccessibleProperty.LABEL], ["Back"])
        self.back.connect("clicked", lambda *_: self.go_back())
        self.back.set_visible(False)
        hb.pack_start(self.back)
        self.search = Gtk.SearchEntry(placeholder_text="Search apps")
        self.search.set_size_request(320, -1)
        self.search.connect("search-changed", self.on_search)
        self.search.connect("activate", self.on_search)
        hb.set_title_widget(self.search)
        self.set_titlebar(hb)
        ui.drag_by_titlebar(self, hb)

        root = hbox(0)
        side = vbox(0, "sidebar-pane")
        side.set_size_request(210, -1)
        self.side = Gtk.ListBox()
        self.side.set_selection_mode(Gtk.SelectionMode.SINGLE)
        self.rows = {}
        entries = [("home", "Popular", "starred-symbolic")] + list(CATEGORIES) + \
                  [("installed", "Installed", "folder-download-symbolic")]
        for key, text, icon in entries:
            r = Gtk.ListBoxRow()
            b = hbox(10)
            b.append(Gtk.Image.new_from_icon_name(icon))
            b.append(label(text))
            r.set_child(b)
            r.key = key
            self.rows[key] = r
            self.side.append(r)
        self.side.set_header_func(self.headers)
        self.side.connect("row-selected", lambda _l, r: r and self.open_section(r.key))
        sc = Gtk.ScrolledWindow()
        sc.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        sc.set_vexpand(True)
        sc.set_child(self.side)
        side.append(sc)
        foot = label("Apps come from Flathub (flathub.org).", "dim small", wrap=True)
        foot.set_margin_start(22)
        foot.set_margin_end(16)
        foot.set_margin_bottom(14)
        side.append(foot)
        root.append(side)

        self.stack = Gtk.Stack()
        self.stack.set_transition_type(Gtk.StackTransitionType.CROSSFADE)
        self.stack.set_hexpand(True)
        self.browse = BrowsePage(self)
        self.detail = DetailPage(self)
        self.installed = InstalledPage(self)
        self.stack.add_named(self.browse, "browse")
        self.stack.add_named(self.detail, "detail")
        self.stack.add_named(self.installed, "installed")
        root.append(self.stack)
        self.set_child(root)
        self.prev = "browse"
        self._search_id = 0
        self._section = "home"     # sidebar page to return to when a search is cleared
        self._quiet = False        # set while the search box is cleared from code

        keys = Gtk.EventControllerKey()
        keys.connect("key-pressed", self.on_key)
        self.add_controller(keys)

    @staticmethod
    def headers(row, before):
        if row.key == CATEGORIES[0][0] or row.key == "installed":
            h = label("Categories" if row.key != "installed" else "Your apps", "group-head")
            row.set_header(h)
        else:
            row.set_header(None)

    def select(self, key):
        self.side.select_row(self.rows[key])

    def open_section(self, key):
        self._section = key
        if self.search.get_text():
            # picking a sidebar page ends the search
            self._quiet = True
            self.search.set_text("")
            self._quiet = False
        self.back.set_visible(False)
        if key == "installed":
            self.stack.set_visible_child_name("installed")
            self.installed.refresh()
            return
        self.stack.set_visible_child_name("browse")
        if key == "home":
            self.browse.show("Popular apps", "The apps people install most from Flathub this month.",
                             lambda p: api(f"/collection/popular?page={p}&per_page={PER_PAGE}"))
        else:
            name = dict((k, n) for k, n, _ in CATEGORIES)[key]
            self.browse.show(name, None, lambda p, k=key: api(f"/collection/category/{k}?page={p}&per_page={PER_PAGE}"))

    def on_search(self, *_):
        if self._quiet:
            return
        if self._search_id:
            GLib.source_remove(self._search_id)
        self._search_id = GLib.timeout_add(300, self.run_search)

    def run_search(self):
        self._search_id = 0
        q = self.search.get_text().strip()
        if not q:
            row = self.rows[self._section]
            if self.side.get_selected_row() is row:
                self.open_section(self._section)
            else:
                self.side.select_row(row)
            return False
        self.side.unselect_all()   # results aren't one of the sidebar pages
        self.back.set_visible(False)
        self.stack.set_visible_child_name("browse")
        body = {"query": q, "filters": [{"filterType": "arches", "value": ARCH}]}
        self.browse.show(f"Results for “{q}”", None,
                         lambda p: api("/search", dict(body, page=p, hits_per_page=PER_PAGE)))
        return False

    def show_app(self, app_id, hit=None):
        cur = self.stack.get_visible_child_name()
        if cur != "detail":
            self.prev = cur
        self.back.set_visible(True)
        self.stack.set_visible_child_name("detail")
        self.detail.show(app_id, hit)

    def go_back(self):
        if self.stack.get_visible_child_name() != "detail":
            return False
        self.back.set_visible(False)
        self.stack.set_visible_child_name(self.prev)
        if self.prev == "installed":
            self.installed.refresh()
        return True

    def refresh_installed(self):
        if self.stack.get_visible_child_name() == "installed":
            self.installed.refresh()

    def on_key(self, _c, keyval, _code, state):
        if keyval == Gdk.KEY_Escape:
            return self.go_back()
        if keyval == Gdk.KEY_Left and state & Gdk.ModifierType.ALT_MASK:
            return self.go_back()
        if keyval == Gdk.KEY_f and state & Gdk.ModifierType.CONTROL_MASK:
            self.search.grab_focus()
            return True
        return False


class StoreApp(Gtk.Application):
    def __init__(self):
        super().__init__(application_id=APP_ID, flags=Gio.ApplicationFlags.HANDLES_COMMAND_LINE)
        self.win = None

    def do_command_line(self, cmdline):
        args = cmdline.get_arguments()[1:]

        def arg(name):
            return args[args.index(name) + 1] if name in args and args.index(name) + 1 < len(args) else None

        if self.win is None:
            ui.apply_css(CSS)
            self.win = StoreWindow(self)
            self.win.select("installed" if "--installed" in args else "home")
        if arg("--search"):
            self.win.search.set_text(arg("--search"))
        self.win.present()
        if arg("--app"):
            # after the window is up, so the sidebar's first selection can't replace the page
            app_id = arg("--app")
            GLib.idle_add(lambda: self.win.show_app(app_id) and False)
        return 0


if __name__ == "__main__":
    GLib.set_prgname(APP_ID)
    sys.exit(StoreApp().run(sys.argv))
