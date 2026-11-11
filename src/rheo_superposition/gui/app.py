from __future__ import annotations

import math
import tkinter as tk
import traceback
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

import numpy as np
import pandas as pd
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg, NavigationToolbar2Tk
from matplotlib.collections import LineCollection
from matplotlib.figure import Figure

from ..controller import TTSController
from ..models import TTSConfig
from ..plotting import (draw_unshifted_preview, get_temperature_colors,
                        configure_condition_axis, condition_positions)
from ..readers import (
    normalize_condition_label,
    parse_stacked_header_table,
    read_raw_rheology_table,
    temp_sort_value,
)
from ..settings import (
    input_dialog_initial_directory,
    load_path_settings,
    output_dialog_initial_directory,
    save_path_settings,
)
from ..shifts import make_shifted_dataframe
from ..exporters import public_shift_table
from .input_table import InputTable
from .theme import configure_plot_fonts
from .widgets import EditableShiftTable

APP_TITLE = "RheoSuperposition v5.0.5"
MASTER_CURVE_BOX_ASPECT = 0.60

def _parse_float(value: str, field_name: str) -> float:
    try:
        result = float(str(value).strip())
    except ValueError as exc:
        raise ValueError(f"{field_name} must be numeric.") from exc
    if not np.isfinite(result):
        raise ValueError(f"{field_name} must be finite.")
    return result

def _parse_positive_float(value: str, field_name: str) -> float:
    result = _parse_float(value, field_name)
    if result <= 0:
        raise ValueError(f"{field_name} must be positive.")
    return result

def _format_float(value, digits: int = 6) -> str:
    try:
        v = float(value)
    except (TypeError, ValueError):
        return ""
    if not np.isfinite(v):
        return ""
    return f"{v:.{digits}g}"

def _bool_text(value) -> str:
    return "Yes" if bool(value) else "No"

class TTSShiftGUI(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        configure_plot_fonts()
        self.title(APP_TITLE)
        self.controller = TTSController()
        self.geometry("1500x900")
        self.minsize(1180, 720)

        self.data: dict[str, dict] | None = None
        self.trace_map: pd.DataFrame | None = None
        self.config: TTSConfig | None = None
        self.horizontal_current: pd.DataFrame | None = None
        self.vertical_current: pd.DataFrame | None = None
        self.vertical_stale = False
        self.selected_horizontal_temperature: str | None = None
        self.selected_vertical_temperature: str | None = None
        self.temperature_colors: dict[str, tuple[float, float, float]] = {}
        self._horizontal_artists: dict | None = None
        self._vertical_artists: dict | None = None
        self._horizontal_plot_dirty = True
        self._vertical_plot_dirty = True
        self.horizontal_visible: dict[str, bool] = {}
        self.vertical_visible: dict[str, bool] = {}
        self._horizontal_resize_after: str | None = None
        self._vertical_resize_after: str | None = None
        self._horizontal_y_center_log: float | None = None
        self._vertical_y_center_log: float | None = None

        self.status_var = tk.StringVar(value="Select an input file and load the data.")

        self._create_variables()
        self._load_path_settings()
        self._build_ui()
        self._bind_keyboard_shortcuts()
        self.protocol("WM_DELETE_WINDOW", self._on_close)

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------
    def _create_variables(self) -> None:
        self.data_path_var = tk.StringVar(value="input.csv")
        self.output_dir_var = tk.StringVar(value="rheo_output")
        self.input_scale_var = tk.StringVar(value="log10")
        self.delimiter_var = tk.StringVar(value="auto")
        self.measurement_var = tk.StringVar(value="dynamic")
        self.condition_name_var = tk.StringVar(value="Temperature")
        self.condition_unit_var = tk.StringVar(value="°C")
        self.shift_mode_var = tk.StringVar(value="both")
        self.fixed_x_var = tk.StringVar(value="0")
        self.fixed_y_var = tk.StringVar(value="0")
        self.input_help_var = tk.StringVar(value="Dynamic: w, G1, G2 (3 columns per condition).")
        self.t_ref_var = tk.StringVar(value="25")

        self.loss_b_var = tk.StringVar(value="0.1")
        self.loss_c_var = tk.StringVar(value="0.1")
        self.min_overlap_var = tk.StringVar(value="5")
        self.at_lower_var = tk.StringVar(value="-6")
        self.at_upper_var = tk.StringVar(value="6")
        self.bt_lower_var = tk.StringVar(value="-6")
        self.bt_upper_var = tk.StringVar(value="6")

        self.horizontal_temperature_var = tk.StringVar(value="")
        self.vertical_temperature_var = tk.StringVar(value="")
        self.horizontal_step_var = tk.StringVar(value="0.01")
        self.horizontal_shift_step_var = tk.StringVar(value="0.1")
        self.vertical_step_var = tk.StringVar(value="0.01")
        self.vertical_shift_step_var = tk.StringVar(value="0.1")
        self.condition_axis_scale_var = tk.StringVar(value="linear")
        self.factor_y_direction_var = tk.StringVar(value="normal")
        self.plot_x_min_var = tk.StringVar(value="1e-3")
        self.plot_x_max_var = tk.StringVar(value="1e3")

    def _build_ui(self) -> None:
        self._build_menu()
        header = ttk.Frame(self, padding=8)
        header.pack(fill="x")
        ttk.Label(header, text="Measurement").pack(side="left", padx=(0, 6))
        measurement = ttk.Combobox(header, textvariable=self.measurement_var,
                                  values=("dynamic", "relaxation", "creep"), state="readonly", width=13)
        measurement.pack(side="left", padx=(0, 12))
        measurement.bind("<<ComboboxSelected>>", self._measurement_changed)
        ttk.Label(header, text="Reference condition").pack(side="left", padx=(0, 8))
        ttk.Entry(header, textvariable=self.t_ref_var, width=10).pack(side="left")
        ttk.Label(header, textvariable=self.data_path_var, anchor="w").pack(side="left", fill="x", expand=True, padx=(24, 0))
        self.notebook = ttk.Notebook(self)
        self.editor_tab = ttk.Frame(self.notebook)
        self.notebook.add(self.editor_tab, text="1. Data input")
        self.input_tab = ttk.Frame(self.notebook)
        self.horizontal_tab = ttk.Frame(self.notebook)
        self.vertical_tab = ttk.Frame(self.notebook)
        self.notebook.add(self.input_tab, text="2. Data preview")
        self.notebook.add(self.horizontal_tab, text="3. Horizontal shift")
        self.notebook.add(self.vertical_tab, text="4. Vertical shift / Export")
        self.notebook.pack(fill="both", expand=True, padx=6, pady=(6, 0))

        self._build_editor_tab()
        self._build_input_tab()
        self._build_horizontal_tab()
        self._build_vertical_tab()
        self.notebook.bind("<<NotebookTabChanged>>", self._on_tab_changed)

        status_frame = ttk.Frame(self)
        status_frame.pack(fill="x", padx=8, pady=6)
        ttk.Label(status_frame, textvariable=self.status_var, anchor="w").pack(
            side="left", fill="x", expand=True
        )

    def _build_menu(self):
        menu = tk.Menu(self)
        files = tk.Menu(menu, tearoff=False)
        files.add_command(label="Open CSV…", command=self._browse_input_file)
        files.add_command(label="Output directory…", command=self._browse_output_dir)
        files.add_command(label="Export results", command=self.export_results)
        menu.add_cascade(label="File", menu=files)
        settings = tk.Menu(menu, tearoff=False)
        settings.add_command(label="Settings…", command=self._open_settings)
        menu.add_cascade(label="Settings", menu=settings)
        self.configure(menu=menu)

    def _build_editor_tab(self):
        outer = ttk.Frame(self.editor_tab, padding=10)
        outer.pack(fill="both", expand=True)
        bar = ttk.Frame(outer)
        bar.pack(fill="x")
        ttk.Button(bar, text="Open CSV…", command=self._browse_input_file).pack(side="left")
        ttk.Button(bar, text="Apply data", command=self.load_data).pack(side="left", padx=8)
        ttk.Label(bar, text="Input scale:").pack(side="left", padx=(12, 4))
        ttk.Label(bar, textvariable=self.input_scale_var).pack(side="left")
        ttk.Label(outer, text="Paste from Excel at the selected cell; double-click to edit. "
                  "\n"
                  "Row 1: condition / Row 2: variable / Row 3: name / Row 4 onward: values.").pack(
                      anchor="w", pady=8)
        ttk.Label(outer, textvariable=self.input_help_var).pack(anchor="w")
        ttk.Button(bar, text="New template", command=self._new_template).pack(side="left", padx=8)
        self.input_table = InputTable(outer)
        self.input_table.pack(fill="both", expand=True)

    def _measurement_changed(self, _event=None):
        kind = self.measurement_var.get()
        self.input_table.variables = ("w", "G1", "G2") if kind == "dynamic" else ("t", "J" if kind == "creep" else "G")
        self.input_table.update_selection_label()
        self.input_table.changed()
        self.shift_mode_var.set("both" if kind == "dynamic" else "horizontal_only")
        self.input_help_var.set(
            f"{kind}: {', '.join(self.input_table.variables)} ({len(self.input_table.variables)} columns per condition). "
            "x_shifted = x × a_x; y_shifted = y × b_y. Re-apply data after changing measurement."
        )

    def _new_template(self):
        if not messagebox.askyesno(APP_TITLE, "Replace the input editor with an empty template?", parent=self):
            return
        variables = self.input_table.variables
        label = self.t_ref_var.get().strip() or "reference"
        self.input_table.set_rows([[label] + [""] * (len(variables)-1), list(variables),
                                   [f"{v}_ref" for v in variables], [""] * len(variables)])

    def _calculation_config(self):
        config = self._build_config()
        loaded = self.controller.state.config
        if loaded is not None:
            fields = ("measurement", "condition_name", "condition_unit", "input_scale", "T_ref")
            if any(getattr(config, k) != getattr(loaded, k) for k in fields):
                raise ValueError("Measurement, condition, reference or input scale changed. Apply data again.")
        if self.input_table.dirty:
            raise ValueError("Apply data before calculating or exporting edited input/settings.")
        return config

    def _show_fit_diagnostics(self, result):
        failed = result[~result["success_aT"].astype(bool) | ~result["success_bT"].astype(bool)]
        if not failed.empty:
            lines = [str(row.T_label) + ": " + str(row.get("diagnostic", "No valid fit; check overlap and bounds.")) for _, row in failed.iterrows()]
            messagebox.showwarning(APP_TITLE, "Some conditions were not fitted successfully.\n" + "\n".join(lines), parent=self)

    def _draw_scalar_plots(self, stage):
        ax = getattr(self, stage + "_curve_ax")
        factor_ax = getattr(self, stage + "_factor_ax")
        current = getattr(self, stage + "_current")
        visible = getattr(self, stage + "_visible")
        selected = getattr(self, "selected_" + stage + "_temperature")
        ax.clear()
        factor_ax.clear()
        ax.set_xscale("log")
        ax.set_yscale("log")
        ax.set_xlabel("t × a_x")
        ax.set_ylabel(self.config.response_name + "(t) × b_y")
        ax.set_title("Shifted " + self.config.measurement + " curves")
        ax.set_box_aspect(MASTER_CURVE_BOX_ASPECT)
        configure_condition_axis(factor_ax, [], self.condition_axis_scale_var.get(),
                                 self._condition_axis_label())
        factor_ax.set_ylabel("log10(a_x)" if stage == "horizontal" else "log10(b_y)")
        if self.data and current is not None:
            rows = current.set_index("T_label")
            for label, d in self.data.items():
                if not visible.get(label, True):
                    continue
                row = rows.loc[label]
                ax.plot(d["time"] * row.aT, d["response"] * row.bT,
                        color=self._temperature_color(label), label=label,
                        linewidth=1.8 if label == selected else 0.9, marker="o", markersize=2,
                        markevery=max(1, len(d["time"])//24))
            ax.legend(fontsize=8)
            positions = configure_condition_axis(
                factor_ax, current.T_label.astype(str).tolist(),
                self.condition_axis_scale_var.get(), self._condition_axis_label())
            key = "log10_aT" if stage == "horizontal" else "log10_bT"
            for x, (_, row) in zip(positions, current.iterrows()):
                if visible.get(str(row.T_label), True):
                    factor_ax.scatter(x, row[key], color=self._temperature_color(str(row.T_label)))
            factor_ax.axhline(0, color="gray", linestyle=":", linewidth=0.8)
        self._apply_factor_y_direction(factor_ax)
        ax.set_xlim(*self._plot_x_limits())
        setattr(self, "_" + stage + "_plot_dirty", False)
        getattr(self, stage + "_canvas").draw_idle()

    def _open_settings(self):
        dialog = tk.Toplevel(self)
        dialog.title("Settings")
        dialog.transient(self)
        dialog.resizable(True, True)
        screen_width, screen_height = dialog.winfo_screenwidth(), dialog.winfo_screenheight()
        width, height = min(580, screen_width - 80), min(760, screen_height - 140)
        left = max(0, (screen_width - width) // 2)
        top = max(30, (screen_height - height) // 2)
        dialog.geometry(f"{width}x{height}+{left}+{top}")
        dialog.minsize(min(420, width), min(360, height))
        dialog.columnconfigure(0, weight=1)
        dialog.rowconfigure(0, weight=1)
        viewport = ttk.Frame(dialog)
        viewport.grid(row=0, column=0, sticky="nsew")
        viewport.columnconfigure(0, weight=1)
        viewport.rowconfigure(0, weight=1)
        canvas = tk.Canvas(viewport, highlightthickness=0, yscrollincrement=20)
        scrollbar = ttk.Scrollbar(viewport, orient="vertical", command=canvas.yview)
        canvas.configure(yscrollcommand=scrollbar.set)
        canvas.grid(row=0, column=0, sticky="nsew")
        scrollbar.grid(row=0, column=1, sticky="ns")
        body = ttk.Frame(canvas)
        content = canvas.create_window(0, 0, window=body, anchor="nw")
        canvas.bind("<Configure>", lambda event: canvas.itemconfigure(content, width=event.width))
        body.bind("<Configure>", lambda event: canvas.configure(scrollregion=canvas.bbox("all")))

        def scroll(event):
            if getattr(event, "num", None) in (4, 5):
                steps = -1 if event.num == 4 else 1
            else:
                delta = -event.delta
                steps = int(delta if dialog.tk.call("tk", "windowingsystem") == "aqua" else delta / 120)
                if not steps and delta:
                    steps = -1 if delta < 0 else 1
            canvas.yview_scroll(steps, "units")
            return "break"

        dialog.bind("<MouseWheel>", scroll)
        dialog.bind("<Button-4>", scroll)
        dialog.bind("<Button-5>", scroll)

        def reveal(event):
            dialog.update_idletasks()
            top = event.widget.winfo_rooty() - body.winfo_rooty()
            bottom = top + event.widget.winfo_height()
            visible_top = canvas.canvasy(0)
            visible_height = canvas.winfo_height()
            total = max(body.winfo_height(), 1)
            if top < visible_top:
                canvas.yview_moveto(max(0, top - 8) / total)
            elif bottom > visible_top + visible_height:
                canvas.yview_moveto(max(0, bottom - visible_height + 8) / total)
        fields = [
            ("Input", [("Input scale", self.input_scale_var, ("linear", "log10", "ln")),
                       ("Delimiter", self.delimiter_var, ("auto", "comma", "tab", "whitespace"))]),
            ("Condition", [("Name", self.condition_name_var, None), ("Unit", self.condition_unit_var, None)]),
            ("Automatic calculation", [("Shift mode", self.shift_mode_var, ("both", "horizontal_only", "vertical_only", "none")),
                ("Fixed log10(a_x)", self.fixed_x_var, None), ("Fixed log10(b_y)", self.fixed_y_var, None),
                ("Minimum overlap", self.min_overlap_var, None),
                ("Loss b", self.loss_b_var, None), ("Loss c", self.loss_c_var, None),
                ("aT lower (log10)", self.at_lower_var, None), ("aT upper (log10)", self.at_upper_var, None),
                ("bT lower (log10)", self.bt_lower_var, None), ("bT upper (log10)", self.bt_upper_var, None)]),
            ("Display", [("Factor y direction", self.factor_y_direction_var, ("normal", "inverted")), ("Condition axis scale", self.condition_axis_scale_var, ("linear", "log")), ("x minimum", self.plot_x_min_var, None), ("x maximum", self.plot_x_max_var, None)]),
        ]
        drafts = []
        for title, entries in fields:
            group = ttk.LabelFrame(body, text=title, padding=10)
            group.columnconfigure(1, weight=1)
            group.pack(fill="x", padx=12, pady=6)
            row = 0
            for label, original, choices in entries:
                draft = tk.StringVar(dialog, value=original.get())
                drafts.append((original, draft))
                ttk.Label(group, text=label, width=24).grid(row=row, column=0, sticky="w", pady=3)
                if choices:
                    widget = ttk.Combobox(group, textvariable=draft, values=choices, state="readonly")
                else:
                    widget = ttk.Entry(group, textvariable=draft)
                widget.grid(row=row, column=1, sticky="ew", pady=3)
                widget.bind("<FocusIn>", reveal)
                row += 1
                help_text = {
                    "Factor y direction": "inverted：シフト係数が大きいほど下に表示します。",
                    "Loss b": "大きな差に対する損失の重み。値を大きくすると、大きな差をより強く評価します。",
                    "Loss c": "差を大きいとみなす目安。値を大きくすると、その基準が緩やかになります。",
                }.get(label)
                if help_text:
                    ttk.Label(group, text=help_text, wraplength=290).grid(
                        row=row, column=1, sticky="w", pady=(0, 8))
                    row += 1
        ttk.Label(body, text="Input changes require Apply data; calculation changes require re-running shifts.",
                  wraplength=400).pack(padx=12, pady=6)

        def apply():
            previous = [original.get() for original, _ in drafts]
            try:
                for original, draft in drafts:
                    original.set(draft.get())
                self._build_config()
                self._validate_condition_axis()
            except Exception as exc:
                for (original, _), value in zip(drafts, previous):
                    original.set(value)
                messagebox.showerror("Invalid settings", str(exc), parent=dialog)
                return
            input_fields = (self.input_scale_var, self.condition_name_var, self.condition_unit_var)
            if any(any(original is field for field in input_fields) and original.get() != old
                   for (original, _), old in zip(drafts, previous)):
                self.input_table.changed()
            self.apply_plot_settings()
            self.status_var.set("Settings applied. Re-apply data for input changes; re-run shifts for calculation changes.")
            dialog.destroy()

        buttons = ttk.Frame(dialog, padding=12)
        buttons.grid(row=1, column=0, sticky="ew")
        ttk.Button(buttons, text="Apply", command=apply).pack(side="right")
        ttk.Button(buttons, text="Cancel", command=dialog.destroy).pack(side="right", padx=6)
        dialog.grab_set()

    def _build_input_tab(self) -> None:
        outer = ttk.Frame(self.input_tab, padding=10)
        outer.pack(fill="both", expand=True)
        outer.columnconfigure(0, weight=0)
        outer.columnconfigure(1, weight=1)
        outer.rowconfigure(0, weight=1)

        left_panel = ttk.Frame(outer)
        right_panel = ttk.Frame(outer)
        left_panel.grid(row=0, column=0, sticky="nsew", padx=(0, 5))
        right_panel.grid(row=0, column=1, sticky="nsew", padx=(5, 0))

        left_panel.columnconfigure(0, weight=1)
        left_panel.rowconfigure(0, weight=1)
        right_panel.columnconfigure(0, weight=1)
        right_panel.rowconfigure(0, weight=1)

        recognized_group = ttk.LabelFrame(left_panel, text="Recognized data", padding=8)
        recognized_group.grid(row=0, column=0, sticky="nsew")
        recognized_group.rowconfigure(0, weight=1)
        recognized_group.columnconfigure(0, weight=1)

        self.preview_tree = ttk.Treeview(
            recognized_group,
            columns=("T", "points", "omega_min", "omega_max"),
            show="headings",
            height=10,
        )
        for key, heading, width in [
            ("T", "Condition", 85),
            ("points", "Points", 55),
            ("omega_min", "x min", 90),
            ("omega_max", "x max", 90),
        ]:
            self.preview_tree.heading(key, text=heading)
            self.preview_tree.column(key, width=width, anchor="center")
        preview_scroll = ttk.Scrollbar(
            recognized_group, orient="vertical", command=self.preview_tree.yview
        )
        self.preview_tree.configure(yscrollcommand=preview_scroll.set)
        self.preview_tree.grid(row=0, column=0, sticky="nsew")
        preview_scroll.grid(row=0, column=1, sticky="ns")

        button_bar = ttk.Frame(recognized_group)
        button_bar.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(8, 0))
        ttk.Button(
            button_bar,
            text="Open horizontal-shift tab",
            command=lambda: self.notebook.select(self.horizontal_tab),
        ).pack(side="left", padx=6)

        preview_plot_group = ttk.LabelFrame(right_panel, text="Input preview", padding=8)
        preview_plot_group.grid(row=0, column=0, sticky="nsew")
        preview_plot_group.rowconfigure(0, weight=1)
        preview_plot_group.columnconfigure(0, weight=1)

        self.preview_figure = Figure(figsize=(7, 8), dpi=100)
        preview_gs = self.preview_figure.add_gridspec(2, 1, height_ratios=(5, 3))
        self.preview_gp_ax = self.preview_figure.add_subplot(preview_gs[0, 0])
        self.preview_tan_ax = self.preview_figure.add_subplot(preview_gs[1, 0])
        self.preview_figure.subplots_adjust(
            left=0.11,
            right=0.97,
            bottom=0.08,
            top=0.94,
            hspace=0.25,
        )
        self.preview_canvas = FigureCanvasTkAgg(self.preview_figure, master=preview_plot_group)
        self.preview_canvas.get_tk_widget().grid(row=0, column=0, sticky="nsew")
        draw_unshifted_preview(self.preview_gp_ax, self.preview_tan_ax, None)
        self.preview_canvas.draw_idle()

    def _build_horizontal_tab(self) -> None:
        self.horizontal_tab.rowconfigure(1, weight=1)
        self.horizontal_tab.columnconfigure(0, weight=1)

        controls = ttk.Frame(self.horizontal_tab, padding=(8, 8, 8, 4))
        controls.grid(row=0, column=0, sticky="ew")

        ttk.Button(controls, text="Run horizontal / joint shift", command=self.run_horizontal_shift).pack(side="left")
        ttk.Label(controls, text="Condition").pack(side="left", padx=(14, 4))
        self.horizontal_temperature_combo = ttk.Combobox(
            controls,
            textvariable=self.horizontal_temperature_var,
            state="readonly",
            width=12,
        )
        self.horizontal_temperature_combo.pack(side="left")
        self.horizontal_temperature_combo.bind("<<ComboboxSelected>>", self._horizontal_combo_selected)

        ttk.Label(controls, text="Step").pack(side="left", padx=(14, 4))
        ttk.Entry(controls, textvariable=self.horizontal_step_var, width=8).pack(side="left")
        ttk.Label(controls, text="Shift+step").pack(side="left", padx=(8, 4))
        ttk.Entry(controls, textvariable=self.horizontal_shift_step_var, width=8).pack(side="left")

        ttk.Button(controls, text="←", width=4, command=lambda: self.adjust_horizontal(-1, False)).pack(side="left", padx=(12, 2))
        ttk.Button(controls, text="→", width=4, command=lambda: self.adjust_horizontal(1, False)).pack(side="left", padx=2)
        ttk.Button(controls, text="Reset selected", command=self.reset_selected_horizontal).pack(side="left", padx=(12, 2))
        ttk.Button(controls, text="Reset all", command=self.reset_all_horizontal).pack(side="left", padx=2)

        pane = ttk.Panedwindow(self.horizontal_tab, orient="horizontal")
        pane.grid(row=1, column=0, sticky="nsew", padx=8, pady=(0, 8))

        graph_frame = ttk.Frame(pane)
        table_frame = ttk.Frame(pane)
        pane.add(graph_frame, weight=3)
        pane.add(table_frame, weight=2)

        graph_frame.rowconfigure(0, weight=1)
        graph_frame.columnconfigure(0, weight=1)
        self.horizontal_figure = Figure(figsize=(8, 7), dpi=100)
        gs = self.horizontal_figure.add_gridspec(2, 1, height_ratios=(3.2, 1.35))
        self.horizontal_curve_ax = self.horizontal_figure.add_subplot(gs[0, 0])
        self.horizontal_factor_ax = self.horizontal_figure.add_subplot(gs[1, 0])
        self.horizontal_figure.subplots_adjust(left=0.11, right=0.98, bottom=0.09, top=0.95, hspace=0.38)
        self.horizontal_canvas = FigureCanvasTkAgg(self.horizontal_figure, master=graph_frame)
        self.horizontal_canvas_widget = self.horizontal_canvas.get_tk_widget()
        self.horizontal_canvas_widget.grid(row=0, column=0, sticky="nsew")
        self.horizontal_canvas_widget.bind(
            "<Configure>", lambda _event: self._schedule_plot_resize("horizontal"), add="+"
        )
        toolbar = NavigationToolbar2Tk(self.horizontal_canvas, graph_frame, pack_toolbar=False)
        toolbar.update()
        toolbar.grid(row=1, column=0, sticky="ew")

        table_frame.rowconfigure(1, weight=1)
        table_frame.columnconfigure(0, weight=1)
        ttk.Label(
            table_frame,
            text="Click Show to display/hide a condition. Double-click log10(a_x) or a_x to edit.",
            wraplength=500,
        ).grid(row=0, column=0, sticky="w", pady=(0, 6))

        h_columns = [
            ("visible", "Show", 70),
            ("T", "Condition", 85),
            ("log10", "log10(a_x)", 95),
            ("factor", "a_x", 95),
            ("auto", "Calculated log10(a_x)", 115),
            ("loss", "Loss", 95),
            ("overlap", "Overlap", 75),
            ("manual", "Manual", 70),
            ("status", "Status", 75),
        ]
        self.horizontal_table = EditableShiftTable(
            table_frame,
            columns=h_columns,
            editable_columns={"log10", "factor"},
            on_select=self.select_horizontal_temperature,
            on_edit=self.edit_horizontal_table_value,
            toggle_columns={"visible"},
            on_toggle=self.toggle_horizontal_visibility,
        )
        self.horizontal_table.grid(row=1, column=0, sticky="nsew")
        self._draw_empty_horizontal_plots()

    def _build_vertical_tab(self) -> None:
        self.vertical_tab.rowconfigure(1, weight=1)
        self.vertical_tab.columnconfigure(0, weight=1)

        controls = ttk.Frame(self.vertical_tab, padding=(8, 8, 8, 4))
        controls.grid(row=0, column=0, sticky="ew")

        ttk.Button(controls, text="Run vertical shift", command=self.run_vertical_shift).pack(side="left")
        ttk.Label(controls, text="Condition").pack(side="left", padx=(14, 4))
        self.vertical_temperature_combo = ttk.Combobox(
            controls,
            textvariable=self.vertical_temperature_var,
            state="readonly",
            width=12,
        )
        self.vertical_temperature_combo.pack(side="left")
        self.vertical_temperature_combo.bind("<<ComboboxSelected>>", self._vertical_combo_selected)

        ttk.Label(controls, text="Step").pack(side="left", padx=(14, 4))
        ttk.Entry(controls, textvariable=self.vertical_step_var, width=8).pack(side="left")
        ttk.Label(controls, text="Shift+step").pack(side="left", padx=(8, 4))
        ttk.Entry(controls, textvariable=self.vertical_shift_step_var, width=8).pack(side="left")

        ttk.Button(controls, text="↓", width=4, command=lambda: self.adjust_vertical(-1, False)).pack(side="left", padx=(12, 2))
        ttk.Button(controls, text="↑", width=4, command=lambda: self.adjust_vertical(1, False)).pack(side="left", padx=2)
        ttk.Button(controls, text="Reset selected", command=self.reset_selected_vertical).pack(side="left", padx=(12, 2))
        ttk.Button(controls, text="Reset all", command=self.reset_all_vertical).pack(side="left", padx=2)
        ttk.Button(controls, text="Export", command=self.export_results).pack(side="right")

        pane = ttk.Panedwindow(self.vertical_tab, orient="horizontal")
        pane.grid(row=1, column=0, sticky="nsew", padx=8, pady=(0, 8))

        graph_frame = ttk.Frame(pane)
        table_frame = ttk.Frame(pane)
        pane.add(graph_frame, weight=3)
        pane.add(table_frame, weight=2)

        graph_frame.rowconfigure(0, weight=1)
        graph_frame.columnconfigure(0, weight=1)
        self.vertical_figure = Figure(figsize=(8, 7), dpi=100)
        gs = self.vertical_figure.add_gridspec(2, 1, height_ratios=(3.2, 1.35))
        self.vertical_curve_ax = self.vertical_figure.add_subplot(gs[0, 0])
        self.vertical_factor_ax = self.vertical_figure.add_subplot(gs[1, 0])
        self.vertical_figure.subplots_adjust(left=0.11, right=0.98, bottom=0.09, top=0.95, hspace=0.38)
        self.vertical_canvas = FigureCanvasTkAgg(self.vertical_figure, master=graph_frame)
        self.vertical_canvas_widget = self.vertical_canvas.get_tk_widget()
        self.vertical_canvas_widget.grid(row=0, column=0, sticky="nsew")
        self.vertical_canvas_widget.bind(
            "<Configure>", lambda _event: self._schedule_plot_resize("vertical"), add="+"
        )
        toolbar = NavigationToolbar2Tk(self.vertical_canvas, graph_frame, pack_toolbar=False)
        toolbar.update()
        toolbar.grid(row=1, column=0, sticky="ew")

        table_frame.rowconfigure(2, weight=1)
        table_frame.columnconfigure(0, weight=1)
        self.vertical_warning_var = tk.StringVar(value="")
        ttk.Label(table_frame, textvariable=self.vertical_warning_var, foreground="#9a4f00", wraplength=500).grid(
            row=0, column=0, sticky="w", pady=(0, 4)
        )
        ttk.Label(
            table_frame,
            text=(
                "Click Show to display/hide a condition. Double-click log10(b_y) or b_y to edit. "
                "G' uses open markers and G'' uses filled markers; both use solid lines."
            ),
            wraplength=500,
        ).grid(row=1, column=0, sticky="w", pady=(0, 6))

        v_columns = [
            ("visible", "Show", 70),
            ("T", "Condition", 85),
            ("log10", "log10(b_y)", 95),
            ("factor", "b_y", 95),
            ("auto", "Calculated log10(b_y)", 115),
            ("loss", "Loss", 95),
            ("overlap", "Overlap", 75),
            ("manual", "Manual", 70),
            ("status", "Status", 75),
        ]
        self.vertical_table = EditableShiftTable(
            table_frame,
            columns=v_columns,
            editable_columns={"log10", "factor"},
            on_select=self.select_vertical_temperature,
            on_edit=self.edit_vertical_table_value,
            toggle_columns={"visible"},
            on_toggle=self.toggle_vertical_visibility,
        )
        self.vertical_table.grid(row=2, column=0, sticky="nsew")
        self._draw_empty_vertical_plots()

    # ------------------------------------------------------------------
    # Configuration and loading
    # ------------------------------------------------------------------
    def _load_path_settings(self) -> None:
        payload = load_path_settings()
        input_file = payload.get("input_file", "")
        output_dir = payload.get("output_dir", "")
        if input_file:
            self.data_path_var.set(input_file)
        if output_dir:
            self.output_dir_var.set(output_dir)

    def _save_path_settings(self) -> None:
        save_path_settings(self.data_path_var.get(), self.output_dir_var.get())

    def _input_dialog_initial_directory(self) -> Path:
        return input_dialog_initial_directory(self.data_path_var.get())

    def _output_dialog_initial_directory(self) -> Path:
        return output_dialog_initial_directory(self.output_dir_var.get())

    def _on_close(self) -> None:
        self.input_table.commit()
        if self.input_table.dirty and not messagebox.askyesno(APP_TITLE, "Close with un-applied table edits?"):
            return
        self._save_path_settings()
        self.destroy()

    def _browse_input_file(self) -> None:
        filename = filedialog.askopenfilename(
            title="Select rheology data", initialdir=str(self._input_dialog_initial_directory()),
            filetypes=[("CSV and text files", "*.csv *.txt *.dat"), ("All files", "*.*")],
        )
        if not filename:
            return
        try:
            raw = read_raw_rheology_table(Path(filename), self._delimiter_value())
            if self.input_table.dirty and not messagebox.askyesno(APP_TITLE, "Replace un-applied table edits?"):
                return
            self.input_table.set_rows(raw.fillna("").astype(str).values.tolist())
            self.data_path_var.set(filename)
            self._save_path_settings()
            self.notebook.select(self.editor_tab)
        except Exception as exc:
            self._show_error("Could not open file", exc)

    def _browse_output_dir(self) -> None:
        dirname = filedialog.askdirectory(
            title="Select output directory",
            initialdir=str(self._output_dialog_initial_directory()),
        )
        if dirname:
            self.output_dir_var.set(dirname)
            self._save_path_settings()

    def _delimiter_value(self) -> str:
        mapping = {
            "auto": "auto",
            "comma": ",",
            "tab": "\t",
            "whitespace": "whitespace",
        }
        return mapping.get(self.delimiter_var.get(), "auto")

    def _build_config(self) -> TTSConfig:
        self._plot_x_limits()
        min_overlap = int(_parse_positive_float(self.min_overlap_var.get(), "Minimum overlap"))
        at_lower = _parse_float(self.at_lower_var.get(), "aT lower bound")
        at_upper = _parse_float(self.at_upper_var.get(), "aT upper bound")
        bt_lower = _parse_float(self.bt_lower_var.get(), "bT lower bound")
        bt_upper = _parse_float(self.bt_upper_var.get(), "bT upper bound")
        if at_lower >= at_upper:
            raise ValueError("aT lower bound must be smaller than the upper bound.")
        if bt_lower >= bt_upper:
            raise ValueError("bT lower bound must be smaller than the upper bound.")

        return TTSConfig(
            data_path=Path(self.data_path_var.get()).expanduser(),
            output_dir=Path(self.output_dir_var.get()).expanduser(),
            input_delimiter=self._delimiter_value(),
            input_scale=self.input_scale_var.get(),
            input_format="stacked_header",
            T_ref=self.t_ref_var.get().strip(),
            measurement=self.measurement_var.get(),
            condition_name=self.condition_name_var.get().strip(),
            condition_unit=self.condition_unit_var.get().strip(),
            shift_mode=self.shift_mode_var.get(),
            fixed_log10_aT=_parse_float(self.fixed_x_var.get(), "Fixed log10(a_x)"),
            fixed_log10_bT=_parse_float(self.fixed_y_var.get(), "Fixed log10(b_y)"),
            loss_b=_parse_positive_float(self.loss_b_var.get(), "Loss parameter b"),
            loss_c=_parse_positive_float(self.loss_c_var.get(), "Loss parameter c"),
            min_overlap_points=min_overlap,
            log10_aT_bounds=(at_lower, at_upper),
            log10_bT_bounds=(bt_lower, bt_upper),
            save_shifted_data=True,
        )

    def _plot_x_limits(self) -> tuple[float, float]:
        x_min = _parse_positive_float(self.plot_x_min_var.get(), "Plot x minimum")
        x_max = _parse_positive_float(self.plot_x_max_var.get(), "Plot x maximum")
        if x_min >= x_max:
            raise ValueError("Plot x minimum must be smaller than the maximum.")
        return x_min, x_max

    def _apply_factor_y_direction(self, ax):
        ax.yaxis.set_inverted(self.factor_y_direction_var.get() == "inverted")

    def _condition_axis_label(self):
        name = self.condition_name_var.get().strip() or "Condition"
        unit = self.condition_unit_var.get().strip()
        return name + (f" ({unit})" if unit else "")

    def _validate_condition_axis(self, data=None):
        labels = list((self.data if data is None else data) or {})
        condition_positions(labels, self.condition_axis_scale_var.get())

    def apply_plot_settings(self) -> None:
        try:
            self._plot_x_limits()
            self._validate_condition_axis()
        except Exception as exc:
            self._show_error("Invalid plot settings", exc)
            return
        self._horizontal_y_center_log = None
        self._vertical_y_center_log = None
        self._request_horizontal_plot_update()
        self._request_vertical_plot_update()
        self.status_var.set("Plot display settings were applied.")

    def _schedule_plot_resize(self, which: str) -> None:
        attr = "_horizontal_resize_after" if which == "horizontal" else "_vertical_resize_after"
        previous = getattr(self, attr)
        if previous is not None:
            try:
                self.after_cancel(previous)
            except tk.TclError:
                pass

        def apply_resize() -> None:
            setattr(self, attr, None)
            if which == "horizontal":
                self._request_horizontal_plot_update()
            else:
                self._request_vertical_plot_update()

        setattr(self, attr, self.after(140, apply_resize))

    def load_data(self) -> None:
        try:
            config = self._build_config()
            raw = self.input_table.dataframe()
            data, trace_map = parse_stacked_header_table(raw, config, strict=True)
            if normalize_condition_label(config.T_ref, config) not in data:
                raise ValueError("Reference condition must be present in the input data.")
            if self.horizontal_current is not None and not messagebox.askyesno(
                APP_TITLE, "Apply edited data and clear existing shift results?"
            ):
                return
            self._validate_condition_axis(data)
            self.controller.set_data(data, trace_map, config)
        except Exception as exc:
            self._show_error("Failed to load data", exc)
            return

        self.input_table.mark_applied()
        self.notebook.select(self.input_tab)
        self.config = config
        self._save_path_settings()
        self.data = data
        self.trace_map = trace_map
        self.horizontal_current = None
        self.vertical_current = None
        self.vertical_stale = False
        self.temperature_colors = get_temperature_colors(data)
        self.horizontal_visible = {str(T): True for T in data}
        self.vertical_visible = {str(T): True for T in data}
        self._horizontal_artists = None
        self._vertical_artists = None
        self._horizontal_y_center_log = None
        self._vertical_y_center_log = None
        self._horizontal_plot_dirty = True
        self._vertical_plot_dirty = True

        temperatures = sorted(data.keys(), key=temp_sort_value)
        non_ref = [t for t in temperatures if t != normalize_condition_label(config.T_ref, config)]
        initial = non_ref[0] if non_ref else temperatures[0]
        self.selected_horizontal_temperature = initial
        self.selected_vertical_temperature = initial
        self.horizontal_temperature_var.set(initial)
        self.vertical_temperature_var.set(initial)
        self.horizontal_temperature_combo.configure(values=temperatures)
        self.vertical_temperature_combo.configure(values=temperatures)

        self._refresh_preview()
        self._refresh_horizontal_view()
        self._refresh_vertical_view()
        self.status_var.set(
            f"Loaded {len(temperatures)} conditions from {config.data_path.name}. "
            "Run the horizontal shift next."
        )

    def _refresh_preview(self) -> None:
        for item in self.preview_tree.get_children():
            self.preview_tree.delete(item)
        if not self.data:
            return
        for T in sorted(self.data.keys(), key=temp_sort_value):
            d = self.data[T]
            omega = np.asarray(d["time"] if "time" in d else d["omega"], dtype=float)
            self.preview_tree.insert(
                "",
                "end",
                values=(
                    T,
                    len(omega),
                    _format_float(np.nanmin(omega)),
                    _format_float(np.nanmax(omega)),
                ),
            )
        draw_unshifted_preview(
            self.preview_gp_ax,
            self.preview_tan_ax,
            self.data,
            self.temperature_colors,
        )
        self.preview_canvas.draw_idle()

    # ------------------------------------------------------------------
    # Automatic estimation
    # ------------------------------------------------------------------
    def run_horizontal_shift(self) -> None:
        if not self._require_data():
            return
        try:
            self.config = self._calculation_config()
            result = self.controller.run_horizontal(self.config)
            result = self._prepare_horizontal_table(result)
        except Exception as exc:
            self._show_error("Horizontal-shift estimation failed", exc)
            return

        self.horizontal_current = result
        self.vertical_current = None
        self.vertical_stale = False
        self._horizontal_artists = None
        self._vertical_artists = None
        self._horizontal_y_center_log = None
        self._vertical_y_center_log = None
        self._horizontal_plot_dirty = True
        self._vertical_plot_dirty = True
        self._refresh_horizontal_view()
        self._refresh_vertical_view()
        self.status_var.set("Shift estimation completed. Manual adjustment is available.")
        self._show_fit_diagnostics(result)

    def run_vertical_shift(self) -> None:
        if not self._require_data():
            return
        try:
            self.config = self._calculation_config()
            standalone = self.horizontal_current is None
            result = self.controller.run_vertical(self.horizontal_current, self.config)
            if standalone:
                self.config = self.controller.state.config
                self.shift_mode_var.set(self.config.shift_mode)
                self.horizontal_current = self._prepare_horizontal_table(self.controller.state.horizontal_shifts)
                self._horizontal_artists = None
                self._horizontal_y_center_log = None
                self._horizontal_plot_dirty = True
            result = self._prepare_vertical_table(result)
        except Exception as exc:
            self._show_error("Vertical-shift estimation failed", exc)
            return

        self.vertical_current = result
        self.vertical_stale = False
        self._vertical_artists = None
        self._vertical_y_center_log = None
        self._vertical_plot_dirty = True
        if standalone:
            self._refresh_horizontal_view()
        self._refresh_vertical_view()
        self.status_var.set("Vertical shift completed. Manual adjustment and export are available.")
        self._show_fit_diagnostics(result)

    def _prepare_horizontal_table(self, df: pd.DataFrame) -> pd.DataFrame:
        out = df.copy()
        out["auto_log10_aT"] = out["log10_aT"].astype(float)
        out["auto_aT"] = out["aT"].astype(float)
        out["aT_manual"] = False
        return self._recalculate_horizontal_derived(out)

    def _prepare_vertical_table(self, df: pd.DataFrame) -> pd.DataFrame:
        out = df.copy()
        out["auto_log10_bT"] = out["log10_bT"].astype(float)
        out["auto_bT"] = out["bT"].astype(float)
        out["bT_manual"] = False

        if self.horizontal_current is not None:
            h = self.horizontal_current.set_index("T_label")
            out["auto_log10_aT"] = out["T_label"].map(h["auto_log10_aT"])
            out["auto_aT"] = out["T_label"].map(h["auto_aT"])
            out["aT_manual"] = out["T_label"].map(h["aT_manual"]).fillna(False).astype(bool)
        return self._recalculate_vertical_derived(out)

    # ------------------------------------------------------------------
    # Selection synchronization
    # ------------------------------------------------------------------
    def _horizontal_combo_selected(self, _event=None) -> None:
        self.select_horizontal_temperature(self.horizontal_temperature_var.get())

    def _vertical_combo_selected(self, _event=None) -> None:
        self.select_vertical_temperature(self.vertical_temperature_var.get())

    def select_horizontal_temperature(self, temperature: str) -> None:
        if not temperature:
            return
        temperature = str(temperature)
        changed = temperature != self.selected_horizontal_temperature
        self.selected_horizontal_temperature = temperature
        self.horizontal_temperature_var.set(temperature)
        self.horizontal_table.select_iid(temperature)
        if changed:
            self._request_horizontal_plot_update()

    def select_vertical_temperature(self, temperature: str) -> None:
        if not temperature:
            return
        temperature = str(temperature)
        changed = temperature != self.selected_vertical_temperature
        self.selected_vertical_temperature = temperature
        self.vertical_temperature_var.set(temperature)
        self.vertical_table.select_iid(temperature)
        if changed:
            self._request_vertical_plot_update()

    # ------------------------------------------------------------------
    # Manual adjustment
    # ------------------------------------------------------------------
    def adjust_horizontal(self, direction: int, shifted: bool) -> None:
        if not self._require_horizontal_results():
            return
        T = self.selected_horizontal_temperature
        if not T:
            return
        if self._is_reference(T):
            self.status_var.set("The reference condition is fixed at aT = 1.")
            return
        try:
            step_var = self.horizontal_shift_step_var if shifted else self.horizontal_step_var
            step = _parse_positive_float(step_var.get(), "Horizontal shift step")
            current = self._get_value(self.horizontal_current, T, "log10_aT")
            self._set_horizontal_log10(T, current + direction * step)
        except Exception as exc:
            self._show_error("Horizontal manual shift failed", exc)

    def adjust_vertical(self, direction: int, shifted: bool) -> None:
        if not self._require_vertical_results():
            return
        T = self.selected_vertical_temperature
        if not T:
            return
        if self._is_reference(T):
            self.status_var.set("The reference condition is fixed at bT = 1.")
            return
        try:
            step_var = self.vertical_shift_step_var if shifted else self.vertical_step_var
            step = _parse_positive_float(step_var.get(), "Vertical shift step")
            current = self._get_value(self.vertical_current, T, "log10_bT")
            self._set_vertical_log10(T, current + direction * step)
        except Exception as exc:
            self._show_error("Vertical manual shift failed", exc)

    def edit_horizontal_table_value(self, temperature: str, column: str, value: str) -> None:
        if self.horizontal_current is None:
            return
        if self._is_reference(temperature):
            messagebox.showinfo(APP_TITLE, "The reference condition is fixed at aT = 1.")
            self._update_horizontal_table_row(temperature)
            return
        try:
            if column == "log10":
                log_value = _parse_float(value, "log10(a_x)")
            elif column == "factor":
                factor = _parse_positive_float(value, "aT")
                log_value = math.log10(factor)
            else:
                return
            self._set_horizontal_log10(temperature, log_value)
        except Exception as exc:
            self._show_error("Invalid horizontal shift value", exc)
            self._update_horizontal_table_row(temperature)

    def edit_vertical_table_value(self, temperature: str, column: str, value: str) -> None:
        if self.vertical_current is None:
            return
        if self._is_reference(temperature):
            messagebox.showinfo(APP_TITLE, "The reference condition is fixed at bT = 1.")
            self._update_vertical_table_row(temperature)
            return
        try:
            if column == "log10":
                log_value = _parse_float(value, "log10(b_y)")
            elif column == "factor":
                factor = _parse_positive_float(value, "bT")
                log_value = math.log10(factor)
            else:
                return
            self._set_vertical_log10(temperature, log_value)
        except Exception as exc:
            self._show_error("Invalid vertical shift value", exc)
            self._update_vertical_table_row(temperature)

    def _set_horizontal_log10(self, T: str, log_value: float) -> None:
        if self.horizontal_current is None:
            return
        if not np.isfinite(log_value):
            raise ValueError("log10(a_x) must be finite.")

        mask = self.horizontal_current["T_label"].astype(str) == str(T)
        if not mask.any():
            raise KeyError(f"Temperature {T} was not found.")
        self.horizontal_current.loc[mask, "log10_aT"] = float(log_value)
        self.horizontal_current.loc[mask, "aT"] = 10.0 ** float(log_value)
        auto = float(self.horizontal_current.loc[mask, "auto_log10_aT"].iloc[0])
        self.horizontal_current.loc[mask, "aT_manual"] = not np.isclose(log_value, auto, atol=1.0e-12)
        self.horizontal_current = self._recalculate_horizontal_derived(self.horizontal_current)

        self._propagate_horizontal_values_to_vertical()
        self.vertical_stale = self.vertical_current is not None
        self._update_horizontal_table_row(T)
        self._request_horizontal_plot_update()
        if self.vertical_current is not None:
            self._request_vertical_plot_update()
        self._update_vertical_warning()
        self.status_var.set(f"Updated horizontal shift for T={T}: log10(a_x)={log_value:.6g}")

    def _set_vertical_log10(self, T: str, log_value: float) -> None:
        if self.vertical_current is None:
            return
        if not np.isfinite(log_value):
            raise ValueError("log10(b_y) must be finite.")

        mask = self.vertical_current["T_label"].astype(str) == str(T)
        if not mask.any():
            raise KeyError(f"Temperature {T} was not found.")
        self.vertical_current.loc[mask, "log10_bT"] = float(log_value)
        self.vertical_current.loc[mask, "bT"] = 10.0 ** float(log_value)
        auto = float(self.vertical_current.loc[mask, "auto_log10_bT"].iloc[0])
        self.vertical_current.loc[mask, "bT_manual"] = not np.isclose(log_value, auto, atol=1.0e-12)
        self.vertical_current = self._recalculate_vertical_derived(self.vertical_current)
        self.vertical_stale = False
        self._update_vertical_table_row(T)
        self._request_vertical_plot_update()
        self._update_vertical_warning()
        self.status_var.set(f"Updated vertical shift for T={T}: log10(b_y)={log_value:.6g}")

    def reset_selected_horizontal(self) -> None:
        T = self.selected_horizontal_temperature
        if self.horizontal_current is None or not T:
            return
        mask = self.horizontal_current["T_label"].astype(str) == str(T)
        if mask.any():
            value = float(self.horizontal_current.loc[mask, "auto_log10_aT"].iloc[0])
            self._set_horizontal_log10(T, value)

    def reset_all_horizontal(self) -> None:
        if self.horizontal_current is None:
            return
        self.horizontal_current["log10_aT"] = self.horizontal_current["auto_log10_aT"].astype(float)
        self.horizontal_current["aT"] = 10.0 ** self.horizontal_current["log10_aT"]
        self.horizontal_current["aT_manual"] = False
        self.horizontal_current = self._recalculate_horizontal_derived(self.horizontal_current)
        self._propagate_horizontal_values_to_vertical()
        self.vertical_stale = self.vertical_current is not None
        self._refresh_horizontal_table()
        self._request_horizontal_plot_update()
        if self.vertical_current is not None:
            self._request_vertical_plot_update()
        self._update_vertical_warning()
        self.status_var.set("All horizontal shifts were reset to the calculated estimates.")

    def reset_selected_vertical(self) -> None:
        T = self.selected_vertical_temperature
        if self.vertical_current is None or not T:
            return
        mask = self.vertical_current["T_label"].astype(str) == str(T)
        if mask.any():
            value = float(self.vertical_current.loc[mask, "auto_log10_bT"].iloc[0])
            self._set_vertical_log10(T, value)

    def reset_all_vertical(self) -> None:
        if self.vertical_current is None:
            return
        self.vertical_current["log10_bT"] = self.vertical_current["auto_log10_bT"].astype(float)
        self.vertical_current["bT"] = 10.0 ** self.vertical_current["log10_bT"]
        self.vertical_current["bT_manual"] = False
        self.vertical_current = self._recalculate_vertical_derived(self.vertical_current)
        self.vertical_stale = False
        self._refresh_vertical_table()
        self._request_vertical_plot_update()
        self._update_vertical_warning()
        self.status_var.set("All vertical shifts were reset to the calculated estimates.")

    def _recalculate_horizontal_derived(self, df: pd.DataFrame) -> pd.DataFrame:
        out = df.copy()
        values = out.set_index(out["T_label"].astype(str))["log10_aT"].to_dict()
        local_values = []
        for _, row in out.iterrows():
            T = str(row["T_label"])
            anchor = row.get("match_to_aT", row.get("match_to"))
            if bool(row.get("is_reference", False)) or anchor is None or pd.isna(anchor):
                local = 0.0
            else:
                local = float(values[T]) - float(values[str(anchor)])
            local_values.append(local)
        out["log10_aT_local"] = local_values
        out["aT_local"] = 10.0 ** out["log10_aT_local"].astype(float)
        return out

    def _recalculate_vertical_derived(self, df: pd.DataFrame) -> pd.DataFrame:
        out = df.copy()
        values = out.set_index(out["T_label"].astype(str))["log10_bT"].to_dict()
        local_values = []
        for _, row in out.iterrows():
            T = str(row["T_label"])
            anchor = row.get("match_to_bT", row.get("match_to"))
            if bool(row.get("is_reference", False)) or anchor is None or pd.isna(anchor):
                local = 0.0
            else:
                local = float(values[T]) - float(values[str(anchor)])
            local_values.append(local)
        out["log10_bT_local"] = local_values
        out["bT_local"] = 10.0 ** out["log10_bT_local"].astype(float)
        return out

    def _propagate_horizontal_values_to_vertical(self) -> None:
        if self.horizontal_current is None or self.vertical_current is None:
            return
        h = self.horizontal_current.set_index("T_label")
        for column in [
            "log10_aT",
            "aT",
            "auto_log10_aT",
            "auto_aT",
            "aT_manual",
            "log10_aT_local",
            "aT_local",
        ]:
            if column in h.columns:
                self.vertical_current[column] = self.vertical_current["T_label"].map(h[column])

    # ------------------------------------------------------------------
    # Tables and plots
    # ------------------------------------------------------------------
    @staticmethod
    def _rgb_to_hex(rgb: tuple[float, float, float]) -> str:
        values = [int(np.clip(round(float(v) * 255.0), 0, 255)) for v in rgb]
        return "#{:02x}{:02x}{:02x}".format(*values)

    def _temperature_color(self, T: str) -> tuple[float, float, float]:
        if T in self.temperature_colors:
            return self.temperature_colors[T]
        if self.data:
            self.temperature_colors = get_temperature_colors(self.data)
            if T in self.temperature_colors:
                return self.temperature_colors[T]
        return (0.5, 0.5, 0.5)

    def _horizontal_row_dict(self, row: pd.Series) -> dict:
        T = str(row["T_label"])
        return {
            "iid": T,
            "color": self._rgb_to_hex(self._temperature_color(T)),
            "visible": "Shown" if self.horizontal_visible.get(T, True) else "Hidden",
            "T": T,
            "log10": _format_float(row["log10_aT"]),
            "factor": _format_float(row["aT"]),
            "auto": _format_float(row["auto_log10_aT"]),
            "loss": _format_float(row.get("loss_aT", np.nan)),
            "overlap": _format_float(row.get("n_overlap_aT", np.nan), digits=8),
            "manual": _bool_text(row.get("aT_manual", False)),
            "status": "OK" if bool(row.get("success_aT", True)) else "Failed",
            "tags": ("reference",) if bool(row.get("is_reference", False)) else (),
        }

    def _vertical_row_dict(self, row: pd.Series) -> dict:
        T = str(row["T_label"])
        return {
            "iid": T,
            "color": self._rgb_to_hex(self._temperature_color(T)),
            "visible": "Shown" if self.vertical_visible.get(T, True) else "Hidden",
            "T": T,
            "log10": _format_float(row["log10_bT"]),
            "factor": _format_float(row["bT"]),
            "auto": _format_float(row["auto_log10_bT"]),
            "loss": _format_float(row.get("loss_bT", np.nan)),
            "overlap": _format_float(row.get("n_overlap_bT", np.nan), digits=8),
            "manual": _bool_text(row.get("bT_manual", False)),
            "status": "OK" if bool(row.get("success_bT", True)) else "Failed",
            "tags": ("reference",) if bool(row.get("is_reference", False)) else (),
        }

    def toggle_horizontal_visibility(self, temperature: str, _column: str = "visible") -> None:
        T = str(temperature)
        self.horizontal_visible[T] = not self.horizontal_visible.get(T, True)
        self._horizontal_y_center_log = None
        self._update_horizontal_table_row(T)
        self._request_horizontal_plot_update()

    def toggle_vertical_visibility(self, temperature: str, _column: str = "visible") -> None:
        T = str(temperature)
        self.vertical_visible[T] = not self.vertical_visible.get(T, True)
        self._vertical_y_center_log = None
        self._update_vertical_table_row(T)
        self._request_vertical_plot_update()

    def _refresh_horizontal_view(self) -> None:
        self._refresh_horizontal_table()
        self._request_horizontal_plot_update()

    def _refresh_vertical_view(self) -> None:
        self._refresh_vertical_table()
        self._request_vertical_plot_update()
        self._update_vertical_warning()

    def _on_tab_changed(self, _event=None) -> None:
        current = self.notebook.select()
        if current == str(self.horizontal_tab) and self._horizontal_plot_dirty:
            self._draw_horizontal_plots()
        elif current == str(self.vertical_tab) and self._vertical_plot_dirty:
            self._draw_vertical_plots()

    def _request_horizontal_plot_update(self) -> None:
        self._horizontal_plot_dirty = True
        if self.notebook.select() == str(self.horizontal_tab):
            self._draw_horizontal_plots()

    def _request_vertical_plot_update(self) -> None:
        self._vertical_plot_dirty = True
        if self.notebook.select() == str(self.vertical_tab):
            self._draw_vertical_plots()

    def _update_vertical_warning(self) -> None:
        if self.vertical_stale:
            self.vertical_warning_var.set(
                "Horizontal shifts changed after the vertical-shift calculation. "
                "Current b_y values are retained, but rerunning the vertical shift is recommended."
            )
        else:
            self.vertical_warning_var.set("")

    def _refresh_horizontal_table(self) -> None:
        if self.horizontal_current is None:
            self.horizontal_table.clear()
            return
        ordered = self.horizontal_current.sort_values("T_value", na_position="last")
        rows = [self._horizontal_row_dict(row) for _, row in ordered.iterrows()]
        self.horizontal_table.populate(rows, self.selected_horizontal_temperature)

    def _refresh_vertical_table(self) -> None:
        if self.vertical_current is None:
            self.vertical_table.clear()
            return
        ordered = self.vertical_current.sort_values("T_value", na_position="last")
        rows = [self._vertical_row_dict(row) for _, row in ordered.iterrows()]
        self.vertical_table.populate(rows, self.selected_vertical_temperature)

    def _update_horizontal_table_row(self, T: str) -> None:
        if self.horizontal_current is None:
            return
        mask = self.horizontal_current["T_label"].astype(str) == str(T)
        if mask.any():
            self.horizontal_table.update_row(self._horizontal_row_dict(self.horizontal_current.loc[mask].iloc[0]))
            self.horizontal_table.select_iid(self.selected_horizontal_temperature)

    def _update_vertical_table_row(self, T: str) -> None:
        if self.vertical_current is None:
            return
        mask = self.vertical_current["T_label"].astype(str) == str(T)
        if mask.any():
            self.vertical_table.update_row(self._vertical_row_dict(self.vertical_current.loc[mask].iloc[0]))
            self.vertical_table.select_iid(self.selected_vertical_temperature)

    @staticmethod
    def _log_limits(arrays: list[np.ndarray], pad_fraction: float = 0.06) -> tuple[float, float]:
        valid_parts = []
        for array in arrays:
            a = np.asarray(array, dtype=float).ravel()
            a = a[np.isfinite(a) & (a > 0)]
            if a.size:
                valid_parts.append(a)
        if not valid_parts:
            return (1.0e-2, 1.0e2)
        values = np.concatenate(valid_parts)
        lo = float(np.min(values))
        hi = float(np.max(values))
        log_lo = math.log10(lo)
        log_hi = math.log10(hi)
        if np.isclose(log_lo, log_hi):
            return (10.0 ** (log_lo - 0.5), 10.0 ** (log_hi + 0.5))
        pad = max(0.04, (log_hi - log_lo) * pad_fraction)
        return (10.0 ** (log_lo - pad), 10.0 ** (log_hi + pad))

    @staticmethod
    def _axes_height_width_ratio(ax) -> float:
        position = ax.get_position()
        figure = ax.figure
        width = max(position.width * figure.get_figwidth(), 1.0e-9)
        height = max(position.height * figure.get_figheight(), 1.0e-9)
        return float(height / width)

    def _equal_decade_y_limits(
        self,
        ax,
        x_limits: tuple[float, float],
        series: list[tuple[np.ndarray, np.ndarray]],
        fallback: tuple[float, float] = (1.0e-2, 1.0e2),
        center_log: float | None = None,
    ) -> tuple[tuple[float, float], float]:
        x_min, x_max = x_limits
        x_decades = math.log10(x_max) - math.log10(x_min)

        # The master-curve axes use a fixed height/width ratio. Matching the
        # displayed y-decade span to this ratio makes one decade on x and y
        # occupy the same physical length. For example, 6 x-decades with a
        # 0.60 box aspect gives 3.6 y-decades.
        ax.set_box_aspect(MASTER_CURVE_BOX_ASPECT)
        y_decades = max(0.25, x_decades * MASTER_CURVE_BOX_ASPECT)

        visible_logs = []
        for x, y in series:
            x_arr = np.asarray(x, dtype=float)
            y_arr = np.asarray(y, dtype=float)
            mask = np.isfinite(x_arr) & np.isfinite(y_arr) & (y_arr > 0)
            mask &= (x_arr >= x_min) & (x_arr <= x_max)
            if np.any(mask):
                visible_logs.append(np.log10(y_arr[mask]))

        if center_log is None:
            if visible_logs:
                values = np.concatenate(visible_logs)
                low = float(np.min(values))
                high = float(np.max(values))
                margin = min(0.12, 0.04 * y_decades)
                center_log = 0.5 * ((low - margin) + (high + margin))
            else:
                center_log = 0.5 * (math.log10(fallback[0]) + math.log10(fallback[1]))

        lower_log = float(center_log) - 0.5 * y_decades
        upper_log = lower_log + y_decades
        return (10.0 ** lower_log, 10.0 ** upper_log), float(center_log)

    @staticmethod
    def _sample_marker_points(
        x: np.ndarray, y: np.ndarray, max_markers: int = 24
    ) -> np.ndarray:
        x_arr = np.asarray(x, dtype=float)
        y_arr = np.asarray(y, dtype=float)
        n = min(len(x_arr), len(y_arr))
        if n == 0:
            return np.empty((0, 2))
        if n <= max_markers:
            indices = np.arange(n)
        else:
            indices = np.unique(np.linspace(0, n - 1, max_markers, dtype=int))
        return np.column_stack([x_arr[indices], y_arr[indices]])

    @staticmethod
    def _linear_limits(values: np.ndarray, pad_fraction: float = 0.08) -> tuple[float, float]:
        a = np.asarray(values, dtype=float)
        a = a[np.isfinite(a)]
        if a.size == 0:
            return (-1.0, 1.0)
        lo = float(np.min(a))
        hi = float(np.max(a))
        if np.isclose(lo, hi):
            pad = max(0.5, abs(lo) * 0.1)
        else:
            pad = (hi - lo) * pad_fraction
        return (lo - pad, hi + pad)

    def _draw_empty_horizontal_plots(self) -> None:
        self._horizontal_artists = None
        self.horizontal_curve_ax.clear()
        self.horizontal_factor_ax.clear()
        self.horizontal_curve_ax.set_xscale("log")
        self.horizontal_curve_ax.set_yscale("log")
        self.horizontal_curve_ax.set_box_aspect(MASTER_CURVE_BOX_ASPECT)
        self.horizontal_curve_ax.set_title("Horizontal-shifted tan(delta)")
        self.horizontal_curve_ax.set_xlabel("omega * a_x")
        self.horizontal_curve_ax.set_ylabel("tan(delta)")
        try:
            self.horizontal_curve_ax.set_xlim(*self._plot_x_limits())
        except ValueError:
            pass
        self.horizontal_factor_ax.set_title("Condition vs horizontal shift")
        configure_condition_axis(self.horizontal_factor_ax, [], self.condition_axis_scale_var.get(),
                                 self._condition_axis_label())
        self.horizontal_factor_ax.set_ylabel("log10(a_x)")
        self._apply_factor_y_direction(self.horizontal_factor_ax)
        self._horizontal_plot_dirty = False

    def _draw_empty_vertical_plots(self) -> None:
        self._vertical_artists = None
        self.vertical_curve_ax.clear()
        self.vertical_factor_ax.clear()
        self.vertical_curve_ax.set_xscale("log")
        self.vertical_curve_ax.set_yscale("log")
        self.vertical_curve_ax.set_box_aspect(MASTER_CURVE_BOX_ASPECT)
        self.vertical_curve_ax.set_title("Horizontally and vertically shifted moduli")
        self.vertical_curve_ax.set_xlabel("omega * a_x")
        self.vertical_curve_ax.set_ylabel("G * b_y")
        try:
            self.vertical_curve_ax.set_xlim(*self._plot_x_limits())
        except ValueError:
            pass
        self.vertical_factor_ax.set_title("Condition vs vertical shift")
        configure_condition_axis(self.vertical_factor_ax, [], self.condition_axis_scale_var.get(),
                                 self._condition_axis_label())
        self.vertical_factor_ax.set_ylabel("log10(b_y)")
        self._apply_factor_y_direction(self.vertical_factor_ax)
        self._vertical_plot_dirty = False

    def _draw_horizontal_plots(self) -> None:
        if self.config and self.config.measurement != "dynamic":
            self._draw_scalar_plots("horizontal")
            return
        if not self.data or self.horizontal_current is None:
            self._draw_empty_horizontal_plots()
            return
        if self._horizontal_artists is None:
            self._initialize_horizontal_artists()
        self._update_horizontal_plot_artists()

    def _initialize_horizontal_artists(self) -> None:
        ax = self.horizontal_curve_ax
        factor_ax = self.horizontal_factor_ax
        ax.clear()
        factor_ax.clear()
        ax.set_xscale("log")
        ax.set_yscale("log")
        ax.set_box_aspect(MASTER_CURVE_BOX_ASPECT)
        ax.grid(False, which="both")
        factor_ax.grid(False)

        normal = LineCollection([], linewidths=1.0, linestyles="solid", zorder=1)
        ax.add_collection(normal)
        normal_markers = ax.scatter(
            [], [], marker="^", s=10, facecolors="none", linewidths=0.5, zorder=2
        )
        ref_line, = ax.plot([], [], linestyle="-", marker="^", markersize=3.6, linewidth=1.0, zorder=4)
        selected_line, = ax.plot([], [], linestyle="-", marker="^", markersize=3.3, linewidth=1.0, zorder=3)

        factor_line, = factor_ax.plot([], [], visible=False,)
        factor_points = factor_ax.scatter([], [], s=34, zorder=2)
        selected_point = factor_ax.scatter([], [], s=105, facecolors="none", edgecolors="black", linewidths=1.5, zorder=5)
        zero_line = factor_ax.axhline(0.0, linestyle=":", linewidth=1.0, zorder=0)

        self._horizontal_artists = {
            "normal": normal,
            "normal_markers": normal_markers,
            "ref_line": ref_line,
            "selected_line": selected_line,
            "factor_line": factor_line,
            "factor_points": factor_points,
            "selected_point": selected_point,
            "zero_line": zero_line,
        }

    def _update_horizontal_plot_artists(self) -> None:
        if not self.data or self.horizontal_current is None:
            return
        if self._horizontal_artists is None:
            self._initialize_horizontal_artists()

        artists = self._horizontal_artists
        shift_map = self.horizontal_current.set_index("T_label").to_dict(orient="index")
        temperatures = sorted(self.data.keys(), key=temp_sort_value)
        T_ref = normalize_condition_label(self.config.T_ref, self.config) if self.config else ""
        selected = self.selected_horizontal_temperature

        normal_segments = []
        normal_colors = []
        normal_marker_offsets = []
        normal_marker_colors = []
        visible_series = []
        ref_xy = None
        selected_xy = None
        for T in temperatures:
            if not self.horizontal_visible.get(str(T), True):
                continue
            d = self.data[T]
            x = np.asarray(d["omega"], dtype=float) * float(shift_map[T]["aT"])
            y = np.asarray(d["tan_delta"], dtype=float)
            xy = np.column_stack([x, y])
            visible_series.append((x, y))
            if T == T_ref:
                ref_xy = (T, x, y)
            elif T == selected:
                selected_xy = (T, x, y)
            else:
                color = self._temperature_color(T)
                normal_segments.append(xy)
                normal_colors.append(color)
                marker_points = self._sample_marker_points(x, y)
                if marker_points.size:
                    normal_marker_offsets.append(marker_points)
                    normal_marker_colors.extend([color] * len(marker_points))

        artists["normal"].set_segments(normal_segments)
        artists["normal"].set_color(normal_colors)
        if normal_marker_offsets:
            artists["normal_markers"].set_offsets(np.vstack(normal_marker_offsets))
            artists["normal_markers"].set_edgecolors(normal_marker_colors)
        else:
            artists["normal_markers"].set_offsets(np.empty((0, 2)))

        if ref_xy is None:
            artists["ref_line"].set_data([], [])
        else:
            T, x, y = ref_xy
            color = self._temperature_color(T)
            artists["ref_line"].set_data(x, y)
            artists["ref_line"].set_markevery(max(1, len(x) // 24))
            artists["ref_line"].set_color(color)
            artists["ref_line"].set_markerfacecolor("white")
            artists["ref_line"].set_markeredgecolor(color)

        if selected_xy is None or selected == T_ref:
            artists["selected_line"].set_data([], [])
        else:
            T, x, y = selected_xy
            color = self._temperature_color(T)
            artists["selected_line"].set_data(x, y)
            artists["selected_line"].set_markevery(max(1, len(x) // 24))
            artists["selected_line"].set_color(color)
            artists["selected_line"].set_markerfacecolor("white")
            artists["selected_line"].set_markeredgecolor(color)

        ax = self.horizontal_curve_ax
        x_limits = self._plot_x_limits()
        ax.set_xlim(*x_limits)
        y_limits, self._horizontal_y_center_log = self._equal_decade_y_limits(
            ax,
            x_limits,
            visible_series,
            center_log=self._horizontal_y_center_log,
        )
        ax.set_ylim(*y_limits)
        ax.set_title(f"Horizontal shift: tan(delta), reference={T_ref}")
        ax.set_xlabel("omega * a_x")
        ax.set_ylabel("tan(delta) = G'' / G'")

        self._update_factor_artists(
            factor_ax=self.horizontal_factor_ax,
            artists=artists,
            df=self.horizontal_current,
            value_column="log10_aT",
            selected_temperature=selected,
            ylabel="log10(a_x)",
            title="Condition vs horizontal shift factor",
            visibility_map=self.horizontal_visible,
        )
        self._horizontal_plot_dirty = False
        self.horizontal_canvas.draw_idle()

    def _draw_vertical_plots(self) -> None:
        if self.config and self.config.measurement != "dynamic":
            self._draw_scalar_plots("vertical")
            return
        if not self.data or self.vertical_current is None:
            self._draw_empty_vertical_plots()
            return
        if self._vertical_artists is None:
            self._initialize_vertical_artists()
        self._update_vertical_plot_artists()

    def _initialize_vertical_artists(self) -> None:
        ax = self.vertical_curve_ax
        factor_ax = self.vertical_factor_ax
        ax.clear()
        factor_ax.clear()
        ax.set_xscale("log")
        ax.set_yscale("log")
        ax.set_box_aspect(MASTER_CURVE_BOX_ASPECT)
        ax.grid(False, which="both")
        factor_ax.grid(False)

        gp_normal = LineCollection([], linewidths=1.05, linestyles="solid", zorder=1)
        gpp_normal = LineCollection([], linewidths=0.85, linestyles="solid", alpha=0.72, zorder=1)
        ax.add_collection(gp_normal)
        ax.add_collection(gpp_normal)
        gp_markers = ax.scatter([], [], marker="o", s=9, facecolors="none", linewidths=0.5, zorder=2)
        gpp_markers = ax.scatter([], [], marker="o", s=9, linewidths=0.4, alpha=0.72, zorder=2)

        ref_gp, = ax.plot([], [], linestyle="-", marker="o", markersize=3.5, linewidth=2.7, zorder=4)
        ref_gpp, = ax.plot([], [], linestyle="-", marker="o", markersize=3.5, linewidth=2.3, alpha=0.78, zorder=4)
        selected_gp, = ax.plot([], [], linestyle="-", marker="o", markersize=3.2, linewidth=2.0, zorder=3)
        selected_gpp, = ax.plot([], [], linestyle="-", marker="o", markersize=3.2, linewidth=1.7, alpha=0.78, zorder=3)

        factor_line, = factor_ax.plot([], [], visible=False,)
        factor_points = factor_ax.scatter([], [], s=34, zorder=2)
        selected_point = factor_ax.scatter([], [], s=105, facecolors="none", edgecolors="black", linewidths=1.5, zorder=5)
        zero_line = factor_ax.axhline(0.0, linestyle=":", linewidth=1.0, zorder=0)

        self._vertical_artists = {
            "gp_normal": gp_normal,
            "gpp_normal": gpp_normal,
            "gp_markers": gp_markers,
            "gpp_markers": gpp_markers,
            "ref_gp": ref_gp,
            "ref_gpp": ref_gpp,
            "selected_gp": selected_gp,
            "selected_gpp": selected_gpp,
            "factor_line": factor_line,
            "factor_points": factor_points,
            "selected_point": selected_point,
            "zero_line": zero_line,
        }

    @staticmethod
    def _set_modulus_line(line, x, y, color, filled: bool) -> None:
        line.set_data(x, y)
        line.set_markevery(max(1, len(x) // 24))
        line.set_color(color)
        line.set_markeredgecolor(color)
        line.set_markerfacecolor(color if filled else "white")

    def _update_vertical_plot_artists(self) -> None:
        if not self.data or self.vertical_current is None:
            return
        if self._vertical_artists is None:
            self._initialize_vertical_artists()

        artists = self._vertical_artists
        shift_map = self.vertical_current.set_index("T_label").to_dict(orient="index")
        temperatures = sorted(self.data.keys(), key=temp_sort_value)
        T_ref = normalize_condition_label(self.config.T_ref, self.config) if self.config else ""
        selected = self.selected_vertical_temperature

        gp_segments = []
        gpp_segments = []
        normal_colors = []
        gp_marker_offsets = []
        gpp_marker_offsets = []
        gp_marker_colors = []
        gpp_marker_colors = []
        visible_series = []
        ref_values = None
        selected_values = None
        for T in temperatures:
            if not self.vertical_visible.get(str(T), True):
                continue
            d = self.data[T]
            s = shift_map[T]
            x = np.asarray(d["omega"], dtype=float) * float(s["aT"])
            gp = np.asarray(d["Gp"], dtype=float) * float(s["bT"])
            gpp = np.asarray(d["Gpp"], dtype=float) * float(s["bT"])
            visible_series.extend([(x, gp), (x, gpp)])
            if T == T_ref:
                ref_values = (T, x, gp, gpp)
            elif T == selected:
                selected_values = (T, x, gp, gpp)
            else:
                color = self._temperature_color(T)
                gp_segments.append(np.column_stack([x, gp]))
                gpp_segments.append(np.column_stack([x, gpp]))
                normal_colors.append(color)
                gp_points = self._sample_marker_points(x, gp)
                gpp_points = self._sample_marker_points(x, gpp)
                if gp_points.size:
                    gp_marker_offsets.append(gp_points)
                    gp_marker_colors.extend([color] * len(gp_points))
                if gpp_points.size:
                    gpp_marker_offsets.append(gpp_points)
                    gpp_marker_colors.extend([color] * len(gpp_points))

        artists["gp_normal"].set_segments(gp_segments)
        artists["gp_normal"].set_color(normal_colors)
        artists["gpp_normal"].set_segments(gpp_segments)
        artists["gpp_normal"].set_color(normal_colors)
        if gp_marker_offsets:
            artists["gp_markers"].set_offsets(np.vstack(gp_marker_offsets))
            artists["gp_markers"].set_edgecolors(gp_marker_colors)
        else:
            artists["gp_markers"].set_offsets(np.empty((0, 2)))
        if gpp_marker_offsets:
            artists["gpp_markers"].set_offsets(np.vstack(gpp_marker_offsets))
            artists["gpp_markers"].set_facecolors(gpp_marker_colors)
            artists["gpp_markers"].set_edgecolors(gpp_marker_colors)
        else:
            artists["gpp_markers"].set_offsets(np.empty((0, 2)))

        if ref_values is None:
            artists["ref_gp"].set_data([], [])
            artists["ref_gpp"].set_data([], [])
        else:
            T, x, gp, gpp = ref_values
            color = self._temperature_color(T)
            self._set_modulus_line(artists["ref_gp"], x, gp, color, filled=False)
            self._set_modulus_line(artists["ref_gpp"], x, gpp, color, filled=True)

        if selected_values is None or selected == T_ref:
            artists["selected_gp"].set_data([], [])
            artists["selected_gpp"].set_data([], [])
        else:
            T, x, gp, gpp = selected_values
            color = self._temperature_color(T)
            self._set_modulus_line(artists["selected_gp"], x, gp, color, filled=False)
            self._set_modulus_line(artists["selected_gpp"], x, gpp, color, filled=True)

        ax = self.vertical_curve_ax
        x_limits = self._plot_x_limits()
        ax.set_xlim(*x_limits)
        y_limits, self._vertical_y_center_log = self._equal_decade_y_limits(
            ax,
            x_limits,
            visible_series,
            center_log=self._vertical_y_center_log,
        )
        ax.set_ylim(*y_limits)
        ax.set_title(f"Horizontal and vertical shifts, reference={T_ref}")
        ax.set_xlabel("omega * a_x")
        ax.set_ylabel("G * b_y")

        self._update_factor_artists(
            factor_ax=self.vertical_factor_ax,
            artists=artists,
            df=self.vertical_current,
            value_column="log10_bT",
            selected_temperature=selected,
            ylabel="log10(b_y)",
            title="Condition vs vertical shift factor",
            visibility_map=self.vertical_visible,
        )
        self._vertical_plot_dirty = False
        self.vertical_canvas.draw_idle()

    def _update_factor_artists(
        self,
        factor_ax,
        artists: dict,
        df: pd.DataFrame,
        value_column: str,
        selected_temperature: str | None,
        ylabel: str,
        title: str,
        visibility_map: dict[str, bool],
    ) -> None:
        ordered = df.sort_values("T_value", na_position="last").copy()
        T_values = ordered["T_value"].to_numpy(dtype=float)
        y = ordered[value_column].to_numpy(dtype=float)
        labels = ordered["T_label"].astype(str).tolist()
        numeric_x = np.all(np.isfinite(T_values))
        x = T_values if numeric_x else np.arange(len(ordered), dtype=float)

        visible_mask = np.array([visibility_map.get(T, True) for T in labels], dtype=bool)
        y_line = np.where(visible_mask, y, np.nan)
        artists["factor_line"].set_data(x, y_line)
        if np.any(visible_mask):
            visible_x = x[visible_mask]
            visible_y = y[visible_mask]
            visible_labels = [T for T, shown in zip(labels, visible_mask) if shown]
            artists["factor_points"].set_offsets(np.column_stack([visible_x, visible_y]))
            colors = [self._temperature_color(T) for T in visible_labels]
            artists["factor_points"].set_facecolors(colors)
            artists["factor_points"].set_edgecolors(colors)
        else:
            visible_y = np.array([], dtype=float)
            artists["factor_points"].set_offsets(np.empty((0, 2)))

        selected_mask = (
            ordered["T_label"].astype(str) == str(selected_temperature)
        ).to_numpy(dtype=bool, copy=True)
        selected_mask = selected_mask & visible_mask
        if selected_mask.any():
            i = int(np.flatnonzero(selected_mask)[0])
            artists["selected_point"].set_offsets(np.array([[x[i], y[i]]]))
        else:
            artists["selected_point"].set_offsets(np.empty((0, 2)))

        configure_condition_axis(factor_ax, labels, self.condition_axis_scale_var.get(),
                                 self._condition_axis_label())
        factor_ax.set_ylim(*self._linear_limits(np.append(visible_y, 0.0)))
        self._apply_factor_y_direction(factor_ax)
        factor_ax.set_title(title)
        factor_ax.set_xlabel(self._condition_axis_label())
        factor_ax.set_ylabel(ylabel)

    # ------------------------------------------------------------------
    # Export
    # ------------------------------------------------------------------
    def export_results(self) -> None:
        if not self._require_vertical_results():
            return
        try:
            self.config = self._calculation_config()
            output_dir = self.config.output_dir
            output_dir.mkdir(parents=True, exist_ok=True)
            self._save_path_settings()

            final_shifts = self.vertical_current.copy()
            if self.horizontal_current is not None:
                h = self.horizontal_current.set_index("T_label")
                for column in [
                    "log10_aT", "aT", "auto_log10_aT", "auto_aT", "aT_manual",
                    "log10_aT_local", "aT_local",
                ]:
                    if column in h.columns:
                        final_shifts[column] = final_shifts["T_label"].map(h[column])

            final_shifts["aT_source"] = np.where(final_shifts["aT_manual"], "manual", "automatic")
            final_shifts["bT_source"] = np.where(final_shifts["bT_manual"], "manual", "automatic")
            final_shifts["vertical_result_stale_after_aT_change"] = bool(self.vertical_stale)
            final_shifts["horizontal_visible"] = final_shifts["T_label"].astype(str).map(
                lambda T: self.horizontal_visible.get(T, True)
            )
            final_shifts["vertical_visible"] = final_shifts["T_label"].astype(str).map(
                lambda T: self.vertical_visible.get(T, True)
            )

            horizontal_export = self.horizontal_current.copy()
            horizontal_export["horizontal_visible"] = horizontal_export["T_label"].astype(str).map(
                lambda T: self.horizontal_visible.get(T, True)
            )
            public_shift_table(horizontal_export, self.config).to_csv(output_dir / "rheo_horizontal_shift_factors.csv", index=False)
            shifted_df, command_path = self.controller.export(final_shifts, self.config)
            if shifted_df is None:
                shifted_df = make_shifted_dataframe(self.data, final_shifts)
                shifted_df.to_csv(output_dir / "rheo_shifted_data.csv", index=False)

            # Ensure hidden tabs are synchronized before saving their figures.
            self._draw_horizontal_plots()
            self._draw_vertical_plots()
            self.horizontal_canvas.draw()
            self.vertical_canvas.draw()
            self.preview_figure.savefig(output_dir / "rheo_input_preview.png", dpi=200)
            self.horizontal_figure.savefig(output_dir / "rheo_horizontal_shift_gui.png", dpi=200)
            self.vertical_figure.savefig(output_dir / "rheo_vertical_shift_gui.png", dpi=200)

            message = (
                f"Export completed:\n{output_dir}\n\n"
                "- analysis_metadata.json\n"
                "- rheo_shift_factors.csv\n"
                "- rheo_shifted_data.csv\n"
                "- rheo_horizontal_shift_factors.csv\n"
                f"- {command_path.name}\n"
                "- rheo_input_preview.png\n"
                "- rheo_horizontal_shift_gui.png\n"
                "- rheo_vertical_shift_gui.png"
            )
            if self.vertical_stale:
                message += (
                    "\n\nWarning: a_x was changed after the vertical-shift calculation. "
                    "The currently displayed b_y values were exported unchanged."
                )
            messagebox.showinfo(APP_TITLE, message)
            self.status_var.set(f"Export completed: {output_dir}")
        except Exception as exc:
            self._show_error("Export failed", exc)

    # ------------------------------------------------------------------
    # Keyboard handling and validation
    # ------------------------------------------------------------------
    def _bind_keyboard_shortcuts(self) -> None:
        self.bind_all("<Left>", lambda event: self._handle_arrow_key(event, "left", False), add="+")
        self.bind_all("<Right>", lambda event: self._handle_arrow_key(event, "right", False), add="+")
        self.bind_all("<Up>", lambda event: self._handle_arrow_key(event, "up", False), add="+")
        self.bind_all("<Down>", lambda event: self._handle_arrow_key(event, "down", False), add="+")
        self.bind_all("<Shift-Left>", lambda event: self._handle_arrow_key(event, "left", True), add="+")
        self.bind_all("<Shift-Right>", lambda event: self._handle_arrow_key(event, "right", True), add="+")
        self.bind_all("<Shift-Up>", lambda event: self._handle_arrow_key(event, "up", True), add="+")
        self.bind_all("<Shift-Down>", lambda event: self._handle_arrow_key(event, "down", True), add="+")

    def _handle_arrow_key(self, event, key: str, shifted: bool):
        if event.widget.winfo_toplevel() != self:
            return None
        widget_class = event.widget.winfo_class()
        if widget_class in {"Entry", "TEntry", "TCombobox", "Spinbox", "TSpinbox", "Text"}:
            return None

        current_tab = self.notebook.select()
        if current_tab == str(self.horizontal_tab) and key in {"left", "right"}:
            self.adjust_horizontal(-1 if key == "left" else 1, shifted)
            return "break"
        if current_tab == str(self.vertical_tab) and key in {"up", "down"}:
            self.adjust_vertical(1 if key == "up" else -1, shifted)
            return "break"
        return None

    def _require_data(self) -> bool:
        if self.data is None or self.config is None:
            messagebox.showwarning(APP_TITLE, "Load the input data first.")
            return False
        return True

    def _require_horizontal_results(self) -> bool:
        if not self._require_data():
            return False
        if self.horizontal_current is None:
            messagebox.showwarning(APP_TITLE, "Run the horizontal-shift calculation first.")
            return False
        return True

    def _require_vertical_results(self) -> bool:
        if not self._require_horizontal_results():
            return False
        if self.vertical_current is None:
            messagebox.showwarning(APP_TITLE, "Run the vertical-shift calculation first.")
            return False
        return True

    def _is_reference(self, T: str) -> bool:
        return self.config is not None and str(T) == normalize_condition_label(self.config.T_ref, self.config)

    @staticmethod
    def _get_value(df: pd.DataFrame, T: str, column: str) -> float:
        mask = df["T_label"].astype(str) == str(T)
        if not mask.any():
            raise KeyError(f"Temperature {T} was not found.")
        return float(df.loc[mask, column].iloc[0])

    def _show_error(self, title: str, exc: Exception) -> None:
        traceback.print_exc()
        messagebox.showerror(APP_TITLE, f"{title}.\n\n{exc}")
        self.status_var.set(f"{title}: {exc}")


def run_app() -> None:
    app = TTSShiftGUI()
    app.mainloop()
