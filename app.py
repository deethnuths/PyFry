import io
import os
import shutil
import subprocess
import tempfile
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import tkinter as tk
from tkinter import ttk, filedialog, messagebox

import numpy as np
from PIL import Image, ImageTk

from effects import (
    apply_deep_fry, apply_deep_fry_cv2, distort_audio,
    IMAGE_EXTS, VIDEO_EXTS,
    HAS_CV2, HAS_MOVIEPY,
    _N_WORKERS,
)
from widgets import (
    SliderRow, RoundedPanel, RoundedButton,
    BG, BG2, BG3, ACCENT, ACCENT2, FG, FG_DIM, ORANGE, BORDER,
    F_BODY, F_SMALL, F_TITLE, F_HEAD, F_BIG,
)

# ── Optional drag-and-drop ─────────────────────────────────────────────────────
DND_FILES = None
TkinterDnD = None
HAS_DND = False
try:
    from tkinterdnd2 import DND_FILES, TkinterDnD
    HAS_DND = True
except ImportError:
    pass


class PyFryApp:
    PREVIEW_DELAY_MS = 90   # debounce delay for live preview

    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title("PyFry")
        self.root.geometry("1140x720")
        self.root.minsize(820, 560)
        self.root.configure(bg=BG)

        self._source: Image.Image | None = None
        self._source_path: str | None = None
        self._is_video: bool = False
        self._is_gif: bool = False
        self._gif_frames: list = []
        self._gif_durations: list = []
        self._gif_processed: list = []
        self._anim_idx: int = 0
        self._anim_job = None
        self._copy_tmp: str | None = None
        self._last_video_output: str | None = None
        self._tk_img = None
        self._full_img: Image.Image | None = None
        self._zoom: float = 1.0
        self._pan_x: int = 0
        self._pan_y: int = 0
        self._drag_start: tuple | None = None
        self._preview_job = None
        self._processing = False
        self._cancel_flag = threading.Event()

        self._build_ui()
        self._bind_events()

    # ── UI construction ────────────────────────────────────────────────────────
    def _build_ui(self):
        self._build_topbar()

        body = tk.Frame(self.root, bg=BG)
        body.pack(fill=tk.BOTH, expand=True, padx=10, pady=(6, 10))

        self._build_preview(body)
        self._build_controls(body)

    def _build_topbar(self):
        bar = tk.Frame(self.root, bg=ACCENT2, height=50)
        bar.pack(fill=tk.X)
        bar.pack_propagate(False)

        tk.Label(
            bar, text="🔥  PYFRY", fg=FG, bg=ACCENT2,
            font=F_TITLE,
        ).pack(side=tk.LEFT, padx=18)

        missing = []
        if not HAS_DND:     missing.append("tkinterdnd2")
        if not HAS_CV2:     missing.append("opencv-python")
        if not HAS_MOVIEPY: missing.append("moviepy")
        if missing:
            tk.Label(
                bar, text=f"pip install {' '.join(missing)}",
                fg=FG_DIM, bg=ACCENT2, font=F_SMALL,
            ).pack(side=tk.RIGHT, padx=8)

    def _build_preview(self, parent):
        panel = RoundedPanel(parent, radius=8, bg=BG3, outer_bg=BG)
        panel.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(0, 6))

        self._canvas = tk.Canvas(panel.inner, bg=BG, highlightthickness=0,
                                  cursor="hand2")
        self._canvas.pack(fill=tk.BOTH, expand=True, padx=2, pady=2)
        self._canvas.bind("<Double-Button-1>", lambda _: self._open_file())
        self._canvas.bind("<Configure>", self._on_canvas_resize)

        self._status_var = tk.StringVar(
            value="Drop an image or video here  •  Ctrl+V to paste  •  double-click to open")
        tk.Label(
            panel.inner, textvariable=self._status_var, fg=FG_DIM, bg=BG3,
            font=F_SMALL, anchor="w",
        ).pack(fill=tk.X, padx=8, pady=(0, 4))

        self._draw_hint()

    def _build_controls(self, parent):
        panel = RoundedPanel(parent, radius=8, bg=BG2, outer_bg=BG, width=308)
        panel.pack(side=tk.RIGHT, fill=tk.Y)
        ctrl = panel.inner

        tk.Label(ctrl, text="EFFECTS", fg=FG, bg=BG2,
                 font=F_HEAD).pack(pady=(16, 6))

        def _sep():
            ttk.Separator(ctrl, orient=tk.HORIZONTAL).pack(fill=tk.X, padx=12, pady=8)

        upd = self._schedule_preview

        self._sl_brightness = SliderRow(ctrl, "Brightness", 0.1, 6.0, 1.0, on_change=upd)
        self._sl_brightness.pack(fill=tk.X, padx=4, pady=2)

        self._sl_contrast   = SliderRow(ctrl, "Contrast",   0.1, 6.0, 1.0, on_change=upd)
        self._sl_contrast.pack(fill=tk.X, padx=4, pady=2)

        self._sl_sharpness  = SliderRow(ctrl, "Sharpness",  0.0, 25.0, 1.0, on_change=upd)
        self._sl_sharpness.pack(fill=tk.X, padx=4, pady=2)

        self._sl_saturation = SliderRow(ctrl, "Saturation", 0.0, 10.0, 1.0, on_change=upd)
        self._sl_saturation.pack(fill=tk.X, padx=4, pady=2)

        self._sl_noise      = SliderRow(ctrl, "Noise",      0.0,  1.0, 0.0, on_change=upd)
        self._sl_noise.pack(fill=tk.X, padx=4, pady=2)

        self._sl_jpeg = SliderRow(
            ctrl, "JPEG Crush", 95, 1, 85,
            fmt="{:.0f}", on_change=upd,
        )
        self._sl_jpeg.pack(fill=tk.X, padx=4, pady=2)

        self._sl_audio = SliderRow(ctrl, "Audio Crush", 0.0, 1.0, 0.0)
        self._sl_audio.pack(fill=tk.X, padx=4, pady=2)
        tk.Label(ctrl, text="↑ video only", fg=FG_DIM, bg=BG2,
                 font=F_SMALL).pack(anchor="e", padx=14)

        _sep()

        tk.Label(ctrl, text="PRESETS", fg=FG, bg=BG2,
                 font=F_HEAD).pack(pady=(0, 6))

        def _pbtn(par, text, color, cmd):
            RoundedButton(
                par, text=text, command=cmd,
                bg=color, fg="white", border_color=color,
                font=F_SMALL, radius=4, height=28, width=1,
            ).pack(side=tk.LEFT, fill=tk.X, expand=True, padx=2)

        row1 = tk.Frame(ctrl, bg=BG2)
        row1.pack(fill=tk.X, padx=8, pady=(0, 2))
        _pbtn(row1, "RESET",  "#1a1a1a",  self._preset_reset)
        _pbtn(row1, "WARM",   "#3d7a62",  self._preset_warm)
        _pbtn(row1, "TOASTY", "#7a6228",  self._preset_toasty)

        row2 = tk.Frame(ctrl, bg=BG2)
        row2.pack(fill=tk.X, padx=8, pady=(0, 4))
        _pbtn(row2, "SPICY",  "#8a3840",  self._preset_spicy)
        _pbtn(row2, "CRISPY", ORANGE,     self._preset_crispy)
        _pbtn(row2, "NUKED",  ACCENT,     self._preset_nuked)

        RoundedButton(
            ctrl, text="RANDOMIZE", command=self._randomize,
            bg="#111111", fg=FG, border_color=BORDER,
            font=F_BODY, radius=4, height=30,
        ).pack(fill=tk.X, padx=8, pady=(0, 2))

        _sep()

        self._prog_var = tk.DoubleVar(value=0)
        self._progbar = ttk.Progressbar(
            ctrl, variable=self._prog_var, maximum=100, mode="determinate",
        )
        self._progbar.pack(fill=tk.X, padx=14, pady=(0, 4))

        self._prog_lbl = tk.Label(ctrl, text="", fg=FG_DIM, bg=BG2, font=F_SMALL)
        self._prog_lbl.pack()

        self._cancel_btn = RoundedButton(
            ctrl, text="CANCEL", command=self._cancel_video,
            bg="#200808", fg="white", border_color="#883333",
            font=F_BODY, radius=4, height=30,
        )
        # not packed yet — appears only while processing

        self._save_btn = RoundedButton(
            ctrl, text="SAVE / EXPORT", command=self._save,
            bg=FG, fg="#000000", border_color=FG,
            font=F_BIG, radius=4, height=44,
        )
        self._save_btn.pack(fill=tk.X, padx=14, pady=(4, 6), side=tk.BOTTOM)

        self._copy_btn = RoundedButton(
            ctrl, text="COPY TO CLIPBOARD", command=self._copy_to_clipboard,
            bg=BG2, fg=FG, border_color=BORDER,
            font=F_BODY, radius=4, height=36,
        )
        self._copy_btn.pack(fill=tk.X, padx=14, pady=(10, 0), side=tk.BOTTOM)

        self._fry_again_btn = RoundedButton(
            ctrl, text="FRY AGAIN", command=self._fry_again,
            bg=BG2, fg=ORANGE, border_color=ORANGE,
            font=F_BODY, radius=4, height=36,
        )
        self._fry_again_btn.pack(fill=tk.X, padx=14, pady=(4, 0), side=tk.BOTTOM)

        self._vid_render_btn = RoundedButton(
            ctrl, text="RENDER", command=self._render_video,
            bg=FG, fg="#000000", border_color=FG,
            font=F_BIG, radius=4, height=44,
        )
        # not packed yet

        self._vid_action_row = tk.Frame(ctrl, bg=BG2)
        self._vid_copy_btn = RoundedButton(
            self._vid_action_row, text="COPY", command=self._copy_rendered_video,
            bg=BG2, fg=FG_DIM, border_color="#333333",
            font=F_BODY, radius=4, height=36, width=1, state=tk.DISABLED,
        )
        self._vid_copy_btn.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 3))
        self._vid_save_btn = RoundedButton(
            self._vid_action_row, text="SAVE", command=self._save_rendered_video,
            bg=BG2, fg=FG_DIM, border_color="#333333",
            font=F_BODY, radius=4, height=36, width=1, state=tk.DISABLED,
        )
        self._vid_save_btn.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(3, 0))
        # not packed yet

    def _refresh_button_labels(self):
        if self._is_video:
            self._last_video_output = None
            self._save_btn.pack_forget()
            self._copy_btn.pack_forget()
            self._fry_again_btn.pack_forget()
            self._vid_render_btn.pack(fill=tk.X, padx=16, pady=(4, 6), side=tk.BOTTOM)
            self._vid_action_row.pack(fill=tk.X, padx=16, pady=(8, 0), side=tk.BOTTOM)
            self._vid_copy_btn.config(state=tk.DISABLED, bg=BG2, fg=FG_DIM, highlightbackground="#333333")
            self._vid_save_btn.config(state=tk.DISABLED, bg=BG2, fg=FG_DIM, highlightbackground="#333333")
        else:
            self._vid_render_btn.pack_forget()
            self._vid_action_row.pack_forget()
            self._save_btn.pack(fill=tk.X, padx=16, pady=(4, 6), side=tk.BOTTOM)
            self._copy_btn.pack(fill=tk.X, padx=16, pady=(12, 0), side=tk.BOTTOM)
            self._fry_again_btn.pack(fill=tk.X, padx=16, pady=(4, 0), side=tk.BOTTOM)

    # ── Hint overlay ──────────────────────────────────────────────────────────
    def _draw_hint(self):
        self._canvas.delete("hint")
        w = max(self._canvas.winfo_width(), 100)
        h = max(self._canvas.winfo_height(), 100)
        cx, cy = w // 2, h // 2
        self._canvas.create_text(cx, cy - 30, text="🔥", font=("Cascadia Code", 48),
                                  tags="hint")
        self._canvas.create_text(cx, cy + 42, text="Drop image or video here",
                                  fill=FG_DIM, font=("Cascadia Code", 12), tags="hint")
        self._canvas.create_text(cx, cy + 66, text="Ctrl+V  •  double-click to open",
                                  fill=FG_DIM, font=("Cascadia Code", 8), tags="hint")

    # ── Event binding ──────────────────────────────────────────────────────────
    def _bind_events(self):
        self.root.bind("<Control-v>", self._paste)
        self.root.bind("<Control-V>", self._paste)
        self._canvas.bind("<Configure>", self._on_canvas_resize)
        self._canvas.bind("<ButtonPress-1>",   self._on_drag_start)
        self._canvas.bind("<B1-Motion>",        self._on_drag)
        self._canvas.bind("<ButtonRelease-1>",  self._on_drag_end)
        self._canvas.bind("<MouseWheel>",        self._on_zoom)   # Windows
        self._canvas.bind("<Button-4>",          self._on_zoom)   # Linux scroll up
        self._canvas.bind("<Button-5>",          self._on_zoom)   # Linux scroll down
        self._canvas.bind("<ButtonPress-3>",     self._reset_view) # right-click resets

        self._canvas.tag_bind("reset_btn", "<ButtonPress-1>", self._reset_view)
        self._canvas.tag_bind("reset_btn", "<Enter>",
            lambda _: self._canvas.itemconfig("reset_btn_bg", fill="#222222"))
        self._canvas.tag_bind("reset_btn", "<Leave>",
            lambda _: self._canvas.itemconfig("reset_btn_bg", fill="#111111"))

        self._canvas.tag_bind("clear_btn", "<ButtonPress-1>", lambda _: self._clear())
        self._canvas.tag_bind("clear_btn", "<Enter>",
            lambda _: self._canvas.itemconfig("clear_btn_bg", fill="#2a1111"))
        self._canvas.tag_bind("clear_btn", "<Leave>",
            lambda _: self._canvas.itemconfig("clear_btn_bg", fill="#111111"))

        if HAS_DND:
            self._canvas.drop_target_register(DND_FILES)
            self._canvas.dnd_bind("<<Drop>>",      self._on_drop)
            self._canvas.dnd_bind("<<DragEnter>>",
                lambda _: self._canvas.config(bg="#151515"))
            self._canvas.dnd_bind("<<DragLeave>>",
                lambda _: self._canvas.config(bg=BG))

    def _on_canvas_resize(self, _event):
        if self._source is None:
            self._draw_hint()
        elif self._full_img is not None:
            self._render_view()
        else:
            self._update_preview()

    # ── Pan / zoom ─────────────────────────────────────────────────────────────
    def _on_drag_start(self, event):
        if self._full_img is None:
            return
        # Don't start a drag when clicking the reset-view overlay button
        hit = self._canvas.find_overlapping(event.x - 1, event.y - 1, event.x + 1, event.y + 1)
        if any(t in self._canvas.gettags(i) for i in hit for t in ("reset_btn", "clear_btn")):
            return
        self._drag_start = (event.x, event.y)
        self._canvas.config(cursor="fleur")

    def _on_drag(self, event):
        if self._drag_start is None:
            return
        self._pan_x += event.x - self._drag_start[0]
        self._pan_y += event.y - self._drag_start[1]
        self._drag_start = (event.x, event.y)
        self._render_view()

    def _on_drag_end(self, _event):
        self._drag_start = None
        if self._full_img is not None:
            self._canvas.config(cursor="hand2")

    def _on_zoom(self, event):
        if self._full_img is None:
            return
        factor = 1.15 if (getattr(event, "delta", 0) > 0 or event.num == 4) else 1 / 1.15
        new_zoom = max(0.1, min(20.0, self._zoom * factor))
        if new_zoom == self._zoom:
            return
        cw = self._canvas.winfo_width()
        ch = self._canvas.winfo_height()
        ratio = new_zoom / self._zoom
        qx = event.x - cw // 2
        qy = event.y - ch // 2
        self._pan_x = int((self._pan_x - qx) * ratio + qx)
        self._pan_y = int((self._pan_y - qy) * ratio + qy)
        self._zoom = new_zoom
        self._render_view()

    def _reset_view(self, _event=None):
        self._zoom = 1.0
        self._pan_x = 0
        self._pan_y = 0
        self._render_view()

    def _update_overlay_btns(self):
        self._canvas.delete("reset_btn")
        self._canvas.delete("clear_btn")

        cw  = self._canvas.winfo_width()
        pad = 8
        sz  = 24
        gap = 4

        # Clear button — always visible when an image is loaded
        if self._source is not None:
            cx1 = cw - pad - sz
            cy1 = pad
            cx2 = cw - pad
            cy2 = pad + sz
            self._canvas.create_rectangle(
                cx1, cy1, cx2, cy2,
                fill="#111111", outline="#333333", width=1,
                stipple="gray75",
                tags=("clear_btn", "clear_btn_bg"),
            )
            m = 7
            self._canvas.create_line(cx1+m, cy1+m, cx2-m, cy2-m,
                                      fill=FG_DIM, width=1.5, tags="clear_btn")
            self._canvas.create_line(cx2-m, cy1+m, cx1+m, cy2-m,
                                      fill=FG_DIM, width=1.5, tags="clear_btn")

        # Fit/reset-view button — visible when zoomed or panned
        if not (self._zoom == 1.0 and self._pan_x == 0 and self._pan_y == 0):
            offset = sz + gap if self._source is not None else 0
            x1 = cw - pad - sz - offset
            y1 = pad
            x2 = cw - pad - offset
            y2 = pad + sz
            self._canvas.create_rectangle(
                x1, y1, x2, y2,
                fill="#111111", outline="#333333", width=1,
                stipple="gray75",
                tags=("reset_btn", "reset_btn_bg"),
            )
            m = 5
            a = 5
            ix1, iy1 = x1 + m, y1 + m
            ix2, iy2 = x2 - m, y2 - m
            kw = dict(fill=FG_DIM, width=1.5, tags=("reset_btn",))
            self._canvas.create_line(ix1, iy1 + a, ix1, iy1, ix1 + a, iy1, **kw)
            self._canvas.create_line(ix2 - a, iy1, ix2, iy1, ix2, iy1 + a, **kw)
            self._canvas.create_line(ix1, iy2 - a, ix1, iy2, ix1 + a, iy2, **kw)
            self._canvas.create_line(ix2 - a, iy2, ix2, iy2, ix2, iy2 - a, **kw)

    # ── File loading ───────────────────────────────────────────────────────────
    def _on_drop(self, event):
        self._canvas.config(bg=BG)
        raw = event.data.strip()
        paths = self.root.tk.splitlist(raw)
        if paths:
            self._load_path(paths[0])

    def _open_file(self):
        path = filedialog.askopenfilename(filetypes=[
            ("All supported",
             "*.jpg *.jpeg *.png *.bmp *.gif *.tiff *.webp "
             "*.mp4 *.avi *.mov *.mkv *.webm *.flv"),
            ("Images", "*.jpg *.jpeg *.png *.bmp *.gif *.tiff *.webp"),
            ("Videos", "*.mp4 *.avi *.mov *.mkv *.webm *.flv"),
            ("All files", "*.*"),
        ])
        if path:
            self._load_path(path)

    def _clear(self):
        self._stop_animation()
        self._source = None
        self._source_path = None
        self._is_video = False
        self._is_gif = False
        self._gif_frames = []
        self._gif_durations = []
        self._gif_processed = []
        self._last_video_output = None
        self._tk_img = None
        self._full_img = None
        self._zoom = 1.0
        self._pan_x = 0
        self._pan_y = 0
        self._status_var.set("Drop an image or video here  •  Ctrl+V to paste  •  double-click to open")
        self._canvas.delete("all")
        self._draw_hint()
        self._refresh_button_labels()

    def _paste(self, _event=None):
        try:
            from PIL import ImageGrab
            cb = ImageGrab.grabclipboard()
            if isinstance(cb, Image.Image):
                self._stop_animation()
                self._is_gif = False
                self._gif_frames = []
                self._source = cb.convert("RGB")
                self._source_path = None
                self._is_video = False
                self._zoom = 1.0; self._pan_x = 0; self._pan_y = 0
                size = self._source.size
                self._status_var.set(f"Pasted from clipboard — {size[0]}×{size[1]}")
                self._update_preview()
                self._refresh_button_labels()
                return
            if isinstance(cb, list) and cb:
                self._load_path(cb[0])
                return
        except Exception:
            pass
        try:
            text = self.root.clipboard_get().strip()
            if os.path.exists(text):
                self._load_path(text)
        except Exception:
            pass

    def _load_path(self, path: str):
        path = path.strip()
        if not os.path.exists(path):
            messagebox.showerror("Error", f"File not found:\n{path}")
            return

        ext = Path(path).suffix.lower()

        if ext in IMAGE_EXTS:
            try:
                img = Image.open(path)
                n_frames = getattr(img, "n_frames", 1)
                if ext == ".gif" and n_frames > 1:
                    from PIL import ImageSequence
                    frames, durations = [], []
                    for frame in ImageSequence.Iterator(img):
                        frames.append(frame.convert("RGB"))
                        durations.append(frame.info.get("duration", 100))
                    self._gif_frames    = frames
                    self._gif_durations = durations
                    self._gif_processed = []
                    self._source        = frames[0]
                    self._source_path   = path
                    self._is_video      = False
                    self._is_gif        = True
                    self._zoom = 1.0; self._pan_x = 0; self._pan_y = 0
                    w, h = self._source.size
                    self._status_var.set(
                        f"GIF: {os.path.basename(path)}  —  {w}×{h}  "
                        f"({n_frames} frames)")
                    self._update_preview()
                    self._refresh_button_labels()
                else:
                    self._stop_animation()
                    self._is_gif = False
                    self._gif_frames = []
                    self._source = img.convert("RGB")
                    self._source_path = path
                    self._is_video = False
                    self._zoom = 1.0; self._pan_x = 0; self._pan_y = 0
                    w, h = self._source.size
                    self._status_var.set(f"{os.path.basename(path)}  —  {w}×{h}")
                    self._update_preview()
                    self._refresh_button_labels()
            except Exception as exc:
                messagebox.showerror("Cannot open image", str(exc))

        elif ext in VIDEO_EXTS:
            if not HAS_CV2:
                messagebox.showerror(
                    "Missing dependency",
                    "Install opencv-python for video support:\n\n"
                    "    pip install opencv-python",
                )
                return
            try:
                import cv2
                cap = cv2.VideoCapture(path)
                ret, frame = cap.read()
                cap.release()
                if not ret:
                    raise RuntimeError("Could not read first frame.")
                self._source = Image.fromarray(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB))
                self._source_path = path
                self._is_video = True
                self._zoom = 1.0; self._pan_x = 0; self._pan_y = 0
                self._status_var.set(
                    f"Video: {os.path.basename(path)}  (preview = first frame)")
                self._update_preview()
                self._refresh_button_labels()
            except Exception as exc:
                messagebox.showerror("Cannot open video", str(exc))

        else:
            messagebox.showwarning("Unsupported", f"Unsupported file type: {ext}")

    # ── Preview ────────────────────────────────────────────────────────────────
    def _schedule_preview(self):
        if self._preview_job:
            self.root.after_cancel(self._preview_job)
        self._preview_job = self.root.after(self.PREVIEW_DELAY_MS, self._update_preview)

    def _update_preview(self):
        if self._source is None:
            return
        if self._is_gif and self._gif_frames:
            self._stop_animation()
            self._gif_processed = [self._effects(f) for f in self._gif_frames]
            self._anim_idx = 0
            self._tick_animation()
        else:
            self._show_frame(self._effects(self._source))

    def _show_frame(self, img: Image.Image):
        self._full_img = img
        self._render_view()

    def _render_view(self):
        img = self._full_img
        if img is None:
            return
        cw = max(self._canvas.winfo_width(), 80)
        ch = max(self._canvas.winfo_height(), 80)
        iw, ih = img.size

        fit_scale  = min(cw / iw, ch / ih)
        disp_scale = fit_scale * self._zoom
        disp_w = max(1, int(iw * disp_scale))
        disp_h = max(1, int(ih * disp_scale))

        # image center on canvas (offset by pan)
        cx = cw // 2 + self._pan_x
        cy = ch // 2 + self._pan_y
        img_l_canvas = cx - disp_w // 2
        img_t_canvas = cy - disp_h // 2

        # clip to canvas bounds
        vis_l = max(0, img_l_canvas)
        vis_t = max(0, img_t_canvas)
        vis_r = min(cw, img_l_canvas + disp_w)
        vis_b = min(ch, img_t_canvas + disp_h)

        if vis_r <= vis_l or vis_b <= vis_t:
            self._canvas.delete("all")
            self._update_overlay_btns()
            return

        # map visible canvas region back to original image pixels
        img_crop_l = max(0, int((vis_l - img_l_canvas) / disp_scale))
        img_crop_t = max(0, int((vis_t - img_t_canvas) / disp_scale))
        img_crop_r = min(iw, int((vis_r - img_l_canvas) / disp_scale) + 1)
        img_crop_b = min(ih, int((vis_b - img_t_canvas) / disp_scale) + 1)

        tile = img.crop((img_crop_l, img_crop_t, img_crop_r, img_crop_b))
        tile = tile.resize((vis_r - vis_l, vis_b - vis_t), Image.LANCZOS)

        self._tk_img = ImageTk.PhotoImage(tile)
        self._canvas.delete("all")
        self._canvas.create_image(vis_l, vis_t, anchor=tk.NW, image=self._tk_img)
        self._update_overlay_btns()

    # ── GIF animation ──────────────────────────────────────────────────────────
    def _tick_animation(self):
        if not self._gif_processed:
            return
        idx = self._anim_idx % len(self._gif_processed)
        self._show_frame(self._gif_processed[idx])
        delay = max(20, self._gif_durations[idx] if self._gif_durations else 100)
        self._anim_idx = (idx + 1) % len(self._gif_processed)
        self._anim_job = self.root.after(delay, self._tick_animation)

    def _stop_animation(self):
        if self._anim_job:
            self.root.after_cancel(self._anim_job)
            self._anim_job = None

    # ── Effects helper ─────────────────────────────────────────────────────────
    def _effects(self, img: Image.Image) -> Image.Image:
        return apply_deep_fry(
            img,
            brightness   = self._sl_brightness.get(),
            contrast     = self._sl_contrast.get(),
            sharpness    = self._sl_sharpness.get(),
            saturation   = self._sl_saturation.get(),
            noise        = self._sl_noise.get(),
            jpeg_quality = int(self._sl_jpeg.get()),
        )

    # ── Presets ────────────────────────────────────────────────────────────────
    def _preset_reset(self):
        self._sl_brightness.set(1.0)
        self._sl_contrast.set(1.0)
        self._sl_sharpness.set(1.0)
        self._sl_saturation.set(1.0)
        self._sl_noise.set(0.0)
        self._sl_jpeg.set(85)
        self._sl_audio.set(0.0)
        self._update_preview()

    def _preset_crispy(self):
        self._sl_brightness.set(1.5)
        self._sl_contrast.set(2.8)
        self._sl_sharpness.set(9.0)
        self._sl_saturation.set(3.5)
        self._sl_noise.set(0.18)
        self._sl_jpeg.set(18)
        self._sl_audio.set(0.35)
        self._update_preview()

    def _preset_nuked(self):
        self._sl_brightness.set(2.2)
        self._sl_contrast.set(5.5)
        self._sl_sharpness.set(22.0)
        self._sl_saturation.set(9.0)
        self._sl_noise.set(0.75)
        self._sl_jpeg.set(2)
        self._sl_audio.set(0.95)
        self._update_preview()

    def _preset_warm(self):
        self._sl_brightness.set(1.15)
        self._sl_contrast.set(1.3)
        self._sl_sharpness.set(2.0)
        self._sl_saturation.set(1.2)
        self._sl_noise.set(0.03)
        self._sl_jpeg.set(75)
        self._sl_audio.set(0.0)
        self._update_preview()

    def _preset_toasty(self):
        self._sl_brightness.set(1.25)
        self._sl_contrast.set(1.9)
        self._sl_sharpness.set(5.0)
        self._sl_saturation.set(1.7)
        self._sl_noise.set(0.08)
        self._sl_jpeg.set(48)
        self._sl_audio.set(0.0)
        self._update_preview()

    def _preset_spicy(self):
        self._sl_brightness.set(1.38)
        self._sl_contrast.set(2.3)
        self._sl_sharpness.set(7.0)
        self._sl_saturation.set(2.2)
        self._sl_noise.set(0.13)
        self._sl_jpeg.set(28)
        self._sl_audio.set(0.15)
        self._update_preview()

    def _fry_again(self):
        if self._source is None:
            return
        if self._is_gif and self._gif_frames:
            frames = self._gif_processed if self._gif_processed else [self._effects(f) for f in self._gif_frames]
            self._gif_frames = [f.copy() for f in frames]
            self._gif_processed = []
            self._source = self._gif_frames[0]
        else:
            self._source = self._effects(self._source)
        self._zoom = 1.0
        self._pan_x = 0
        self._pan_y = 0
        self._status_var.set("Fried again — effects baked into source")
        self._update_preview()

    def _randomize(self):
        self._sl_brightness.set(round(float(np.random.uniform(1.0, 2.5)), 2))
        self._sl_contrast.set(round(float(np.random.uniform(1.0, 4.5)), 2))
        self._sl_sharpness.set(round(float(np.random.uniform(0.5, 16.0)), 2))
        self._sl_saturation.set(round(float(np.random.uniform(1.0, 7.0)), 2))
        self._sl_noise.set(round(float(np.random.uniform(0.0, 0.55)), 2))
        self._sl_jpeg.set(int(np.random.randint(4, 65)))
        self._sl_audio.set(round(float(np.random.uniform(0.0, 0.8)), 2))
        self._update_preview()

    # ── Copy to clipboard ──────────────────────────────────────────────────────
    def _copy_to_clipboard(self):
        if self._source is None:
            messagebox.showwarning("Nothing to copy", "Load an image first.")
            return
        if self._is_video:
            if not self._last_video_output or not os.path.exists(self._last_video_output):
                self._status_var.set("Render & Save the video first, then copy.")
                return
            self._put_file_on_clipboard(self._last_video_output)
            return

        if self._is_gif and self._gif_frames:
            self._copy_gif_to_clipboard()
            return

        self._copy_image_to_clipboard(self._effects(self._source))

    def _copy_image_to_clipboard(self, processed: Image.Image):
        try:
            import win32clipboard  # type: ignore
            buf = io.BytesIO()
            processed.save(buf, format="BMP")
            data = buf.getvalue()[14:]
            win32clipboard.OpenClipboard()
            win32clipboard.EmptyClipboard()
            win32clipboard.SetClipboardData(win32clipboard.CF_DIB, data)
            win32clipboard.CloseClipboard()
            self._flash_copy_btn()
            return
        except ImportError:
            pass
        except Exception as exc:
            self._status_var.set(f"Clipboard error: {exc}")
            return

        try:
            with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as f:
                tmp = f.name
            processed.save(tmp)
            script = (
                "Add-Type -AssemblyName System.Windows.Forms;"
                "Add-Type -AssemblyName System.Drawing;"
                f'[System.Windows.Forms.Clipboard]::SetImage('
                f'[System.Drawing.Image]::FromFile("{tmp}"))'
            )
            subprocess.run(
                ["powershell", "-NoProfile", "-Command", script],
                check=True, capture_output=True,
            )
            os.unlink(tmp)
            self._flash_copy_btn()
        except Exception as exc:
            self._status_var.set(f"Copy failed: {exc}")

    def _copy_gif_to_clipboard(self):
        try:
            if self._copy_tmp and os.path.exists(self._copy_tmp):
                try:
                    os.unlink(self._copy_tmp)
                except OSError:
                    pass

            frames = self._gif_processed or [self._effects(f) for f in self._gif_frames]
            with tempfile.NamedTemporaryFile(suffix=".gif", delete=False) as f:
                tmp = f.name
            frames[0].save(
                tmp, format="GIF", save_all=True,
                append_images=frames[1:],
                loop=0, duration=self._gif_durations, optimize=False,
            )
            self._copy_tmp = tmp

            script = (
                "Add-Type -AssemblyName System.Windows.Forms;"
                "Add-Type -AssemblyName System.Collections.Specialized;"
                "$col = New-Object System.Collections.Specialized.StringCollection;"
                f'$col.Add("{tmp}");'
                "[System.Windows.Forms.Clipboard]::SetFileDropList($col)"
            )
            subprocess.run(
                ["powershell", "-NoProfile", "-Command", script],
                check=True, capture_output=True,
            )
            self._flash_copy_btn("GIF COPIED!")
        except Exception as exc:
            self._status_var.set(f"GIF copy failed: {exc}")

    def _flash_copy_btn(self, label: str = "COPIED!"):
        self._copy_btn.config(bg="#0a1a10", text=label)
        self._status_var.set("Copied to clipboard")
        self.root.after(1400, lambda: self._copy_btn.config(
            bg=BG2, text="COPY TO CLIPBOARD"))

    # ── Save / Export ──────────────────────────────────────────────────────────
    def _save(self):
        if self._source is None:
            messagebox.showwarning("Nothing to save", "Load an image or video first.")
            return
        if self._processing:
            messagebox.showinfo("Busy", "Video processing is already running.")
            return
        if self._is_video:
            self._export_video()
        elif self._is_gif:
            self._export_gif()
        else:
            self._export_image()

    def _export_gif(self):
        src_name = Path(self._source_path).stem if self._source_path else "image"
        path = filedialog.asksaveasfilename(
            defaultextension=".gif",
            initialfile=f"{src_name}_fried",
            filetypes=[("GIF", "*.gif"), ("All files", "*.*")],
        )
        if not path:
            return
        try:
            frames = self._gif_processed or [self._effects(f) for f in self._gif_frames]
            frames[0].save(
                path, format="GIF", save_all=True,
                append_images=frames[1:],
                loop=0, duration=self._gif_durations, optimize=False,
            )
            self._status_var.set(f"Saved: {os.path.basename(path)}")
        except Exception as exc:
            messagebox.showerror("Save failed", str(exc))

    def _export_image(self):
        src_name = Path(self._source_path).stem if self._source_path else "image"
        path = filedialog.asksaveasfilename(
            defaultextension=".jpg",
            initialfile=f"{src_name}_fried",
            filetypes=[("JPEG", "*.jpg"), ("PNG", "*.png"), ("All files", "*.*")],
        )
        if not path:
            return
        try:
            result = self._effects(self._source)
            result.save(path)
            self._status_var.set(f"Saved: {os.path.basename(path)}")
        except Exception as exc:
            messagebox.showerror("Save failed", str(exc))

    def _export_video(self):
        pass  # replaced by _render_video / _save_rendered_video

    def _render_video(self):
        if not HAS_CV2:
            messagebox.showerror("Missing dependency",
                                  "Install opencv-python for video rendering.")
            return
        tmp = tempfile.NamedTemporaryFile(suffix=".mp4", delete=False).name
        self._start_video_processing(tmp)

    def _copy_rendered_video(self):
        if self._last_video_output and os.path.exists(self._last_video_output):
            self._put_file_on_clipboard(self._last_video_output)
        else:
            self._status_var.set("Render the video first.")

    def _save_rendered_video(self):
        if not self._last_video_output or not os.path.exists(self._last_video_output):
            self._status_var.set("Render the video first.")
            return
        src_name = Path(self._source_path).stem
        path = filedialog.asksaveasfilename(
            defaultextension=".mp4",
            initialfile=f"{src_name}_fried",
            filetypes=[("MP4", "*.mp4"), ("AVI", "*.avi"), ("All files", "*.*")],
        )
        if not path:
            return
        try:
            shutil.copy2(self._last_video_output, path)
            self._status_var.set(f"Saved: {os.path.basename(path)}")
        except Exception as exc:
            messagebox.showerror("Save failed", str(exc))

    def _start_video_processing(self, out_path: str):
        self._processing = True
        self._cancel_flag.clear()
        self._vid_render_btn.config(state=tk.DISABLED, text="Rendering…")
        self._vid_copy_btn.config(state=tk.DISABLED, bg=BG2, fg=FG_DIM, highlightbackground="#333333")
        self._vid_save_btn.config(state=tk.DISABLED, bg=BG2, fg=FG_DIM, highlightbackground="#333333")
        self._cancel_btn.pack(fill=tk.X, padx=14, pady=(4, 0), before=self._vid_render_btn)
        threading.Thread(target=self._process_video_thread, args=(out_path,),
                          daemon=True).start()

    def _process_video_thread(self, out_path: str):
        audio_amount = self._sl_audio.get()
        params = dict(
            brightness   = self._sl_brightness.get(),
            contrast     = self._sl_contrast.get(),
            sharpness    = self._sl_sharpness.get(),
            saturation   = self._sl_saturation.get(),
            noise        = self._sl_noise.get(),
            jpeg_quality = int(self._sl_jpeg.get()),
        )
        try:
            import cv2
            cap   = cv2.VideoCapture(self._source_path)
            total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT)) or 1
            fps   = cap.get(cv2.CAP_PROP_FPS) or 30
            w     = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
            h     = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))

            tmp_path = out_path + ".__tmp__.mp4"
            writer = cv2.VideoWriter(
                tmp_path, cv2.VideoWriter_fourcc(*"mp4v"), fps, (w, h)
            )

            BATCH = _N_WORKERS * 3
            frame_idx = 0
            exhausted = False

            with ThreadPoolExecutor(max_workers=_N_WORKERS) as pool:
                while not exhausted:
                    if self._cancel_flag.is_set():
                        cap.release()
                        writer.release()
                        self._cleanup_tmp(tmp_path)
                        self.root.after(0, self._video_cancelled)
                        return

                    raw_batch = []
                    for _ in range(BATCH):
                        ok, frame = cap.read()
                        if not ok:
                            exhausted = True
                            break
                        raw_batch.append(frame)

                    if not raw_batch:
                        break

                    futures = [
                        pool.submit(apply_deep_fry_cv2, f, **params)
                        for f in raw_batch
                    ]
                    for fut in futures:
                        writer.write(fut.result())
                        frame_idx += 1
                        self.root.after(0, self._set_progress,
                                        frame_idx / total * 100, frame_idx, total)

            cap.release()
            writer.release()

            if HAS_MOVIEPY and not self._cancel_flag.is_set():
                self.root.after(0, self._prog_lbl.config, {"text": "Merging audio…"})
                try:
                    try:
                        from moviepy import VideoFileClip
                        from moviepy.audio.AudioClip import AudioArrayClip
                    except ImportError:
                        from moviepy.editor import VideoFileClip
                        AudioArrayClip = None
                    orig_clip = VideoFileClip(self._source_path)
                    new_clip  = VideoFileClip(tmp_path)
                    audio = orig_clip.audio
                    if audio is not None:
                        if audio_amount > 0.01:
                            samples = audio.to_soundarray(fps=audio.fps)
                            samples = distort_audio(samples, audio_amount)
                            audio = AudioArrayClip(samples, fps=audio.fps)
                        try:
                            final = new_clip.with_audio(audio)
                        except AttributeError:
                            final = new_clip.set_audio(audio)
                    else:
                        final = new_clip
                    final.write_videofile(out_path, logger=None)
                    orig_clip.close()
                    new_clip.close()
                    os.remove(tmp_path)
                except Exception:
                    os.replace(tmp_path, out_path)
            else:
                if os.path.exists(tmp_path):
                    os.replace(tmp_path, out_path)

            self.root.after(0, self._video_done, out_path)

        except Exception as exc:
            self.root.after(0, self._video_error, str(exc))

    @staticmethod
    def _cleanup_tmp(path: str):
        try:
            if os.path.exists(path):
                os.remove(path)
        except OSError:
            pass

    def _cancel_video(self):
        self._cancel_flag.set()
        self._cancel_btn.config(state=tk.DISABLED, text="Cancelling…")
        self._prog_lbl.config(text="Cancelling…")

    def _hide_cancel_btn(self):
        self._cancel_btn.pack_forget()
        self._cancel_btn.config(state=tk.NORMAL, text="CANCEL")

    def _set_progress(self, pct: float, frame: int, total: int):
        self._prog_var.set(pct)
        self._prog_lbl.config(text=f"Frame {frame} / {total}")

    def _video_done(self, path: str):
        self._prog_var.set(100)
        self._last_video_output = path
        self._vid_render_btn.config(state=tk.NORMAL, text="RENDER")
        self._vid_copy_btn.config(state=tk.NORMAL, bg="#111111", fg=FG, highlightbackground=BORDER)
        self._vid_save_btn.config(state=tk.NORMAL, bg="#111111", fg=FG, highlightbackground=BORDER)
        self._hide_cancel_btn()
        self._processing = False
        self._prog_lbl.config(text="Done!")
        self._status_var.set("Rendered — use COPY or SAVE below")

    def _put_file_on_clipboard(self, path: str):
        try:
            script = (
                "Add-Type -AssemblyName System.Windows.Forms;"
                "Add-Type -AssemblyName System.Collections.Specialized;"
                "$col = New-Object System.Collections.Specialized.StringCollection;"
                f'$col.Add("{path}");'
                "[System.Windows.Forms.Clipboard]::SetFileDropList($col)"
            )
            subprocess.run(
                ["powershell", "-NoProfile", "-Command", script],
                check=True, capture_output=True,
            )
            self._flash_copy_btn("VIDEO COPIED!")
            self._prog_lbl.config(text="")
        except Exception as exc:
            self._prog_lbl.config(text="")
            self._status_var.set(f"Clipboard copy failed: {exc}")

    def _video_cancelled(self):
        self._prog_var.set(0)
        self._prog_lbl.config(text="")
        self._status_var.set("Cancelled")
        self._vid_render_btn.config(state=tk.NORMAL, text="RENDER")
        self._hide_cancel_btn()
        self._processing = False

    def _video_error(self, msg: str):
        self._prog_var.set(0)
        self._prog_lbl.config(text="")
        self._vid_render_btn.config(state=tk.NORMAL, text="RENDER")
        self._hide_cancel_btn()
        self._processing = False
        messagebox.showerror("Video processing failed", msg)
