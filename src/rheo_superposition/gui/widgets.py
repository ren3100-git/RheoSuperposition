from __future__ import annotations

import tkinter as tk
from collections.abc import Callable
from tkinter import ttk


class EditableShiftTable(ttk.Frame):
    """Treeview with color swatches and in-place numeric editing."""

    def __init__(
        self,
        master,
        columns: list[tuple[str, str, int]],
        editable_columns: set[str],
        on_select: Callable[[str], None],
        on_edit: Callable[[str, str, str], None],
        toggle_columns: set[str] | None = None,
        on_toggle: Callable[[str, str], None] | None = None,
    ) -> None:
        super().__init__(master)
        self.columns = columns
        self.column_keys = [key for key, _, _ in columns]
        self.editable_columns = set(editable_columns)
        self.on_select = on_select
        self.on_edit = on_edit
        self.toggle_columns = set(toggle_columns or ())
        self.on_toggle = on_toggle
        self._editor: ttk.Entry | None = None
        self._editing_item: str | None = None
        self._editing_column: str | None = None
        self._committing = False
        self._swatch_images: dict[str, tk.PhotoImage] = {}

        self.tree = ttk.Treeview(
            self,
            columns=self.column_keys,
            show="tree headings",
            selectmode="browse",
        )
        y_scroll = ttk.Scrollbar(self, orient="vertical", command=self.tree.yview)
        x_scroll = ttk.Scrollbar(self, orient="horizontal", command=self.tree.xview)
        self.tree.configure(yscrollcommand=y_scroll.set, xscrollcommand=x_scroll.set)

        self.tree.grid(row=0, column=0, sticky="nsew")
        y_scroll.grid(row=0, column=1, sticky="ns")
        x_scroll.grid(row=1, column=0, sticky="ew")
        self.rowconfigure(0, weight=1)
        self.columnconfigure(0, weight=1)

        self.tree.heading("#0", text="Color")
        self.tree.column("#0", width=48, minwidth=48, anchor="center", stretch=False)
        for key, heading, width in columns:
            self.tree.heading(key, text=heading)
            self.tree.column(key, width=width, minwidth=55, anchor="center", stretch=True)

        self.tree.tag_configure("reference", font=("TkDefaultFont", 9, "bold"))
        self.tree.bind("<<TreeviewSelect>>", self._handle_select)
        self.tree.bind("<Button-1>", self._handle_click, add="+")
        self.tree.bind("<Double-1>", self._start_edit)

    @staticmethod
    def _make_swatch(color: str) -> tk.PhotoImage:
        image = tk.PhotoImage(width=24, height=12)
        image.put(color, to=(1, 1, 23, 11))
        image.put("#606060", to=(0, 0, 24, 1))
        image.put("#606060", to=(0, 11, 24, 12))
        image.put("#606060", to=(0, 0, 1, 12))
        image.put("#606060", to=(23, 0, 24, 12))
        return image

    def clear(self) -> None:
        self._cancel_editor()
        for item in self.tree.get_children():
            self.tree.delete(item)
        self._swatch_images.clear()

    def populate(self, rows: list[dict], selected_iid: str | None = None) -> None:
        self.clear()
        for row in rows:
            self._insert_or_update_row(row)

        if selected_iid and self.tree.exists(selected_iid):
            self.select_iid(selected_iid)

    def update_row(self, row: dict) -> None:
        self._insert_or_update_row(row)

    def _insert_or_update_row(self, row: dict) -> None:
        iid = str(row["iid"])
        values = [row.get(key, "") for key in self.column_keys]
        tags = tuple(row.get("tags", ()))
        color = str(row.get("color", "#808080"))
        image = self._make_swatch(color)
        self._swatch_images[iid] = image

        if self.tree.exists(iid):
            self.tree.item(iid, values=values, tags=tags, image=image, text="")
        else:
            self.tree.insert("", "end", iid=iid, values=values, tags=tags, image=image, text="")

    def select_iid(self, iid: str | None) -> None:
        if iid and self.tree.exists(iid):
            if self.tree.selection() != (iid,):
                self.tree.selection_set(iid)
            self.tree.focus(iid)
            self.tree.see(iid)

    def _handle_select(self, _event=None) -> None:
        selection = self.tree.selection()
        if selection:
            self.on_select(str(selection[0]))

    def _handle_click(self, event):
        region = self.tree.identify_region(event.x, event.y)
        if region != "cell":
            return None

        item = self.tree.identify_row(event.y)
        column_id = self.tree.identify_column(event.x)
        if not item or not column_id or column_id == "#0":
            return None

        column_index = int(column_id[1:]) - 1
        if not 0 <= column_index < len(self.column_keys):
            return None
        column_key = self.column_keys[column_index]
        if column_key not in self.toggle_columns:
            return None

        if self.on_toggle is not None:
            self.on_toggle(str(item), column_key)
        return "break"

    def _start_edit(self, event) -> None:
        region = self.tree.identify_region(event.x, event.y)
        if region != "cell":
            return

        item = self.tree.identify_row(event.y)
        column_id = self.tree.identify_column(event.x)
        if not item or not column_id or column_id == "#0":
            return

        column_index = int(column_id[1:]) - 1
        if not 0 <= column_index < len(self.column_keys):
            return
        column_key = self.column_keys[column_index]
        if column_key not in self.editable_columns:
            return

        bbox = self.tree.bbox(item, column_id)
        if not bbox:
            return

        self._cancel_editor()
        x, y, width, height = bbox
        current_value = self.tree.set(item, column_key)

        self._editing_item = str(item)
        self._editing_column = column_key
        self._editor = ttk.Entry(self.tree)
        self._editor.insert(0, current_value)
        self._editor.select_range(0, "end")
        self._editor.place(x=x, y=y, width=width, height=height)
        self._editor.focus_set()
        self._editor.bind("<Return>", self._commit_editor)
        self._editor.bind("<KP_Enter>", self._commit_editor)
        self._editor.bind("<Escape>", self._cancel_editor)
        self._editor.bind("<FocusOut>", self._commit_editor)

    def _commit_editor(self, _event=None):
        if self._committing or self._editor is None:
            return "break"
        self._committing = True
        try:
            value = self._editor.get()
            item = self._editing_item
            column = self._editing_column
            self._destroy_editor()
            if item is not None and column is not None:
                self.on_edit(item, column, value)
        finally:
            self._committing = False
        return "break"

    def _cancel_editor(self, _event=None):
        self._destroy_editor()
        return "break"

    def _destroy_editor(self) -> None:
        if self._editor is not None:
            self._editor.destroy()
        self._editor = None
        self._editing_item = None
        self._editing_column = None
