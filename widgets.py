import tkinter as tk

# ── Colour palette — black / white theme ──────────────────────────────────────
BG      = "#0a0a0a"
BG2     = "#070707"
BG3     = "#111111"
ACCENT  = "#ed8796"
ACCENT2 = "#000000"
FG      = "#ffffff"
FG_DIM  = "#444444"
ORANGE  = "#f5a97f"
BORDER  = "#ffffff"

# ── Typography ─────────────────────────────────────────────────────────────────
_F      = "Cascadia Code"
F_BODY  = (_F,  9, "bold")
F_SMALL = (_F,  8)
F_MONO  = (_F,  9)
F_TITLE = (_F, 13, "bold")
F_HEAD  = (_F, 10, "bold")
F_BIG   = (_F, 11, "bold")


def _round_rect(canvas, x1, y1, x2, y2, r, **kw):
    """Draw a smooth filled+outlined rounded rectangle on a Canvas."""
    canvas.create_polygon(
        x1+r, y1,    x2-r, y1,
        x2,   y1,    x2,   y1+r,
        x2,   y2-r,  x2,   y2,
        x2-r, y2,    x1+r, y2,
        x1,   y2,    x1,   y2-r,
        x1,   y1+r,  x1,   y1,
        smooth=True, **kw
    )


class RoundedPanel(tk.Canvas):
    """Container with a rounded-rectangle border. Pack children into *.inner*."""

    def __init__(self, parent, radius=8, bg=BG3, border_color=BORDER,
                 outer_bg=BG, **kw):
        super().__init__(parent, bg=outer_bg, highlightthickness=0, **kw)
        self._r    = radius
        self._bg   = bg
        self._bc   = border_color
        self.inner = tk.Frame(self, bg=bg, highlightthickness=0)
        self.bind("<Configure>", self._redraw)

    def _redraw(self, _=None):
        w, h = self.winfo_width(), self.winfo_height()
        if w < 4 or h < 4:
            return
        self.delete("_rp")
        _round_rect(self, 1, 1, w-1, h-1, self._r,
                    fill=self._bg, outline=self._bc, width=1, tags="_rp")
        self.tag_lower("_rp")
        p = self._r + 3
        self.inner.place(x=p, y=p, width=max(1, w-2*p), height=max(1, h-2*p))


class FlatSlider(tk.Canvas):
    """Minimal slider — a horizontal track line with a circular thumb."""

    _R = 6    # thumb radius
    _TW = 2   # track line width

    def __init__(self, parent, from_=0.0, to=1.0, variable=None,
                 command=None, bg=BG2, **kw):
        super().__init__(parent, bg=bg, highlightthickness=0, height=22, **kw)
        self._from    = from_
        self._to      = to
        self._var     = variable if variable is not None else tk.DoubleVar()
        self._command = command
        self._drag    = False

        self._var.trace_add("write", lambda *_: self.after_idle(self._draw))
        self.bind("<Configure>",       lambda _: self._draw())
        self.bind("<ButtonPress-1>",   self._on_press)
        self.bind("<B1-Motion>",       self._on_drag)
        self.bind("<ButtonRelease-1>", lambda _: setattr(self, "_drag", False))

    def _track(self):
        r = self._R
        return r + 4, self.winfo_width() - r - 4

    def _frac(self):
        span = self._to - self._from
        if not span:
            return 0.0
        return max(0.0, min(1.0, (self._var.get() - self._from) / span))

    def _draw(self):
        self.delete("all")
        w = self.winfo_width()
        if w < 4:
            return
        x0, x1 = self._track()
        cy = self.winfo_height() // 2
        f  = self._frac()
        tx = x0 + f * (x1 - x0)

        self.create_line(x0, cy, x1, cy, fill="#333333", width=self._TW)
        if tx > x0:
            self.create_line(x0, cy, tx, cy, fill=FG, width=self._TW)
        r = self._R
        self.create_oval(tx-r, cy-r, tx+r, cy+r, fill=FG, outline="")

    def _x_to_val(self, x):
        x0, x1 = self._track()
        f = (x - x0) / (x1 - x0) if x1 > x0 else 0.0
        return self._from + max(0.0, min(1.0, f)) * (self._to - self._from)

    def _on_press(self, e):
        self._drag = True
        self._apply(self._x_to_val(e.x))

    def _on_drag(self, e):
        if self._drag:
            self._apply(self._x_to_val(e.x))

    def _apply(self, val):
        self._var.set(val)
        if self._command:
            self._command(str(val))


class RoundedButton(tk.Canvas):
    """Button rendered as a rounded rectangle on a Canvas."""

    def __init__(self, parent, text="", command=None,
                 bg="#111111", fg=FG, border_color=BORDER,
                 font=F_BODY, radius=5, height=34, state=tk.NORMAL, **kw):
        try:
            outer = parent.cget("bg")
        except Exception:
            outer = BG2
        self._enabled = (state != tk.DISABLED)
        super().__init__(parent, bg=outer, highlightthickness=0,
                        cursor="hand2" if self._enabled else "",
                        height=height, **kw)
        self._text    = text
        self._command = command
        self._bg      = bg
        self._fg      = fg
        self._bc      = border_color
        self._font    = font
        self._r       = radius
        self._hover   = False

        self.bind("<Configure>",      lambda _: self._draw())
        self.bind("<ButtonPress-1>",  self._on_press)
        self.bind("<Enter>",          lambda _: self._set_hover(True))
        self.bind("<Leave>",          lambda _: self._set_hover(False))

    def _hover_fill(self):
        try:
            r, g, b = int(self._bg[1:3], 16), int(self._bg[3:5], 16), int(self._bg[5:7], 16)
            d = -25 if (r + g + b) > 384 else 25
            return f"#{max(0,min(255,r+d)):02x}{max(0,min(255,g+d)):02x}{max(0,min(255,b+d)):02x}"
        except Exception:
            return self._bg

    def _draw(self):
        self.delete("all")
        w, h = self.winfo_width(), self.winfo_height()
        if w < 2 or h < 2:
            return
        if not self._enabled:
            fill, fg, bc = "#0d0d0d", FG_DIM, "#333333"
        elif self._hover:
            fill, fg, bc = self._hover_fill(), self._fg, self._bc
        else:
            fill, fg, bc = self._bg, self._fg, self._bc
        _round_rect(self, 1, 1, w-1, h-1, self._r,
                    fill=fill, outline=bc, width=1)
        self.create_text(w//2, h//2, text=self._text, fill=fg, font=self._font)

    def _on_press(self, _):
        if self._enabled and self._command:
            self._command()

    def _set_hover(self, val):
        self._hover = val
        self._draw()

    def config(self, **kw):
        redraw = False
        for key, val in list(kw.items()):
            if key == "text":
                self._text = val;  redraw = True
            elif key == "state":
                en = (val != tk.DISABLED)
                if en != self._enabled:
                    self._enabled = en
                    super().config(cursor="hand2" if en else "")
                redraw = True
            elif key == "bg":
                self._bg = val;  redraw = True
            elif key == "fg":
                self._fg = val;  redraw = True
            elif key in ("highlightbackground", "border_color"):
                self._bc = val;  redraw = True
            else:
                super().config(**{key: val})
        if redraw:
            self._draw()

    configure = config


class RoundedEntry(tk.Canvas):
    """Entry field with a rounded-rectangle border that highlights on focus."""

    def __init__(self, parent, textvariable=None, fg=FG, bg="#111111",
                 font=F_MONO, char_width=6, justify="right", radius=4, **kw):
        try:
            outer = parent.cget("bg")
        except Exception:
            outer = BG2
        super().__init__(parent, bg=outer, highlightthickness=0,
                         height=24, width=58, **kw)
        self._radius = radius
        self._fill   = bg
        self._bc     = "#333333"

        self.inner = tk.Entry(
            self, textvariable=textvariable, fg=fg, bg=bg,
            font=font, width=char_width, justify=justify,
            relief=tk.FLAT, insertbackground=fg,
            highlightthickness=0, bd=0,
        )
        self.inner.bind("<FocusIn>",  lambda _: self._set_focus(True))
        self.inner.bind("<FocusOut>", lambda _: self._set_focus(False))
        self.bind("<Configure>", self._redraw)
        self.bind("<ButtonPress-1>", lambda _: self.inner.focus_set())

    def _set_focus(self, on):
        self._bc = BORDER if on else "#333333"
        self._redraw()

    def _redraw(self, _=None):
        w, h = self.winfo_width(), self.winfo_height()
        if w < 4 or h < 4:
            return
        self.delete("_re")
        _round_rect(self, 1, 1, w-1, h-1, self._radius,
                    fill=self._fill, outline=self._bc, width=1, tags="_re")
        self.tag_lower("_re")
        px, py = 4, 3
        self.inner.place(x=px, y=py, width=max(1, w - 2*px), height=max(1, h - 2*py))


class SliderRow(tk.Frame):
    """Labelled flat slider with an editable value field."""

    def __init__(self, parent, label, from_, to, default,
                 fmt="{:.2f}", on_change=None, **kwargs):
        super().__init__(parent, bg=BG2, highlightthickness=0, **kwargs)
        self._fmt       = fmt
        self._from      = from_
        self._to        = to
        self._on_change = on_change
        self._updating  = False

        self._var = tk.DoubleVar(value=default)

        tk.Label(
            self, text=label, fg=FG, bg=BG2,
            font=F_BODY, width=12, anchor="w",
        ).pack(side=tk.LEFT, padx=(10, 2))

        self._entry_var = tk.StringVar(value=self._fmt.format(default))
        self._entry = RoundedEntry(
            self, textvariable=self._entry_var,
            fg=FG, bg="#111111", font=F_MONO, char_width=6,
        )
        self._entry.pack(side=tk.RIGHT, padx=(2, 10))
        self._entry.inner.bind("<Return>",   self._commit)
        self._entry.inner.bind("<FocusOut>", self._commit)
        self._entry.inner.bind("<Escape>",   self._revert)

        self._slider = FlatSlider(
            self, from_=from_, to=to, variable=self._var,
            command=self._slide, bg=BG2,
        )
        self._slider.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(4, 4))

    def _slide(self, _=None):
        if self._updating:
            return
        self._entry_var.set(self._fmt.format(self._var.get()))
        if self._on_change:
            self._on_change()

    def _commit(self, _=None):
        raw = self._entry_var.get().strip()
        try:
            v = float(raw)
        except ValueError:
            self._revert()
            return
        v = max(self._from, min(self._to, v))
        self._updating = True
        self._var.set(v)
        self._entry_var.set(self._fmt.format(v))
        self._updating = False
        if self._on_change:
            self._on_change()

    def _revert(self, _=None):
        self._entry_var.set(self._fmt.format(self._var.get()))

    def get(self) -> float:
        return self._var.get()

    def set(self, value: float):
        self._var.set(value)
        self._entry_var.set(self._fmt.format(value))
