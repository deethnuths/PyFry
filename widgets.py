import tkinter as tk
from tkinter import ttk

# ── Colour palette ─────────────────────────────────────────────────────────────
BG      = "#24273a"  # Catppuccin Macchiato — Base
BG2     = "#1e2030"  # Mantle
BG3     = "#363a4f"  # Surface0
ACCENT  = "#ed8796"  # Red
ACCENT2 = "#181926"  # Crust
FG      = "#cad3f5"  # Text
FG_DIM  = "#8087a2"  # Overlay1
ORANGE  = "#f5a97f"  # Peach


class SliderRow(tk.Frame):
    """Labelled horizontal slider with editable value field."""

    def __init__(self, parent, label, from_, to, default,
                 fmt="{:.2f}", on_change=None, **kwargs):
        super().__init__(parent, bg=BG2, **kwargs)
        self._fmt = fmt
        self._from = from_
        self._to = to
        self._on_change = on_change
        self._updating = False   # guard against recursive trace/slide callbacks

        self._var = tk.DoubleVar(value=default)

        tk.Label(
            self, text=label, fg=FG, bg=BG2,
            font=("Segoe UI", 9, "bold"), width=13, anchor="w",
        ).pack(side=tk.LEFT, padx=(10, 2))

        self._entry_var = tk.StringVar(value=self._fmt.format(default))
        self._entry = tk.Entry(
            self, textvariable=self._entry_var, fg=ACCENT, bg="#181926",
            font=("Consolas", 9, "bold"), width=6, justify="right",
            relief=tk.FLAT, insertbackground=ACCENT,
            highlightthickness=1, highlightcolor=ACCENT,
            highlightbackground="#363a4f",
            disabledforeground=FG_DIM,
        )
        self._entry.pack(side=tk.RIGHT, padx=(2, 10))
        self._entry.bind("<Return>",   self._commit)
        self._entry.bind("<FocusOut>", self._commit)
        self._entry.bind("<Escape>",   self._revert)

        self._slider = ttk.Scale(
            self, from_=from_, to=to, variable=self._var,
            orient=tk.HORIZONTAL, command=self._slide,
        )
        self._slider.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=4)

    def _slide(self, _=None):
        if self._updating:
            return
        v = self._var.get()
        self._entry_var.set(self._fmt.format(v))
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
