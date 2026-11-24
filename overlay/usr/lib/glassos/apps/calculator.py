#!/usr/bin/python3
"""Glass Calculator - a small see-through calculator for GlassOS.

Type with the keyboard or click. Enter = equals, Backspace deletes, Esc clears,
Ctrl+C copies the result.
"""
import sys
from decimal import Decimal, DivisionByZero, InvalidOperation, getcontext

sys.path.insert(0, "/usr/lib/glassos")
import glassui as ui  # noqa: E402
from gi.repository import Gdk, Gio, GLib, Gtk  # noqa: E402

getcontext().prec = 34
OPS = "+−×÷"

CSS = """
.display { padding: 6px 18px 0 18px; }
.expr { font-size: 17px; color: alpha(#ffffff, 0.85); font-feature-settings: "tnum"; }
.result { font-size: 46px; font-weight: 300; font-feature-settings: "tnum"; }
.result.small-result { font-size: 30px; }
.result.error { font-size: 20px; color: #ff9b9b; }
button.key {
  min-width: 58px; min-height: 58px; border-radius: 99px; padding: 0;
  font-size: 21px; font-weight: 500; color: #fff;
  background: alpha(#ffffff, 0.10);
  border: 1px solid alpha(#ffffff, 0.12); border-top-color: alpha(#ffffff, 0.28);
  box-shadow: inset 0 1px alpha(#ffffff, 0.08), 0 3px 10px alpha(#000000, 0.18);
  transition: background 120ms ease, transform 80ms ease;
}
button.key:hover { background: alpha(#ffffff, 0.17); }
button.key:active { background: alpha(#ffffff, 0.26); transform: scale(0.94); }
button.key.fn { background: alpha(#ffffff, 0.05); color: alpha(#ffffff, 0.85); font-size: 18px; }
button.key.op { background: alpha(#8fb8ff, 0.24); border-color: alpha(#bcd4ff, 0.3); }
button.key.op:hover { background: alpha(#8fb8ff, 0.36); }
button.key.op.armed { background: alpha(#ffffff, 0.85); color: #232436; }
button.key.eq { background: linear-gradient(160deg, alpha(#9a8cff, 0.85), alpha(#5a9cff, 0.85));
                border-color: alpha(#ffffff, 0.35); }
button.key.eq:hover { background: linear-gradient(160deg, alpha(#ab9fff, 0.95), alpha(#6ea9ff, 0.95)); }
"""


class CalcError(Exception):
    pass


def tokenize(s):
    toks, i = [], 0
    while i < len(s):
        c = s[i]
        if c.isdigit() or c == ".":
            j = i
            while j < len(s) and (s[j].isdigit() or s[j] == "."):
                j += 1
            num = s[i:j]
            if num.count(".") > 1:
                raise CalcError("Too many decimal points")
            toks.append(("num", Decimal(num if num != "." else "0")))
            i = j
        elif c in OPS + "()%":
            toks.append(("op", c))
            i += 1
        elif c == " ":
            i += 1
        else:
            raise CalcError(f"Unexpected '{c}'")
    return toks


class Parser:
    """expr := term (('+'|'−') term)* ; term := unary (('×'|'÷') unary)* ;
       unary := '−' unary | postfix ; postfix := primary '%'* ; primary := num | '(' expr ')'"""

    def __init__(self, toks):
        self.t, self.i = toks, 0

    def peek(self):
        return self.t[self.i] if self.i < len(self.t) else (None, None)

    def take(self):
        tok = self.peek()
        self.i += 1
        return tok

    def parse(self):
        if not self.t:
            return Decimal(0)
        v = self.expr()
        if self.i != len(self.t):
            raise CalcError("Check the expression")
        return v

    def expr(self):
        v = self.term()
        while self.peek() in (("op", "+"), ("op", "−")):
            op = self.take()[1]
            r = self.term()
            v = v + r if op == "+" else v - r
        return v

    def term(self):
        v = self.unary()
        while self.peek() in (("op", "×"), ("op", "÷")):
            op = self.take()[1]
            r = self.unary()
            if op == "×":
                v = v * r
            else:
                if r == 0:
                    raise CalcError("Can't divide by zero")
                v = v / r
        return v

    def unary(self):
        if self.peek() == ("op", "−"):
            self.take()
            return -self.unary()
        if self.peek() == ("op", "+"):
            self.take()
            return self.unary()
        return self.postfix()

    def postfix(self):
        v = self.primary()
        while self.peek() == ("op", "%"):
            self.take()
            v = v / 100
        return v

    def primary(self):
        kind, val = self.take()
        if kind == "num":
            return val
        if (kind, val) == ("op", "("):
            v = self.expr()
            if self.peek() == ("op", ")"):
                self.take()
            return v   # a missing ")" at the end is forgiven
        raise CalcError("Check the expression")


def evaluate(expr):
    try:
        return Parser(tokenize(expr)).parse()
    except (InvalidOperation, DivisionByZero):
        raise CalcError("Not a number")


def fmt(d):
    return _fmt(d).replace("-", "−")


def _fmt(d):
    if d.is_nan() or d.is_infinite():
        return "Not a number"
    if d == d.to_integral_value() and abs(d) < Decimal("1e16"):
        return f"{int(d):,}"
    if abs(d) >= Decimal("1e16") or (d != 0 and abs(d) < Decimal("1e-9")):
        s = f"{d:.10E}"
        mant, exp = s.split("E")
        mant = mant.rstrip("0").rstrip(".")
        return f"{mant}e{int(exp)}"
    q = d.quantize(Decimal("1e-12")).normalize()
    whole, _, frac = f"{q:f}".partition(".")
    sign = "-" if whole.startswith("-") else ""
    whole = whole.lstrip("-")
    return f"{sign}{int(whole):,}" + (f".{frac}" if frac else "")


class CalcWindow(Gtk.ApplicationWindow):
    def __init__(self, app):
        super().__init__(application=app, title="Calculator")
        self.add_css_class("glass")
        self.set_default_size(320, 500)
        self.set_resizable(False)
        hb = Gtk.HeaderBar()
        hb.set_title_widget(ui.label("Calculator", "dim small"))
        self.set_titlebar(hb)
        ui.drag_by_titlebar(self, hb)

        self.expr = ""
        self.last_result = None
        self.just_done = False

        root = ui.vbox(10)
        root.set_margin_start(16)
        root.set_margin_end(16)
        root.set_margin_bottom(18)
        disp = ui.vbox(0, "display")
        disp.set_vexpand(True)
        disp.set_valign(Gtk.Align.END)
        self.expr_l = ui.label("", "expr", xalign=1.0, ellipsize=True)
        self.res_l = ui.label("0", "result", xalign=1.0, ellipsize=True)
        self.res_l.set_selectable(True)
        disp.append(self.expr_l)
        disp.append(self.res_l)
        root.append(disp)

        grid = Gtk.Grid(row_spacing=11, column_spacing=11, column_homogeneous=True, row_homogeneous=True)
        keys = [
            [("C", "fn", "clear"), ("( )", "fn", "paren"), ("%", "fn", "%"), ("÷", "op", "÷")],
            [("7", "", "7"), ("8", "", "8"), ("9", "", "9"), ("×", "op", "×")],
            [("4", "", "4"), ("5", "", "5"), ("6", "", "6"), ("−", "op", "−")],
            [("1", "", "1"), ("2", "", "2"), ("3", "", "3"), ("+", "op", "+")],
            [("±", "fn", "neg"), ("0", "", "0"), (".", "", "."), ("=", "eq", "=")],
        ]
        self.op_buttons = {}
        for r, row in enumerate(keys):
            for c, (text, cls, action) in enumerate(row):
                b = Gtk.Button(label=text)
                b.add_css_class("key")
                if cls:
                    b.add_css_class(cls)
                b.set_focusable(False)
                b.connect("clicked", lambda _b, a=action: self.press(a))
                grid.attach(b, c, r, 1, 1)
                if cls == "op":
                    self.op_buttons[action] = b
                if action == "clear":
                    self.clear_btn = b
        root.append(grid)
        self.set_child(root)

        keyc = Gtk.EventControllerKey()
        keyc.connect("key-pressed", self.on_key)
        self.add_controller(keyc)
        copy = Gio.SimpleAction.new("copy", None)
        copy.connect("activate", lambda *_: self.copy())
        self.add_action(copy)
        app.set_accels_for_action("win.copy", ["<Control>c"])
        self.refresh()

    # ---------------------------------------------------------------- input
    def press(self, a):
        if a == "clear":
            if self.expr and not self.just_done:
                self.expr = ""
            else:
                self.expr, self.last_result = "", None
            self.just_done = False
        elif a == "back":
            self.expr = self.expr[:-1]
            self.just_done = False
        elif a == "=":
            if not self.expr:
                return
            try:
                v = evaluate(self.expr.rstrip(OPS))
                self.expr_l.set_text(self.pretty(self.expr) + " =")
                self.last_result = v
                self.expr = self.plain(v)
                self.just_done = True
                self.show_result(fmt(v))
                self.update_ops()
                return
            except CalcError as e:
                self.show_error(str(e))
                return
        elif a == "neg":
            self.negate_last()
        elif a == "paren":
            opens = self.expr.count("(") - self.expr.count(")")
            if opens > 0 and self.expr and (self.expr[-1].isdigit() or self.expr[-1] in ").%"):
                self.expr += ")"
            else:
                self.add("(")
        elif a in OPS:
            if self.just_done:
                self.just_done = False
            if self.expr and self.expr[-1] in OPS:
                if a == "−" and self.expr[-1] in "×÷":
                    self.expr += a          # 5 × −2
                else:
                    self.expr = self.expr[:-1] + a
            elif self.expr or a == "−":
                self.expr += a
        else:
            self.add(a)
        self.refresh()

    def add(self, ch):
        if self.just_done:
            if ch.isdigit() or ch in ".(":
                self.expr = ""
            self.just_done = False
        if ch == ".":
            cur = self.current_number()
            if "." in cur:
                return
            if not cur:
                ch = "0."
        if ch == "(" and self.expr and (self.expr[-1].isdigit() or self.expr[-1] in ").%"):
            self.expr += "×"
        if ch.isdigit() and self.expr.endswith(")"):
            self.expr += "×"
        self.expr += ch

    def current_number(self):
        i = len(self.expr)
        while i > 0 and (self.expr[i - 1].isdigit() or self.expr[i - 1] == "."):
            i -= 1
        return self.expr[i:]

    def negate_last(self):
        cur = self.current_number()
        if not cur:
            if not self.expr or self.expr[-1] in OPS + "(":
                self.expr += "−"
            return
        start = len(self.expr) - len(cur)
        before = self.expr[:start]
        if before.endswith("(−"):
            self.expr = before[:-2] + cur
        elif before == "−":
            self.expr = cur
        elif not before:
            self.expr = "(−" + cur
        else:
            self.expr = before + "(−" + cur
        self.just_done = False

    def on_key(self, _c, keyval, _code, state):
        if state & Gdk.ModifierType.CONTROL_MASK:
            return False
        name = Gdk.keyval_name(keyval) or ""
        ch = chr(Gdk.keyval_to_unicode(keyval)) if Gdk.keyval_to_unicode(keyval) else ""
        mapping = {"+": "+", "-": "−", "*": "×", "x": "×", "X": "×", "/": "÷", "%": "%",
                   "(": "(", ")": ")", ".": ".", ",": ".", "=": "="}
        if ch.isdigit():
            self.press(ch)
        elif ch in mapping:
            m = mapping[ch]
            if m == ")":
                self.expr += ")"
                self.refresh()
            else:
                self.press(m)
        elif name in ("Return", "KP_Enter"):
            self.press("=")
        elif name == "BackSpace":
            self.press("back")
        elif name in ("Escape", "Delete"):
            self.press("clear")
        elif name.startswith("KP_") and name[3:].isdigit():
            self.press(name[3:])
        else:
            return False
        return True

    def copy(self):
        txt = self.res_l.get_text().replace(",", "").replace("−", "-")
        self.get_clipboard().set(txt)

    # ---------------------------------------------------------------- output
    @staticmethod
    def plain(d):
        s = f"{d.normalize():f}"
        return s.replace("-", "−") if not s.startswith("-") else "(−" + s[1:]

    @staticmethod
    def pretty(expr):
        out = ""
        for ch in expr:
            out += f" {ch} " if ch in "+×÷" or (ch == "−" and out and out[-1] not in "( ") else ch
        return " ".join(out.split())

    def show_result(self, text):
        self.res_l.remove_css_class("error")
        self.res_l.set_text(text)
        if len(text) > 11:
            self.res_l.add_css_class("small-result")
        else:
            self.res_l.remove_css_class("small-result")

    def show_error(self, msg):
        self.res_l.remove_css_class("small-result")
        self.res_l.add_css_class("error")
        self.res_l.set_text(msg)

    def update_ops(self):
        last = self.expr[-1] if self.expr else ""
        for op, b in self.op_buttons.items():
            (b.add_css_class if last == op else b.remove_css_class)("armed")
        self.clear_btn.set_label("C" if self.expr and not self.just_done else "AC")

    def refresh(self):
        self.update_ops()
        if self.just_done:
            return
        self.expr_l.set_text(self.pretty(self.expr))
        cur = self.expr.rstrip(OPS)
        if not cur:
            self.show_result("0")
            return
        try:
            self.show_result(fmt(evaluate(cur)))
        except CalcError:
            self.show_result(self.current_number() or "…")


class CalcApp(Gtk.Application):
    def __init__(self):
        super().__init__(application_id="os.glass.Calculator", flags=Gio.ApplicationFlags.DEFAULT_FLAGS)

    def do_activate(self):
        if not self.get_active_window():
            ui.apply_css(CSS)
            CalcWindow(self)
        self.get_active_window().present()


if __name__ == "__main__":
    GLib.set_prgname("os.glass.Calculator")
    sys.exit(CalcApp().run(sys.argv))
