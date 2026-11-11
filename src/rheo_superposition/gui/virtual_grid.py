"""A viewport-only input grid; off-screen cells never become Tk drawing items."""
from __future__ import annotations

import math
import tkinter as tk
from tkinter import font


class VirtualGrid(tk.Canvas):
    column_width = 125
    row_height = 26
    gutter_width = 65
    header_height = 26

    def __init__(self, master, rows, before_scroll):
        super().__init__(master, background="white", highlightthickness=0,
                         xscrollincrement=1, yscrollincrement=1, takefocus=True)
        self.rows = rows
        self.before_scroll = before_scroll
        self._selected = set()
        self._anchor = 0
        self._pending = None
        self._font = font.nametofont("TkDefaultFont")
        self._text_cache = {}
        self._xbar = self._ybar = lambda *args: None
        self.configure(xscrollcommand=self._x_changed, yscrollcommand=self._y_changed)
        # Use Tk's platform-specific wheel and high-resolution touchpad bindings.
        self.bindtags((str(self), "TtkScrollable", "Canvas", str(self.winfo_toplevel()), "all"))
        self.bind("<Configure>", lambda event: self.schedule_draw())
        self.bind("<Button-1>", self._select)
        self.bind("<MouseWheel>", self._wheel)
        self.bind("<Shift-MouseWheel>", self._wheel)
        self.bind("<Destroy>", self._destroy)

    def _wheel(self, event):
        # Canvas expects integer pixel units, unlike ttk's fractional units.
        pixels = round(-event.delta / 120 * 40)
        if not pixels and event.delta:
            pixels = -1 if event.delta > 0 else 1
        scroll = self.xview_scroll if event.state & 1 else self.yview_scroll
        scroll(pixels, "units")
        return "break"

    def set_scrollbars(self, xbar, ybar):
        self._xbar, self._ybar = xbar, ybar

    def _x_changed(self, first, last):
        self.before_scroll()
        self._xbar(first, last)
        self.schedule_draw()

    def _y_changed(self, first, last):
        self.before_scroll()
        self._ybar(first, last)
        self.schedule_draw()

    def refresh(self):
        self._selected.clear()
        self._text_cache.clear()
        self.configure(scrollregion=(0, 0,
            self.gutter_width + len(self.rows()[0]) * self.column_width,
            self.header_height + len(self.rows()) * self.row_height))
        self.schedule_draw()

    def schedule_draw(self):
        if self._pending is None:
            self._pending = self.after_idle(self._draw)

    def _destroy(self, event):
        if event.widget is self and self._pending is not None:
            self.after_cancel(self._pending)
            self._pending = None

    def _short_text(self, value):
        if value not in self._text_cache:
            available = self.column_width - 12
            if self._font.measure(value) <= available:
                short = value
            else:
                low, high = 0, len(value)
                while low < high:
                    middle = (low + high + 1) // 2
                    if self._font.measure(value[:middle] + "…") <= available:
                        low = middle
                    else:
                        high = middle - 1
                short = value[:low] + "…"
            self._text_cache[value] = short
        return self._text_cache[value]

    def _draw(self):
        self._pending = None
        self.delete("cells")
        rows = self.rows()
        x, y = self.canvasx(0), self.canvasy(0)
        width, height = self.winfo_width(), self.winfo_height()
        first_col = max(0, int(x // self.column_width))
        last_col = min(len(rows[0]), math.ceil((x + width - self.gutter_width) / self.column_width))
        first_row = max(0, int(y // self.row_height))
        last_row = min(len(rows), math.ceil((y + height - self.header_height) / self.row_height))
        for r in range(first_row, last_row):
            top = self.header_height + r * self.row_height
            selected = r in self._selected
            self.create_rectangle(x, top, x + width, top + self.row_height,
                                  fill="#dbeafb" if selected else ("#f7f8fa" if r % 2 else "white"),
                                  outline="", tags="cells")
            for c in range(first_col, last_col):
                left = self.gutter_width + c * self.column_width
                self.create_text(left + 6, top + self.row_height / 2,
                                 text=self._short_text(rows[r][c]), font=self._font,
                                 anchor="w", fill="#202124", tags="cells")
            self.create_line(x, top + self.row_height, x + width, top + self.row_height,
                             fill="#e3e5e8", tags="cells")
        for c in range(first_col, last_col + 1):
            left = self.gutter_width + c * self.column_width
            self.create_line(left, y, left, y + height, fill="#e3e5e8", tags="cells")
        # Fixed row and column headers cover cells that scroll beneath them.
        self.create_rectangle(x, y, x + self.gutter_width, y + height,
                              fill="#eef0f3", outline="", tags="cells")
        for r in range(first_row, last_row):
            self.create_text(x + self.gutter_width / 2, self.header_height + (r + .5) * self.row_height,
                             text=("Cond" if r == 0 else "val" if r == 1 else "name" if r == 2 else str(r - 3)), font=self._font, fill="#444444", tags="cells")
        self.create_rectangle(x, y, x + width, y + self.header_height,
                              fill="#eef0f3", outline="", tags="cells")
        for c in range(first_col, last_col):
            self.create_text(self.gutter_width + (c + .5) * self.column_width, y + self.header_height / 2,
                             text=str(c + 1), font=self._font, fill="#444444", tags="cells")
        self.create_rectangle(x, y, x + self.gutter_width, y + self.header_height,
                              fill="#eef0f3", outline="", tags="cells")
        self.create_text(x + self.gutter_width / 2, y + self.header_height / 2,
                         text="Row", font=self._font, fill="#444444", tags="cells")

    def identify_row(self, y):
        row = int((self.canvasy(y) - self.header_height) // self.row_height)
        return str(row) if y >= self.header_height and 0 <= row < len(self.rows()) else ""

    def identify_column(self, x):
        column = int((self.canvasx(x) - self.gutter_width) // self.column_width)
        if x < self.gutter_width:
            return "#0"
        return f"#{column + 1}" if 0 <= column < len(self.rows()[0]) else ""

    def cell_bbox(self, row, column):
        x = self.gutter_width + column * self.column_width - self.canvasx(0)
        y = self.header_height + row * self.row_height - self.canvasy(0)
        right, bottom = x + self.column_width, y + self.row_height
        x, y = max(x, self.gutter_width), max(y, self.header_height)
        right, bottom = min(right, self.winfo_width()), min(bottom, self.winfo_height())
        return (x, y, right - x, bottom - y) if right > x and bottom > y else ()

    def _select(self, event):
        self.focus_set()
        row = self.identify_row(event.y)
        if not row:
            return
        row = int(row)
        if event.state & 1:
            self._selected = set(range(min(self._anchor, row), max(self._anchor, row) + 1))
        elif event.state & (4 | 8):
            self._selected.symmetric_difference_update({row})
            self._anchor = row
        else:
            self._selected = {row}
            self._anchor = row
        self.schedule_draw()

    def selection(self):
        return tuple(str(row) for row in sorted(self._selected))

    def see(self, row):
        self.yview_moveto(int(row) * self.row_height / max(1, self.header_height + len(self.rows()) * self.row_height))
