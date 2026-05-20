#!/usr/bin/env python3
"""
PyFry — apply deep-fry meme effects to images and videos.

Install dependencies:
    pip install pillow numpy tkinterdnd2 opencv-python moviepy
    (moviepy is optional — used to preserve audio in video exports)
"""

import tkinter as tk
from tkinter import ttk

from app import PyFryApp, HAS_DND, TkinterDnD
from widgets import BG2, ACCENT, FG


def main():
    if HAS_DND:
        root = TkinterDnD.Tk()
    else:
        root = tk.Tk()

    style = ttk.Style(root)
    style.theme_use("clam")
    style.configure("Horizontal.TScale",
                     background=BG2, troughcolor="#222222",
                     sliderthickness=14, sliderrelief="flat")
    style.configure("TProgressbar",
                     background=FG, troughcolor="#1a1a1a",
                     bordercolor=BG2, lightcolor=FG, darkcolor=FG)
    style.configure("TSeparator", background="#333333")

    PyFryApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
