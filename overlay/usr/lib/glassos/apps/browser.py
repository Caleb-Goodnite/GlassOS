#!/usr/bin/python3
"""Glass Browser - a simple, private, see-through web browser for GlassOS (WebKitGTK).

Private by default:
  * no telemetry, no accounts, no sync, no "safe browsing" lookups sent anywhere
  * third-party cookies blocked and Intelligent Tracking Prevention on
  * DuckDuckGo search, and a local start page
  * sites must ask before using your camera, microphone, location or notifications
  * Private windows (Ctrl+Shift+N) keep nothing at all once closed
For sites that need a heavier browser, the menu has "Open in Firefox".
"""
import os
import subprocess
import sys
import urllib.parse

sys.path.insert(0, "/usr/lib/glassos")
import glassui as ui  # noqa: E402
import gi  # noqa: E402

gi.require_version("WebKit", "6.0")
from gi.repository import Gdk, Gio, GLib, Gtk, Pango, WebKit  # noqa: E402

APP_ID = "os.glass.Browser"
HOME = "file:///usr/share/glassos/welcome/index.html#glass"
SEARCH = "https://duckduckgo.com/?q={}"
DATA = os.path.join(GLib.get_user_data_dir(), "glass-browser")
CACHE = os.path.join(GLib.get_user_cache_dir(), "glass-browser")
DOWNLOADS = GLib.get_user_special_dir(GLib.UserDirectory.DIRECTORY_DOWNLOAD) or os.path.expanduser("~/Downloads")

CSS = """
window.browser headerbar { padding: 0 6px; }
entry.urlbar { min-height: 34px; border-radius: 99px; padding: 0 14px; font-size: 14px;
               background: alpha(#ffffff, 0.09); }
entry.urlbar progress { background: alpha(#8fb8ff, 0.6); border-radius: 99px; min-height: 2px; }
notebook > header { background: transparent; border: none; box-shadow: none; padding: 0 8px 4px 8px; }
notebook > header > tabs > tab { border-radius: 10px; padding: 4px 10px; margin: 0 2px; min-height: 26px;
                                 background: transparent; border: none; color: alpha(#ffffff, 0.7); }
notebook > header > tabs > tab:hover { background: alpha(#ffffff, 0.06); }
notebook > header > tabs > tab:checked { background: alpha(#ffffff, 0.14); color: #fff;
                                         box-shadow: inset 0 1px alpha(#ffffff, 0.12); }
notebook > stack { background: transparent; }
.tab-close { min-width: 18px; min-height: 18px; padding: 0; border-radius: 99px; background: none;
             border: none; box-shadow: none; }
.tab-close:hover { background: alpha(#ffffff, 0.18); }
.webframe { border-radius: 0 0 14px 14px; }
window.private { background-color: alpha(#1b1030, 0.6); }
.private-badge { background: alpha(#a37bff, 0.35); border-radius: 99px; padding: 2px 10px; font-size: 12px;
                 font-weight: 700; }
.findbar { padding: 6px 10px; background: alpha(#ffffff, 0.05); }
.status { background: alpha(#10111a, 0.85); color: #fff; border-radius: 8px; padding: 3px 10px;
          font-size: 12px; margin: 0 0 8px 8px; }
"""


def to_uri(text):
    t = text.strip()
    if not t:
        return HOME
    low = t.lower()
    if low.startswith(("http://", "https://", "file://", "about:", "data:", "view-source:")):
        return t
    if " " not in t and ("." in t or low.startswith("localhost")) and not t.endswith("."):
        return "https://" + t
    return SEARCH.format(urllib.parse.quote_plus(t))


def display_uri(uri):
    if not uri or uri.startswith(HOME.split("#")[0]):
        return ""
    return uri


class Tab(Gtk.Box):
    def __init__(self, win, view=None):
        super().__init__(orientation=Gtk.Orientation.VERTICAL)
        self.win = win
        self.view = view or WebKit.WebView(network_session=win.session)
        self.view.set_vexpand(True)
        self.view.set_hexpand(True)
        # let pages that don't paint a background show the glass (the start page uses this)
        clear = Gdk.RGBA()
        clear.parse("rgba(0,0,0,0)")
        self.view.set_background_color(clear)
        s = self.view.get_settings()
        s.set_enable_developer_extras(True)
        s.set_enable_back_forward_navigation_gestures(True)
        s.set_enable_smooth_scrolling(True)
        s.set_javascript_can_open_windows_automatically(False)
        s.set_enable_webrtc(True)
        s.set_enable_media_stream(True)
        s.set_hardware_acceleration_policy(WebKit.HardwareAccelerationPolicy.ALWAYS
                                           if os.path.exists("/dev/dri/renderD128")
                                           else WebKit.HardwareAccelerationPolicy.NEVER)

        overlay = Gtk.Overlay()
        overlay.set_child(self.view)
        self.status = ui.label("", "status", ellipsize=True)
        self.status.set_halign(Gtk.Align.START)
        self.status.set_valign(Gtk.Align.END)
        self.status.set_max_width_chars(80)
        self.status.set_visible(False)
        self.status.set_can_target(False)
        overlay.add_overlay(self.status)
        self.append(overlay)

        # tab label: title + close button
        self.tab_label = ui.hbox(6)
        self.title = ui.label("New Tab", ellipsize=True)
        self.title.set_max_width_chars(22)
        self.title.set_width_chars(10)
        self.tab_label.append(self.title)
        close = Gtk.Button.new_from_icon_name("window-close-symbolic")
        close.add_css_class("tab-close")
        close.connect("clicked", lambda *_: win.close_tab(self))
        self.tab_label.append(close)

        v = self.view
        v.connect("notify::title", self.on_title)
        v.connect("notify::uri", lambda *_: win.sync_toolbar(self))
        v.connect("notify::estimated-load-progress", lambda *_: win.sync_toolbar(self))
        v.connect("load-changed", lambda *_: win.sync_toolbar(self))
        v.connect("create", self.on_create)
        v.connect("permission-request", self.on_permission)
        v.connect("mouse-target-changed", self.on_hover)
        v.connect("close", lambda *_: win.close_tab(self))
        v.connect("load-failed-with-tls-errors", self.on_tls_error)

    def on_title(self, *_):
        t = self.view.get_title() or display_uri(self.view.get_uri()) or "New Tab"
        self.title.set_text(t)
        self.tab_label.set_tooltip_text(t)
        self.win.sync_toolbar(self)

    def on_create(self, view, _action):
        new = WebKit.WebView(related_view=view)
        tab = self.win.add_tab(view=new, focus=True)
        new.connect("ready-to-show", lambda *_: self.win.notebook.set_current_page(
            self.win.notebook.page_num(tab)))
        return new

    def on_hover(self, _v, hit, _mods):
        if hit.context_is_link():
            self.status.set_text(hit.get_link_uri())
            self.status.set_visible(True)
        else:
            self.status.set_visible(False)

    def on_permission(self, _view, req):
        host = urllib.parse.urlparse(self.view.get_uri() or "").hostname or "This page"
        what = None
        if isinstance(req, WebKit.UserMediaPermissionRequest):
            cam = req.get_property("is-for-video-device")
            mic = req.get_property("is-for-audio-device")
            what = "your camera and microphone" if cam and mic else ("your camera" if cam else "your microphone")
            if req.get_property("is-for-display-device"):
                what = "your screen"
        elif isinstance(req, WebKit.GeolocationPermissionRequest):
            what = "your location"
        elif isinstance(req, WebKit.NotificationPermissionRequest):
            what = "show notifications"
        elif isinstance(req, WebKit.ClipboardPermissionRequest):
            what = "read your clipboard"
        if what is None:
            req.deny()
            return True
        dlg = Gtk.AlertDialog(message=f"Allow {host} to use {what}?" if not what.startswith(("show", "read"))
                              else f"Allow {host} to {what}?",
                              detail="Only allow this if you trust the site. You'll be asked again next time.",
                              buttons=["Don't Allow", "Allow"], cancel_button=0, default_button=0)

        def done(d, res):
            try:
                (req.allow if d.choose_finish(res) == 1 else req.deny)()
            except GLib.Error:
                req.deny()

        dlg.choose(self.win, None, done)
        return True

    def on_tls_error(self, view, failing_uri, _cert, _errors):
        host = urllib.parse.urlparse(failing_uri).hostname or failing_uri
        view.load_alternate_html(
            f"""<html><body style="font-family:Inter,sans-serif;background:transparent;color:#fff;
            display:flex;align-items:center;justify-content:center;height:90vh;text-align:center">
            <div><h1>This connection isn't private</h1>
            <p>The certificate for <b>{GLib.markup_escape_text(host)}</b> isn't valid, so someone could be
            reading or changing what you send. Glass Browser stopped loading it.</p></div></body></html>""",
            failing_uri, None)
        return True


class BrowserWindow(Gtk.ApplicationWindow):
    def __init__(self, app, private=False):
        super().__init__(application=app, title="Glass Browser")
        self.private = private
        self.add_css_class("glass")
        self.add_css_class("browser")
        if private:
            self.add_css_class("private")
            self.session = WebKit.NetworkSession.new_ephemeral()
        else:
            self.session = app.session
        ui.fit_size(self, 1180, 800)

        hb = Gtk.HeaderBar()
        self.back = ui.icon_button("go-previous-symbolic", lambda: self.cur().view.go_back(), "Back (Alt+Left)")
        self.fwd = ui.icon_button("go-next-symbolic", lambda: self.cur().view.go_forward(), "Forward (Alt+Right)")
        self.reload = ui.icon_button("view-refresh-symbolic", self.reload_or_stop, "Reload (Ctrl+R)")
        for b in (self.back, self.fwd, self.reload):
            hb.pack_start(b)
        self.url = Gtk.Entry()
        self.url.add_css_class("urlbar")
        self.url.add_css_class("glass-entry")
        self.url.set_hexpand(True)
        self.url.set_size_request(420, -1)
        self.url.set_placeholder_text("Search privately or type an address")
        self.url.connect("activate", self.on_go)
        hb.set_title_widget(self.url)
        menu = Gio.Menu()
        sec1 = Gio.Menu()
        sec1.append("New Tab", "win.new-tab")
        sec1.append("New Private Window", "app.private-window")
        menu.append_section(None, sec1)
        sec2 = Gio.Menu()
        sec2.append("Find in Page", "win.find")
        sec2.append("Zoom In", "win.zoom-in")
        sec2.append("Zoom Out", "win.zoom-out")
        sec2.append("Actual Size", "win.zoom-reset")
        menu.append_section(None, sec2)
        sec3 = Gio.Menu()
        sec3.append("Open This Page in Firefox", "win.firefox")
        sec3.append("Clear Browsing Data", "win.clear-data")
        sec3.append("Downloads Folder", "win.downloads")
        menu.append_section(None, sec3)
        mb = Gtk.MenuButton(icon_name="open-menu-symbolic", menu_model=menu)
        mb.add_css_class("round")
        hb.pack_end(mb)
        hb.pack_end(ui.icon_button("tab-new-symbolic", lambda: self.add_tab(focus=True), "New tab (Ctrl+T)"))
        if private:
            hb.pack_end(ui.label("Private", "private-badge"))
        self.set_titlebar(hb)
        ui.drag_by_titlebar(self, hb)

        body = ui.vbox(0)
        self.findbar = Gtk.Revealer()
        fb = ui.hbox(8, "findbar")
        self.find_entry = Gtk.SearchEntry()
        self.find_entry.set_hexpand(True)
        self.find_entry.connect("search-changed", self.on_find)
        self.find_entry.connect("activate", lambda *_: self.cur().view.get_find_controller().search_next())
        self.find_entry.connect("stop-search", lambda *_: self.hide_find())
        self.find_count = ui.label("", "dim small")
        fb.append(self.find_entry)
        fb.append(self.find_count)
        fb.append(ui.icon_button("window-close-symbolic", self.hide_find))
        self.findbar.set_child(fb)
        body.append(self.findbar)

        self.notebook = Gtk.Notebook()
        self.notebook.set_scrollable(True)
        self.notebook.set_show_border(False)
        self.notebook.set_vexpand(True)
        self.notebook.connect("switch-page", lambda nb, page, n: GLib.idle_add(self.sync_toolbar, page))
        body.append(self.notebook)
        self.set_child(body)

        acts = {
            "new-tab": lambda: self.add_tab(focus=True),
            "close-tab": lambda: self.close_tab(self.cur()),
            "focus-url": self.focus_url,
            "reload": lambda: self.cur().view.reload(),
            "back": lambda: self.cur().view.go_back(),
            "forward": lambda: self.cur().view.go_forward(),
            "find": self.show_find,
            "zoom-in": lambda: self.zoom(0.1),
            "zoom-out": lambda: self.zoom(-0.1),
            "zoom-reset": lambda: self.zoom(None),
            "firefox": self.open_in_firefox,
            "clear-data": self.clear_data,
            "downloads": lambda: subprocess.Popen(["xdg-open", DOWNLOADS]),
            "next-tab": lambda: self.notebook.next_page(),
            "prev-tab": lambda: self.notebook.prev_page(),
        }
        for name, fn in acts.items():
            a = Gio.SimpleAction.new(name, None)
            a.connect("activate", lambda _a, _p, f=fn: f())
            self.add_action(a)
        self.present()

    # ---------------------------------------------------------------- tabs
    def cur(self):
        return self.notebook.get_nth_page(self.notebook.get_current_page())

    def add_tab(self, uri=None, view=None, focus=True):
        tab = Tab(self, view)
        n = self.notebook.append_page(tab, tab.tab_label)
        self.notebook.set_tab_reorderable(tab, True)
        self.notebook.set_show_tabs(self.notebook.get_n_pages() > 1)
        if view is None:
            tab.view.load_uri(uri or HOME)
        if focus:
            self.notebook.set_current_page(n)
            if not uri and view is None:
                GLib.idle_add(self.focus_url)
        return tab

    def close_tab(self, tab):
        if tab is None:
            return
        n = self.notebook.page_num(tab)
        if n < 0:
            return
        self.notebook.remove_page(n)
        if self.notebook.get_n_pages() == 0:
            self.close()
            return
        self.notebook.set_show_tabs(self.notebook.get_n_pages() > 1)

    # ---------------------------------------------------------------- toolbar
    def sync_toolbar(self, tab=None):
        cur = self.cur()
        if tab is not None and tab is not cur:
            return False
        if cur is None:
            return False
        v = cur.view
        self.back.set_sensitive(v.can_go_back())
        self.fwd.set_sensitive(v.can_go_forward())
        loading = v.is_loading()
        self.reload.set_icon_name("process-stop-symbolic" if loading else "view-refresh-symbolic")
        p = v.get_estimated_load_progress()
        self.url.set_progress_fraction(p if loading and p < 1 else 0)
        if not self.url.has_focus() or not self.url.get_text():
            self.url.set_text(display_uri(v.get_uri()))
        uri = v.get_uri() or ""
        if uri.startswith("https://"):
            self.url.set_icon_from_icon_name(Gtk.EntryIconPosition.PRIMARY, "security-high-symbolic")
            self.url.set_icon_tooltip_text(Gtk.EntryIconPosition.PRIMARY, "Encrypted connection")
        elif uri.startswith("http://"):
            self.url.set_icon_from_icon_name(Gtk.EntryIconPosition.PRIMARY, "security-low-symbolic")
            self.url.set_icon_tooltip_text(Gtk.EntryIconPosition.PRIMARY,
                                           "Not encrypted: others on the network can see this page")
        else:
            self.url.set_icon_from_icon_name(Gtk.EntryIconPosition.PRIMARY, "system-search-symbolic")
        title = v.get_title()
        self.set_title(f"{title} - Glass Browser" if title else "Glass Browser")
        return False

    def reload_or_stop(self):
        v = self.cur().view
        v.stop_loading() if v.is_loading() else v.reload()

    def on_go(self, entry):
        self.cur().view.load_uri(to_uri(entry.get_text()))
        self.cur().view.grab_focus()

    def focus_url(self):
        self.url.grab_focus()
        self.url.select_region(0, -1)
        return False

    def zoom(self, step):
        v = self.cur().view
        v.set_zoom_level(1.0 if step is None else max(0.3, min(3.0, v.get_zoom_level() + step)))

    # ---------------------------------------------------------------- find
    def show_find(self):
        self.findbar.set_reveal_child(True)
        self.find_entry.grab_focus()

    def hide_find(self):
        self.findbar.set_reveal_child(False)
        self.cur().view.get_find_controller().search_finish()
        self.find_count.set_text("")

    def on_find(self, entry):
        fc = self.cur().view.get_find_controller()
        text = entry.get_text()
        if not text:
            fc.search_finish()
            self.find_count.set_text("")
            return
        if not getattr(fc, "_glass_hooked", False):
            fc.connect("counted-matches", lambda _f, n: self.find_count.set_text(f"{n} found"))
            fc.connect("failed-to-find-text", lambda *_: self.find_count.set_text("Not found"))
            fc._glass_hooked = True
        opts = WebKit.FindOptions.CASE_INSENSITIVE | WebKit.FindOptions.WRAP_AROUND
        fc.count_matches(text, opts, 1000)
        fc.search(text, opts, 1000)

    # ---------------------------------------------------------------- misc
    def open_in_firefox(self):
        uri = self.cur().view.get_uri() or ""
        args = ["glass-launch", "firefox-esr"] + ([uri] if uri.startswith("http") else [])
        try:
            subprocess.Popen(args, start_new_session=True)
        except OSError:
            pass

    def clear_data(self):
        dlg = Gtk.AlertDialog(message="Clear all browsing data?",
                              detail="Cookies, site storage, cache and logins for every site are deleted. "
                                     "Your downloads stay.",
                              buttons=["Cancel", "Clear"], cancel_button=0, default_button=0)

        def done(d, res):
            try:
                if d.choose_finish(res) != 1:
                    return
            except GLib.Error:
                return
            self.session.get_website_data_manager().clear(WebKit.WebsiteDataTypes.ALL, 0, None, None, None)

        dlg.choose(self, None, done)


class BrowserApp(Gtk.Application):
    def __init__(self):
        super().__init__(application_id=APP_ID, flags=Gio.ApplicationFlags.HANDLES_OPEN)
        self.session = None
        self.add_main_option("private", 0, GLib.OptionFlags.NONE, GLib.OptionArg.NONE,
                             "Open a private window", None)

    def do_handle_local_options(self, options):
        if options.contains("private"):
            self.register(None)
            if self.get_is_remote():          # already running: ask it for a private window
                self.activate_action("private-window", None)
                return 0
            self.start_private = True
        return -1

    def do_startup(self):
        Gtk.Application.do_startup(self)
        ui.apply_css(CSS)
        os.makedirs(DATA, exist_ok=True)
        os.makedirs(CACHE, exist_ok=True)
        self.session = WebKit.NetworkSession.new(DATA, CACHE)
        self.session.set_itp_enabled(True)
        self.session.get_cookie_manager().set_accept_policy(WebKit.CookieAcceptPolicy.NO_THIRD_PARTY)
        self.session.connect("download-started", self.on_download)
        pw = Gio.SimpleAction.new("private-window", None)
        pw.connect("activate", lambda *_: self.new_window(private=True))
        self.add_action(pw)
        accels = {
            "win.new-tab": ["<Control>t"], "win.close-tab": ["<Control>w"], "win.focus-url": ["<Control>l", "F6"],
            "win.reload": ["<Control>r", "F5"], "win.back": ["<Alt>Left"], "win.forward": ["<Alt>Right"],
            "win.find": ["<Control>f"], "win.zoom-in": ["<Control>plus", "<Control>equal"],
            "win.zoom-out": ["<Control>minus"], "win.zoom-reset": ["<Control>0"],
            "win.next-tab": ["<Control>Tab", "<Control>Page_Down"],
            "win.prev-tab": ["<Control><Shift>Tab", "<Control>Page_Up"],
            "app.private-window": ["<Control><Shift>n"],
        }
        for act, keys in accels.items():
            self.set_accels_for_action(act, keys)

    def new_window(self, uris=None, private=False):
        w = BrowserWindow(self, private=private)
        if uris:
            for u in uris:
                w.add_tab(u, focus=True)
        else:
            w.add_tab(focus=True)
        return w

    def do_activate(self):
        self.new_window(private=getattr(self, "start_private", False))
        self.start_private = False

    def do_open(self, files, _n, _hint):
        uris = [f.get_uri() for f in files]
        win = self.get_active_window()
        if win and not win.private:
            for u in uris:
                win.add_tab(u, focus=True)
            win.present()
        else:
            self.new_window(uris)

    def on_download(self, _session, download):
        def decide(d, suggested):
            name = os.path.basename(suggested or "download")
            base, ext = os.path.splitext(name)
            dest = os.path.join(DOWNLOADS, name)
            i = 1
            while os.path.exists(dest):
                dest = os.path.join(DOWNLOADS, f"{base} ({i}){ext}")
                i += 1
            os.makedirs(DOWNLOADS, exist_ok=True)
            d.set_destination(dest)
            return True

        def finished(d):
            dest = d.get_destination() or ""
            subprocess.Popen(["notify-send", "-a", "Glass Browser", "-i", "folder-download",
                              "Download finished", os.path.basename(dest)])

        download.connect("decide-destination", decide)
        download.connect("finished", finished)


if __name__ == "__main__":
    GLib.set_prgname(APP_ID)
    if not os.path.exists("/dev/dri/renderD128"):
        # no GPU (e.g. in some virtual machines): use WebKit's CPU renderer
        os.environ.setdefault("WEBKIT_DISABLE_DMABUF_RENDERER", "1")
        os.environ.setdefault("WEBKIT_DISABLE_COMPOSITING_MODE", "1")
    sys.exit(BrowserApp().run(sys.argv))
