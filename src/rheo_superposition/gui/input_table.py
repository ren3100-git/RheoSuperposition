from __future__ import annotations

import csv
import io
import tkinter as tk
from tkinter import messagebox, ttk

import pandas as pd

from .virtual_grid import VirtualGrid


class InputTable(ttk.Frame):
    """Editable rectangular table with spreadsheet-style range paste."""

    def __init__(self, master):
        super().__init__(master)
        self.rows = [["25", "", ""], ["w", "G1", "G2"],
                     ["omega_25", "Gp_25", "Gpp_25"], ["", "", ""]]
        self.variables = ("w", "G1", "G2")
        self.cell = (0, 0)
        self.editor = None
        self.dirty = False
        self.state_var = tk.StringVar(value="Paste data or open a CSV file.")
        bar = ttk.Frame(self)
        bar.pack(fill="x", pady=6)
        for label, command in [("Paste", self.paste), ("Add row", self.add_row),
                               ("Delete rows", self.delete_rows), ("Add condition", self.add_block),
                               ("Delete condition", self.delete_block)]:
            ttk.Button(bar, text=label, command=command).pack(side="left", padx=3)
        ttk.Label(self, textvariable=self.state_var).pack(anchor="w", pady=(0, 6))
        self.selection_var = tk.StringVar(value="")
        ttk.Label(bar, textvariable=self.selection_var).pack(side="left", padx=12)
        frame = ttk.Frame(self)
        frame.pack(fill="both", expand=True)
        frame.rowconfigure(0, weight=1)
        frame.columnconfigure(0, weight=1)
        self.tree = VirtualGrid(frame, rows=lambda: self.rows, before_scroll=self.commit)
        self.tree.grid(row=0, column=0, sticky="nsew")
        xbar = ttk.Scrollbar(frame, orient="horizontal", command=self.tree.xview)
        ybar = ttk.Scrollbar(frame, orient="vertical", command=self.tree.yview)
        xbar.grid(row=1, column=0, sticky="ew")
        ybar.grid(row=0, column=1, sticky="ns")
        self.tree.set_scrollbars(xbar.set, ybar.set)
        self.tree.bind("<Button-1>", self.select_cell, add="+")
        self.tree.bind("<Double-1>", self.edit_cell)
        self.tree.bind("<<Paste>>", self.paste)
        self.tree.bind("<Return>", self.edit_cell)
        self.render()

    def render(self):
        width = max(map(len, self.rows), default=3)
        for row in self.rows:
            row.extend([""] * (width - len(row)))
        self.tree.refresh()
        self.update_selection_label()

    def update_selection_label(self):
        size = len(getattr(self, "variables", ("w", "G1", "G2")))
        start = self.cell[1] // size * size
        temperature = next((v.strip() for v in self.rows[0][start:start + size] if v.strip()), "unnamed")
        self.selection_var.set(f"Selected: {temperature} (columns {start + 1}–{min(start + size, len(self.rows[0]))})")

    def changed(self):
        self.dirty = True
        self.state_var.set("Un-applied changes — click Apply data")

    def mark_applied(self):
        self.dirty = False
        self.state_var.set("Data applied")

    def commit(self):
        if self.editor is not None:
            editor, (r, c) = self.editor
            self.editor = None
            value = editor.get()
            editor.destroy()
            if value != self.rows[r][c]:
                self.rows[r][c] = value
                self.tree.schedule_draw()
                self.update_selection_label()
                self.changed()

    def select_cell(self, event):
        self.commit()
        row, col = self.tree.identify_row(event.y), self.tree.identify_column(event.x)
        if row and col and col != "#0":
            self.cell = (int(row), int(col[1:]) - 1)
            self.update_selection_label()

    def edit_cell(self, event=None):
        self.commit()
        r, c = self.cell
        box = self.tree.cell_bbox(r, c)
        if not box:
            return "break"
        entry = ttk.Entry(self.tree)
        entry.insert(0, self.rows[r][c])
        entry.place(x=box[0], y=box[1], width=box[2], height=box[3])
        self.editor = (entry, (r, c))
        entry.focus_set()
        entry.select_range(0, "end")
        entry.bind("<Return>", lambda e: self.commit())
        entry.bind("<FocusOut>", lambda e: self.commit())
        return "break"

    def paste(self, event=None):
        self.commit()
        try:
            text = self.clipboard_get()
            values = list(csv.reader(io.StringIO(text), delimiter="\t" if "\t" in text else ","))
            if not values:
                return "break"
            r, c = self.cell
            width = max(len(self.rows[0]), c + max(map(len, values)))
            while len(self.rows) < r + len(values):
                self.rows.append([""] * width)
            for row in self.rows:
                row.extend([""] * (width - len(row)))
            for offset, row in enumerate(values):
                self.rows[r + offset][c:c + len(row)] = row
            self.render()
            self.changed()
        except (tk.TclError, csv.Error) as exc:
            messagebox.showerror("Paste failed", str(exc), parent=self)
        return "break"

    def set_rows(self, rows):
        self.commit()
        self.rows = rows or [["", "", ""]]
        self.cell = (0, 0)
        self.render()
        self.changed()

    def add_row(self):
        self.commit()
        self.rows.append([""] * len(self.rows[0]))
        self.render()
        self.tree.see(str(len(self.rows) - 1))
        self.changed()

    def delete_rows(self):
        self.commit()
        selected = {int(i) for i in self.tree.selection()}
        if not selected:
            return
        self.set_rows([row for i, row in enumerate(self.rows) if i not in selected])

    def add_block(self):
        self.commit()
        size = len(self.variables)
        for row in self.rows:
            row.extend([""] * size)
        if len(self.rows) > 1:
            self.rows[1][-size:] = list(self.variables)
        self.cell = (0, len(self.rows[0]) - size)
        self.render()
        self.tree.xview_moveto(1)
        self.changed()

    def delete_block(self):
        self.commit()
        size = len(getattr(self, "variables", ("w", "G1", "G2")))
        start = self.cell[1] // size * size
        temperature = next((v.strip() for v in self.rows[0][start:start + size] if v.strip()), "unnamed")
        if not messagebox.askyesno(
            "Delete condition",
            f"Delete condition {temperature} (columns {start + 1}–{min(start + size, len(self.rows[0]))})?\n"
            "This removes its headers and all data rows from the editor.\n"
            "Analysis changes only when you click Apply data.",
            parent=self,
        ):
            return
        for row in self.rows:
            del row[start:start + size]
        if not self.rows[0]:
            self.rows = [[""] * size, list(getattr(self, "variables", ("w", "G1", "G2"))), [""] * size, [""] * size]
        self.cell = (min(self.cell[0], len(self.rows) - 1), min(start, len(self.rows[0]) - 1))
        self.render()
        self.changed()

    def dataframe(self):
        self.commit()
        return pd.DataFrame(self.rows).replace(r"^\s*$", float("nan"), regex=True)
