#!/usr/bin/python3
"""Disk Utility - see and change the disks and partitions on this computer.

Each disk shows as a bar of its partitions and free space. Pick a part of the bar to mount it,
format it, resize it or delete it, or to make a new partition in free space (to make room for
another operating system, for example). Changes run through /usr/lib/glassos/glass-disk as root,
after polkit asks for an administrator's password. Reading the disks needs no password: lsblk
gets everything from /sys.
"""
import json
import math
import shutil
import subprocess
import sys

sys.path.insert(0, "/usr/lib/glassos")
import glassui as ui  # noqa: E402
from gi.repository import Gdk, Gio, GLib, Gtk  # noqa: E402

APP_ID = "os.glass.Disks"
HELPER = "/usr/lib/glassos/glass-disk"
MIB = 1024 * 1024
MIN_FREE = 16 * MIB          # smaller gaps are alignment slack, not usable free space
SYSTEM_MOUNTS = ("/", "/boot", "/boot/efi", "/usr", "/var", "/home", "[SWAP]", "/run/live/medium")

# colour, plain name
KINDS = {
    "linux": ("#5fb3a1", "Linux"),
    "windows": ("#7b93f0", "Windows"),
    "efi": ("#e0a85a", "Startup files (EFI)"),
    "fat": ("#e0c35a", "FAT"),
    "exfat": ("#d987b8", "exFAT"),
    "swap": ("#a98be8", "Swap"),
    "locked": ("#c9787b", "Encrypted"),
    "empty": ("#8a8fa3", "Not formatted"),
    "other": ("#8a8fa3", "Other"),
}
LINUX_FS = {"ext4", "ext3", "ext2", "btrfs", "xfs", "f2fs"}

# format choices: key, label, longest name the format allows
FORMATS = [
    ("ext4", "Linux (ext4)", 16),
    ("exfat", "exFAT: for USB sticks shared with Windows and Macs", 15),
    ("fat32", "FAT32: works almost everywhere, files up to 4 GB", 11),
    ("ntfs", "NTFS: Windows", 32),
    ("none", "Leave empty, for another system's installer", 36),
]

CSS = """
.disk-map { margin: 4px 0 2px 0; }
.seg-row { padding: 9px 6px; border-radius: 11px; }
.big-num { font-size: 15px; font-weight: 700; font-feature-settings: "tnum"; }
.status { color: alpha(#ffffff, 0.86); font-size: 13px; }
.note { color: alpha(#ffffff, 0.86); font-size: 13px; }
button.danger { background: alpha(#e5484d, 0.78); color: #fff; border-color: alpha(#ffffff, 0.25); }
button.danger:hover { background: alpha(#f05a5f, 0.9); }
list.segs { background: transparent; }
list.segs row { border-radius: 11px; margin: 1px 0; }
list.segs row:selected { background: alpha(#ffffff, 0.13); }
"""


def size_text(b):
    """Decimal units, like the label on the box the disk came in."""
    for unit, n in (("TB", 1e12), ("GB", 1e9), ("MB", 1e6), ("KB", 1e3)):
        if b >= n:
            v = b / n
            return f"{v:.1f} {unit}" if v < 100 else f"{v:.0f} {unit}"
    return f"{b} bytes"


def as_admin(*argv):
    if shutil.which("pkexec"):
        return ["pkexec", *argv]
    return ["sudo", "-n", *argv]


def read_disks():
    cols = "NAME,PATH,TYPE,SIZE,START,FSTYPE,LABEL,PARTLABEL,MOUNTPOINTS,MODEL,TRAN,RM,PTTYPE,FSUSED,PARTTYPENAME"
    out = subprocess.run(["lsblk", "-J", "-b", "-o", cols], capture_output=True, text=True).stdout
    disks = []
    for d in json.loads(out or '{"blockdevices": []}')["blockdevices"]:
        if d["type"] != "disk" or not d.get("size") or d["name"].startswith(("zram", "loop", "ram")):
            continue
        disks.append(d)
    return disks, out


def mounts(dev):
    """Every mount point of a device and of what sits on it (an unlocked encrypted volume, say)."""
    found = [m for m in (dev.get("mountpoints") or []) if m]
    for c in dev.get("children") or []:
        found += mounts(c)
    return found


def kind_of(p):
    fs = p.get("fstype") or ""
    ptype = (p.get("parttypename") or "").lower()
    if fs == "vfat" and "efi" in ptype:
        return "efi"
    if fs in LINUX_FS:
        return "linux"
    if fs == "ntfs" or fs == "BitLocker" or "microsoft" in ptype or "windows" in ptype:
        return "windows"
    if fs == "vfat":
        return "fat"
    if fs == "exfat":
        return "exfat"
    if fs == "swap":
        return "swap"
    if fs == "crypto_LUKS":
        return "locked"
    return "other" if fs else "empty"


def kind_text(p):
    fs = p.get("fstype") or ""
    k = kind_of(p)
    if fs == "BitLocker":
        return "Windows, locked with BitLocker"
    if k == "linux":
        return "GlassOS system" if "/" in mounts(p) else f"Linux ({fs})"
    if k == "windows":
        return "Windows reserved" if not fs else "Windows (NTFS)"
    if k == "locked":
        return "Encrypted (LUKS)"
    if k == "fat":
        return "FAT32"
    if k == "swap":
        return "Swap (memory that spills onto the disk)"
    if k == "other":
        return fs
    return KINDS[k][1]


def segments(disk):
    """Partitions and the free space between them, in disk order."""
    parts = sorted((c for c in disk.get("children") or [] if c["type"] == "part"), key=lambda c: c.get("start") or 0)
    segs, pos = [], MIB
    end = disk["size"] - (MIB if disk.get("pttype") == "gpt" else 0)
    for p in parts:
        start = (p.get("start") or 0) * 512
        if start - pos >= MIN_FREE:
            segs.append({"free": True, "start": pos, "size": start - pos, "id": f"free:{pos}"})
        segs.append({"free": False, "part": p, "start": start, "size": p["size"], "id": p["path"]})
        pos = max(pos, start + p["size"])
    if disk.get("pttype") and end - pos >= MIN_FREE:
        segs.append({"free": True, "start": pos, "size": end - pos, "id": f"free:{pos}"})
    return segs


def seg_name(s):
    if s["free"]:
        return "Free space"
    p = s["part"]
    return p.get("label") or p.get("partlabel") or p["name"]


def seg_color(s):
    return "free" if s["free"] else KINDS[kind_of(s["part"])][0]


def system_reason(p):
    """Why GlassOS can't change this partition while it runs from it, or None."""
    m = mounts(p)
    if any(x in SYSTEM_MOUNTS for x in m):
        return ("GlassOS is running from this partition, so it can't change it now. "
                "Start from the GlassOS USB stick to change it.")
    return None


def rgba(hexcol, a=1.0):
    c = Gdk.RGBA()
    c.parse(hexcol)
    c.alpha = a
    return c


class DiskMap(Gtk.DrawingArea):
    """The bar: one block per partition or free space, as wide as its share of the disk."""

    def __init__(self, on_pick):
        super().__init__()
        self.add_css_class("disk-map")
        self.set_content_height(54)
        self.set_hexpand(True)
        self.segs, self.sel, self.spans = [], None, []
        self.on_pick = on_pick
        self.set_draw_func(self.draw)
        click = Gtk.GestureClick()
        click.connect("pressed", self.clicked)
        self.add_controller(click)

    def show(self, segs, sel):
        self.segs, self.sel = segs, sel
        self.queue_draw()

    def layout(self, w):
        total = sum(s["size"] for s in self.segs) or 1
        gap = 3
        avail = w - gap * max(0, len(self.segs) - 1)
        widths = [max(10.0, s["size"] / total * avail) for s in self.segs]
        k = avail / (sum(widths) or 1)
        x, spans = 0.0, []
        for s, wi in zip(self.segs, widths):
            spans.append((x, x + wi * k, s))
            x += wi * k + gap
        return spans

    @staticmethod
    def rounded(cr, x, y, w, h, r):
        r = min(r, w / 2, h / 2)
        cr.new_sub_path()
        cr.arc(x + w - r, y + r, r, -math.pi / 2, 0)
        cr.arc(x + w - r, y + h - r, r, 0, math.pi / 2)
        cr.arc(x + r, y + h - r, r, math.pi / 2, math.pi)
        cr.arc(x + r, y + r, r, math.pi, 3 * math.pi / 2)
        cr.close_path()

    def draw(self, _a, cr, w, h):
        self.spans = self.layout(w)
        for x0, x1, s in self.spans:
            self.rounded(cr, x0 + 1, 1, x1 - x0 - 2, h - 2, 10)
            if s["free"]:
                cr.set_source_rgba(1, 1, 1, 0.06)
                cr.fill_preserve()
                cr.set_source_rgba(1, 1, 1, 0.35)
                cr.set_dash([4, 3])
                cr.set_line_width(1)
                cr.stroke()
                cr.set_dash([])
            else:
                c = rgba(seg_color(s))
                cr.set_source_rgba(c.red, c.green, c.blue, 0.78)
                cr.fill_preserve()
                cr.set_source_rgba(1, 1, 1, 0.22)
                cr.set_line_width(1)
                cr.stroke()
                used = s["part"].get("fsused")
                if used and s["size"]:   # a lighter band shows how full it is
                    frac = min(1.0, int(used) / s["size"])
                    cr.save()
                    self.rounded(cr, x0 + 1, 1, x1 - x0 - 2, h - 2, 10)
                    cr.clip()
                    cr.rectangle(x0, h - 7, (x1 - x0) * frac, 7)
                    cr.set_source_rgba(1, 1, 1, 0.45)
                    cr.fill()
                    cr.restore()
            if s["id"] == self.sel:
                self.rounded(cr, x0 + 1.5, 1.5, x1 - x0 - 3, h - 3, 10)
                cr.set_source_rgba(1, 1, 1, 0.95)
                cr.set_line_width(2.5)
                cr.stroke()

    def clicked(self, _g, _n, x, _y):
        for x0, x1, s in self.spans:
            if x0 <= x <= x1:
                self.on_pick(s["id"])
                return


def dot(color):
    d = Gtk.DrawingArea()
    d.set_content_width(12)
    d.set_content_height(12)
    d.set_valign(Gtk.Align.CENTER)

    def draw(_a, cr, w, h):
        cr.arc(w / 2, h / 2, 5.5, 0, 2 * math.pi)
        if color == "free":
            cr.set_source_rgba(1, 1, 1, 0.5)
            cr.set_line_width(1.2)
            cr.stroke()
        else:
            c = rgba(color)
            cr.set_source_rgba(c.red, c.green, c.blue, 1)
            cr.fill()
    d.set_draw_func(draw)
    return d


class DisksWindow(Gtk.ApplicationWindow):
    def __init__(self, app):
        super().__init__(application=app, title="Disk Utility")
        self.add_css_class("glass")
        ui.fit_size(self, 960, 640)
        hb = Gtk.HeaderBar()
        hb.set_title_widget(ui.label("Disk Utility", "card-title"))
        self.set_titlebar(hb)
        ui.drag_by_titlebar(self, hb)

        root = ui.hbox(0)
        side = ui.vbox(0, "sidebar-pane")
        side.set_size_request(240, -1)
        self.side = Gtk.ListBox()
        self.side.set_selection_mode(Gtk.SelectionMode.SINGLE)
        sc = Gtk.ScrolledWindow()
        sc.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        sc.set_vexpand(True)
        sc.set_child(self.side)
        side.append(sc)
        root.append(side)

        page = ui.vbox(14, "page")
        page.set_margin_start(26)
        page.set_margin_end(26)
        page.set_margin_top(18)
        page.set_margin_bottom(18)
        head = ui.hbox(12)
        ht = ui.vbox(2)
        ht.set_hexpand(True)
        self.title = ui.label("", "page-title", ellipsize=True)
        self.sub = ui.label("", "page-sub", ellipsize=True)
        ht.append(self.title)
        ht.append(self.sub)
        head.append(ht)
        self.erase_btn = ui.button("Erase disk…", self.ask_erase, "pill")
        self.erase_btn.set_valign(Gtk.Align.CENTER)
        head.append(self.erase_btn)
        page.append(head)

        self.map = DiskMap(self.pick)
        page.append(self.map)
        self.status = ui.label("", "status", wrap=True)
        self.status.set_visible(False)
        page.append(self.status)

        body = ui.hbox(18)
        body.set_vexpand(True)
        self.segs_list = Gtk.ListBox()
        self.segs_list.add_css_class("segs")
        self.segs_list.connect("row-selected", lambda _l, r: r and self.pick(r.seg_id, from_list=True))
        lsc = Gtk.ScrolledWindow()
        lsc.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        lsc.set_child(self.segs_list)
        lsc.set_hexpand(True)
        body.append(lsc)
        self.detail = ui.card()
        self.detail.set_size_request(320, -1)
        self.detail.set_valign(Gtk.Align.START)
        body.append(self.detail)
        page.append(body)
        root.append(page)
        self.set_child(root)

        self.disks, self.raw, self.disk_path, self.sel = [], None, None, None
        self.busy = False
        self.side.connect("row-selected", lambda _l, r: r and self.choose_disk(r.disk_path))
        self.refresh()
        GLib.timeout_add_seconds(3, self.poll)

    # ------------------------------------------------------------------ reading
    def poll(self):
        if not self.busy and self.get_visible():
            self.refresh()
        return True

    def refresh(self, force=False):
        disks, raw = read_disks()
        if raw == self.raw and not force:
            return
        self.disks, self.raw = disks, raw
        ui.clear(self.side)
        rows = {}
        for d in disks:
            r = Gtk.ListBoxRow()
            rb = ui.hbox(10)
            removable = d.get("rm") or d.get("tran") == "usb"
            rb.append(Gtk.Image.new_from_icon_name("drive-removable-media" if removable else "drive-harddisk"))
            t = ui.vbox(0)
            t.append(ui.label(self.disk_name(d), ellipsize=True))
            t.append(ui.label(size_text(d["size"]), "dim small"))
            rb.append(t)
            r.set_child(rb)
            r.disk_path = d["path"]
            rows[d["path"]] = r
            self.side.append(r)
        if not disks:
            self.title.set_text("No disks found")
            self.sub.set_text("")
            return
        if self.disk_path not in rows:
            self.disk_path = disks[0]["path"]
        self.side.select_row(rows[self.disk_path])
        self.choose_disk(self.disk_path)

    @staticmethod
    def disk_name(d):
        model = (d.get("model") or "").strip()
        return model or d["name"]

    def disk(self):
        return next((d for d in self.disks if d["path"] == self.disk_path), None)

    def choose_disk(self, path):
        if path != self.disk_path:
            self.sel = None
        self.disk_path = path
        d = self.disk()
        if not d:
            return
        conn = {"usb": "USB", "nvme": "NVMe", "sata": "SATA", "ata": "SATA", "mmc": "memory card",
                "virtio": "virtual"}.get(d.get("tran") or "", "")
        table = {"gpt": "GPT partition table", "dos": "MBR partition table"}.get(d.get("pttype") or "", "no partition table")
        self.title.set_text(self.disk_name(d))
        self.sub.set_text(" · ".join(x for x in (size_text(d["size"]), conn, table, d["path"]) if x))
        in_use = bool(mounts(d))
        self.erase_btn.set_sensitive(not in_use and not self.busy)
        self.erase_btn.set_tooltip_text("Unmount everything on this disk first." if in_use else
                                        "Erase everything and start with an empty disk.")
        self.segs = segments(d)
        if self.sel not in [s["id"] for s in self.segs]:
            self.sel = self.segs[0]["id"] if self.segs else None
        ui.clear(self.segs_list)
        for s in self.segs:
            r = Gtk.ListBoxRow()
            rb = ui.hbox(10, "seg-row")
            rb.append(dot(seg_color(s)))
            t = ui.vbox(0)
            t.set_hexpand(True)
            t.append(ui.label(seg_name(s), ellipsize=True))
            t.append(ui.label("Room for a new partition" if s["free"] else kind_text(s["part"]), "dim small",
                              ellipsize=True))
            rb.append(t)
            rb.append(ui.label(size_text(s["size"]), "big-num"))
            r.set_child(rb)
            r.seg_id = s["id"]
            self.segs_list.append(r)
            if s["id"] == self.sel:
                self.segs_list.select_row(r)
        if not self.segs:
            self.show_detail(None)
        self.map.show(self.segs, self.sel)

    def pick(self, seg_id, from_list=False):
        self.sel = seg_id
        self.map.show(self.segs, seg_id)
        if not from_list:
            r = self.segs_list.get_first_child()
            while r:
                if getattr(r, "seg_id", None) == seg_id:
                    self.segs_list.select_row(r)
                    break
                r = r.get_next_sibling()
        self.show_detail(next((s for s in self.segs if s["id"] == seg_id), None))

    # ------------------------------------------------------------------ the detail card
    def show_detail(self, s):
        ui.clear(self.detail)
        d = self.disk()
        if s is None:
            self.detail.append(ui.label("Nothing on this disk yet", "card-title"))
            self.detail.append(ui.label("It has no partition table. Erase it to start using it.", "note", wrap=True))
            return
        self.detail.append(ui.label(seg_name(s), "card-title", ellipsize=True))
        if s["free"]:
            self.detail.append(ui.label(f"{size_text(s['size'])} not used by any partition.", "note", wrap=True))
            b = ui.button("New partition…", lambda: self.ask_new(s), "pill accent")
            b.set_sensitive(not self.busy and bool(d.get("pttype")))
            self.detail.append(b)
            return
        p = s["part"]
        m = mounts(p)
        facts = [("Kind", kind_text(p)), ("Size", size_text(p["size"]))]
        if p.get("fsused"):
            facts.append(("Used", f"{size_text(int(p['fsused']))} ({int(p['fsused']) * 100 // p['size']}%)"))
        facts.append(("Open at", ", ".join(m) if m else "Not mounted"))
        facts.append(("Device", p["path"]))
        for k, v in facts:
            r = ui.hbox(10)
            r.append(ui.label(k, "dim small"))
            sp = ui.spacer()
            r.append(sp)
            r.append(ui.label(v, "small mono" if k == "Device" else "small", xalign=1.0, ellipsize=True))
            self.detail.append(r)

        sys_reason = system_reason(p)
        fs = p.get("fstype") or ""
        mountable = fs and fs not in ("swap", "crypto_LUKS", "BitLocker")
        acts = ui.hbox(8)
        if m and not sys_reason and fs != "swap":
            acts.append(ui.button("Open", lambda: subprocess.Popen(["xdg-open", m[0]]), "pill"))
            acts.append(ui.button("Unmount", lambda: self.run_user(["udisksctl", "unmount", "-b", p["path"]],
                                                                   f"Unmounting {seg_name(s)}…"), "pill"))
        elif not m and mountable:
            acts.append(ui.button("Mount", lambda: self.run_user(["udisksctl", "mount", "-b", p["path"]],
                                                                 f"Mounting {seg_name(s)}…"), "pill accent"))
        if acts.get_first_child():
            self.detail.append(acts)

        change = ui.hbox(8)
        fmt = ui.button("Format…", lambda: self.ask_format(s), "pill")
        rsz = ui.button("Resize…", lambda: self.ask_resize(s), "pill")
        dele = ui.button("Delete…", lambda: self.ask_delete(s), "pill danger")
        for b in (fmt, rsz, dele):
            b.set_sensitive(not m and not self.busy)
            change.append(b)
        if fs not in ("ext4", "ext3", "ext2", "ntfs", ""):
            rsz.set_sensitive(False)
            rsz.set_tooltip_text("Disk Utility can resize ext4 and NTFS partitions.")
        self.detail.append(change)
        if sys_reason:
            self.detail.append(ui.label(sys_reason, "note", wrap=True))
        elif m:
            self.detail.append(ui.label("Unmount it to format, resize or delete it.", "note", wrap=True))
        if fs == "BitLocker":
            self.detail.append(ui.label("To resize a BitLocker partition, shrink it from Windows (Disk Management).",
                                        "note", wrap=True))

    # ------------------------------------------------------------------ dialogs
    def dialog(self, title, body, widgets, ok_text, on_ok, danger=False):
        d = Gtk.Window(transient_for=self, modal=True, title=title)
        d.add_css_class("glass")
        d.set_default_size(460, -1)
        d.set_resizable(False)
        hb = Gtk.HeaderBar()
        hb.set_show_title_buttons(False)
        hb.set_title_widget(ui.label(title, "card-title"))
        d.set_titlebar(hb)
        box = ui.vbox(12)
        for side in ("start", "end"):
            getattr(box, f"set_margin_{side}")(22)
        box.set_margin_bottom(20)
        box.set_margin_top(6)
        box.append(ui.label(body, wrap=True))
        for w in widgets:
            box.append(w)
        row = ui.hbox(10)
        row.append(ui.spacer())
        row.append(ui.button("Cancel", d.close, "pill"))
        ok = ui.button(ok_text, lambda: (d.close(), on_ok()), "pill danger" if danger else "pill accent")
        row.append(ok)
        box.append(row)
        d.set_child(box)
        keys = Gtk.EventControllerKey()
        keys.connect("key-pressed", lambda _c, kv, *_a: (d.close(), True)[1] if kv == Gdk.KEY_Escape else False)
        d.add_controller(keys)
        d.present()
        return d

    def format_picker(self, with_empty):
        opts = FORMATS if with_empty else FORMATS[:-1]
        drop = Gtk.DropDown.new_from_strings([o[1] for o in opts])
        name = Gtk.Entry(placeholder_text="Name (optional)")
        name.set_max_length(opts[0][2])

        def changed(*_a):
            name.set_max_length(opts[drop.get_selected()][2])
        drop.connect("notify::selected", changed)
        return drop, name, lambda: (opts[drop.get_selected()][0], name.get_text().strip())

    def size_spin(self, lo_b, hi_b, val_b):
        lo, hi = max(0.01, lo_b / 1e9), hi_b / 1e9
        adj = Gtk.Adjustment(value=min(hi, max(lo, val_b / 1e9)), lower=lo, upper=hi, step_increment=0.1,
                             page_increment=10)
        spin = Gtk.SpinButton(adjustment=adj, digits=2, climb_rate=1)
        r = ui.hbox(10)
        r.append(ui.label("Size"))
        r.append(spin)
        r.append(ui.label(f"GB, up to {size_text(hi_b)}", "dim small"))
        return r, spin

    def ask_new(self, s):
        d = self.disk()
        row, spin = self.size_spin(MIN_FREE, s["size"], s["size"])
        drop, name, get = self.format_picker(True)

        def go():
            fs, nm = get()
            start = math.ceil(s["start"] / MIB)
            size = min(int(spin.get_value() * 1e9) // MIB, (s["start"] + s["size"]) // MIB - start)
            self.run_admin(["new", d["path"], str(start), str(start + size), fs, nm],
                           "Making the partition…")
        self.dialog("New partition", f"Make a partition in the free space on {self.disk_name(d)}.",
                    [row, drop, name], "Create partition", go)

    def ask_format(self, s):
        p = s["part"]
        drop, name, get = self.format_picker(False)
        name.set_text((p.get("label") or "")[:16])

        def go():
            fs, nm = get()
            self.run_admin(["format", p["path"], fs, nm], f"Formatting {seg_name(s)}…")
        self.dialog("Format partition", f"Everything on {seg_name(s)} ({size_text(p['size'])}) is erased.",
                    [drop, name], "Erase and format", go, danger=True)

    def ask_resize(self, s):
        p = s["part"]
        i = self.segs.index(s)
        after = self.segs[i + 1]["size"] if i + 1 < len(self.segs) and self.segs[i + 1]["free"] else 0
        used = int(p.get("fsused") or 0)
        lo = max(MIN_FREE, int(used * 1.1) + 256 * MIB) if used else MIN_FREE
        row, spin = self.size_spin(lo, p["size"] + after, p["size"])
        note = ui.label("Shrinking leaves free space after the partition for a new one. Back up anything "
                        "important first: if the power goes out part way through, the partition can be damaged.",
                        "note", wrap=True)

        def go():
            self.run_admin(["resize", p["path"], str(int(spin.get_value() * 1e9))], f"Resizing {seg_name(s)}…")
        self.dialog("Resize partition", f"{seg_name(s)} is {size_text(p['size'])} now.", [row, note], "Resize", go)

    def ask_delete(self, s):
        p = s["part"]
        self.dialog("Delete partition",
                    f"Delete {seg_name(s)}? Everything on it ({size_text(p['size'])}) is erased, and its space "
                    "becomes free space.", [], "Delete partition",
                    lambda: self.run_admin(["delete", p["path"]], f"Deleting {seg_name(s)}…"), danger=True)

    def ask_erase(self):
        d = self.disk()
        n = sum(1 for s in self.segs if not s["free"])
        what = f"its {n} partition{'s' if n != 1 else ''}" if n else "everything on it"
        self.dialog("Erase disk", f"Erase {self.disk_name(d)} ({size_text(d['size'])})? This deletes {what}. "
                    "The disk gets a new, empty GPT partition table.", [], "Erase disk",
                    lambda: self.run_admin(["erase", d["path"]], f"Erasing {self.disk_name(d)}…"), danger=True)

    # ------------------------------------------------------------------ running changes
    def set_busy(self, text):
        self.busy = bool(text)
        self.status.set_text(text or "")
        self.status.set_visible(bool(text))
        self.side.set_sensitive(not self.busy)
        self.refresh(force=True)

    def run(self, argv, text, admin):
        self.set_busy(text)
        try:
            proc = Gio.Subprocess.new(argv, Gio.SubprocessFlags.STDOUT_PIPE | Gio.SubprocessFlags.STDERR_MERGE)
        except GLib.Error as e:
            self.finish(1, e.message, admin)
            return

        def done(p, res):
            try:
                _ok, out, _err = p.communicate_utf8_finish(res)
            except GLib.Error as e:
                out = e.message
            self.finish(p.get_exit_status() if p.get_if_exited() else 1, out or "", admin)
        proc.communicate_utf8_async(None, None, done)

    def run_admin(self, args, text):
        self.run(as_admin(HELPER, *args), text, True)

    def run_user(self, argv, text):
        self.run(argv, text, False)

    def finish(self, code, out, admin):
        self.set_busy(None)
        if code == 0:
            return
        if admin and (code in (126, 127) or "a password is required" in out):
            self.status.set_text("Nothing changed: an administrator's password is needed.")
            self.status.set_visible(True)
            return
        lines = [ln for ln in out.strip().splitlines() if ln.strip()]
        msg = "\n".join(lines[-4:]) or f"It stopped with error {code}."
        self.dialog("That didn't work", msg, [], "OK", lambda: None)


class DisksApp(Gtk.Application):
    def __init__(self):
        super().__init__(application_id=APP_ID, flags=Gio.ApplicationFlags.DEFAULT_FLAGS)

    def do_activate(self):
        if not self.get_active_window():
            ui.apply_css(CSS)
            DisksWindow(self)
        self.get_active_window().present()


if __name__ == "__main__":
    GLib.set_prgname(APP_ID)
    sys.exit(DisksApp().run(sys.argv))
