from __future__ import annotations

import re
import warnings
from pathlib import Path

import numpy as np
import pandas as pd

from .models import TTSConfig


def strip_temp_label_suffix(s: str, suffixes: tuple[str, ...]) -> str:
    s = str(s).strip()

    for suffix in sorted(suffixes, key=len, reverse=True):
        if suffix == "":
            continue
        if s.lower().endswith(suffix.lower()):
            s = s[: -len(suffix)].strip()
            break

    return s

def normalize_temp_label(
    x,
    strip_suffixes: tuple[str, ...] = ("°C", "℃", "degC", "C"),
) -> str:
    s = str(x).strip()
    s = strip_temp_label_suffix(s, strip_suffixes)
    s = s.strip(" _-:;[](){}")

    try:
        v = float(s)
        if np.isfinite(v) and v.is_integer():
            return str(int(v))
        return str(v)
    except ValueError:
        return s

def temp_sort_value(label) -> float:
    try:
        value = float(label)
        return value if np.isfinite(value) else np.inf
    except (ValueError, TypeError):
        return np.inf


def normalize_condition_label(label, config):
    if config.condition_name.lower() == "temperature":
        label = strip_temp_label_suffix(str(label).strip(), config.temp_label_strip_suffixes)
    text = str(label).strip()
    try:
        value = float(text)
        if np.isfinite(value):
            return str(int(value)) if value.is_integer() else str(value)
    except ValueError:
        pass
    return text


def read_rheology_table(path: Path, delimiter: str = "auto") -> pd.DataFrame:
    if delimiter == "auto":
        return pd.read_csv(path, sep=None, engine="python")
    if delimiter in ["space", "whitespace"]:
        return pd.read_csv(path, sep=r"\s+", engine="python")
    return pd.read_csv(path, sep=delimiter)

def read_raw_rheology_table(path: Path, delimiter: str = "auto") -> pd.DataFrame:
    """Read a CSV-like table without using any row as a header."""
    if delimiter == "auto":
        return pd.read_csv(path, sep=None, engine="python", header=None)
    if delimiter in ["space", "whitespace"]:
        return pd.read_csv(path, sep=r"\s+", engine="python", header=None)
    return pd.read_csv(path, sep=delimiter, header=None)

def convert_to_linear(values, input_scale: str) -> np.ndarray:
    values = np.asarray(values, dtype=float)
    if input_scale == "linear":
        return values
    if input_scale == "log10":
        return 10.0 ** values
    if input_scale == "ln":
        return np.exp(values)
    raise ValueError("input_scale must be 'linear', 'log10', or 'ln'.")

def _as_tuple_of_str(x) -> tuple[str, ...]:
    if x is None:
        return ("",)
    if isinstance(x, str):
        return (x,)
    return tuple(str(v) for v in x)

def _has_invalid_prefix_boundary(s: str, prefix: str) -> bool:
    """
    Avoid unintended matches such as prefix='Gp' matching 'Gpp_25'.
    Separators, digits, spaces, and symbols are accepted after the prefix.
    """
    if prefix == "":
        return False

    i = len(prefix)
    if i >= len(s):
        return False

    next_char = s[i]
    return bool(next_char.isalpha() or next_char in {"'", '"'})

def extract_temp_label_from_column(
    col,
    prefix: str,
    suffix: str = "",
    case_sensitive: bool = False,
    temp_label_strip_suffixes: tuple[str, ...] = ("°C", "℃", "degC", "C"),
) -> str | None:
    """
    Extract a temperature label from a column name.

    The column is interpreted as:
        prefix + arbitrary middle string containing temperature + suffix

    The last numeric value in the middle string is used as the temperature.
    Therefore, columns such as 'omega_25', 'omega_25C', 'w_sample_25C',
    and 'omega_sample_25C_rad_s' can be handled by changing prefix/suffix.
    """
    s = str(col).strip()
    prefix = str(prefix)
    suffix = str(suffix)

    s_cmp = s if case_sensitive else s.lower()
    prefix_cmp = prefix if case_sensitive else prefix.lower()
    suffix_cmp = suffix if case_sensitive else suffix.lower()

    if prefix_cmp and not s_cmp.startswith(prefix_cmp):
        return None

    if suffix_cmp and not s_cmp.endswith(suffix_cmp):
        return None

    if _has_invalid_prefix_boundary(s_cmp, prefix_cmp):
        return None

    start = len(prefix)
    end = len(s) - len(suffix) if suffix else len(s)
    if end < start:
        return None

    middle = s[start:end].strip()
    middle = strip_temp_label_suffix(middle, temp_label_strip_suffixes)

    numbers = re.findall(r"[-+]?(?:\d+\.\d*|\.\d+|\d+)", middle)
    if len(numbers) > 0:
        return normalize_temp_label(numbers[-1], strip_suffixes=())

    middle = middle.strip(" _-:;[](){}")
    if middle == "":
        return None

    return normalize_temp_label(middle, strip_suffixes=temp_label_strip_suffixes)

def build_column_map_by_temperature(
    df: pd.DataFrame,
    prefixes: tuple[str, ...],
    suffixes: tuple[str, ...],
    role_name: str,
    config: TTSConfig,
) -> dict[str, str]:
    col_map: dict[str, str] = {}
    prefixes = _as_tuple_of_str(prefixes)
    suffixes = _as_tuple_of_str(suffixes)

    for col in df.columns:
        for prefix in prefixes:
            matched_this_column = False
            for suffix in suffixes:
                T_label = extract_temp_label_from_column(
                    col=col,
                    prefix=prefix,
                    suffix=suffix,
                    case_sensitive=config.column_case_sensitive,
                    temp_label_strip_suffixes=config.temp_label_strip_suffixes,
                )

                if T_label is None:
                    continue

                matched_this_column = True

                if T_label in col_map:
                    warnings.warn(
                        f"Duplicate {role_name} column for T={T_label}: "
                        f"{col_map[T_label]} and {col}. Using {col_map[T_label]}."
                    )
                    break

                col_map[T_label] = col
                break

            if matched_this_column:
                break

    return col_map

def normalize_stacked_variable_label(x) -> str:
    """Normalize variable labels used in the stacked-header format."""
    s = str(x).strip()
    s_ascii = s.replace("′", "'").replace("″", "''").replace("ω", "w")
    s_key = re.sub(r"[\s_\-./]+", "", s_ascii).lower()

    if s_key in {"t", "time"}:
        return "t"
    if s_key in {"g", "g(t)", "relaxationmodulus"}:
        return "G"
    if s_key in {"j", "j(t)", "creepcompliance"}:
        return "J"
    if s_key in {"w", "omega", "angularfrequency"}:
        return "w"
    if s_key in {"g1", "gp", "gprime", "g'"}:
        return "G1"
    if s_key in {"g2", "gpp", "gdoubleprime", "g''"}:
        return "G2"

    return s

def _first_valid_cell(values) -> str:
    for v in values:
        if pd.isna(v):
            continue
        s = str(v).strip()
        if s != "":
            return s
    return ""

def build_trace_map_from_stacked_header(raw: pd.DataFrame, config: TTSConfig) -> pd.DataFrame:
    """
    Build a table linking temperature, variable type, and IGOR trace/wave names.

    Expected input rows are defined by TTSConfig:
        temperature row, variable row, trace row, numeric-data start row.
    """
    n_cols = raw.shape[1]
    block_size = int(config.stacked_header_block_size)
    expected_vars = tuple(normalize_stacked_variable_label(v) for v in config.stacked_header_expected_vars)

    if block_size <= 0:
        raise ValueError("stacked_header_block_size must be positive.")
    if len(expected_vars) != block_size:
        raise ValueError("stacked_header_expected_vars length must match stacked_header_block_size.")
    if n_cols % block_size != 0:
        raise ValueError(
            f"The number of columns ({n_cols}) must be a multiple of "
            f"stacked_header_block_size ({block_size})."
        )

    rows = []

    for block_index, start_col in enumerate(range(0, n_cols, block_size)):
        cols = list(range(start_col, start_col + block_size))
        T_raw = _first_valid_cell(raw.iloc[config.stacked_header_temperature_row, cols])
        T_label = normalize_condition_label(T_raw, config)

        if T_label == "":
            raise ValueError(f"Block {block_index}: temperature label is empty.")

        vars_found = [
            normalize_stacked_variable_label(raw.iat[config.stacked_header_variable_row, c])
            for c in cols
        ]

        if tuple(vars_found) != expected_vars:
            raise ValueError(
                f"Block {block_index}, T={T_label}: variable row must be "
                f"{expected_vars}, but got {tuple(vars_found)}."
            )

        trace_names = [str(raw.iat[config.stacked_header_trace_row, c]).strip() for c in cols]

        for local_col, var, trace_name in zip(cols, vars_found, trace_names):
            if trace_name == "" or trace_name.lower() == "nan":
                raise ValueError(f"Block {block_index}, T={T_label}, var={var}: trace name is empty.")

            rows.append({
                "T_label": T_label,
                "T_value": temp_sort_value(T_label),
                "var": var,
                "trace": trace_name,
                "source_column_index": int(local_col),
                "block_index": int(block_index),
            })

    trace_map = pd.DataFrame(rows)

    duplicates = trace_map.duplicated(subset=["T_label", "var"], keep=False)
    if duplicates.any():
        bad = trace_map.loc[duplicates, ["T_label", "var", "trace"]]
        raise ValueError("Duplicate T_label/var combinations were found:\n" + bad.to_string(index=False))

    return trace_map

def parse_stacked_header_csv(config: TTSConfig) -> tuple[dict[str, dict[str, np.ndarray]], pd.DataFrame]:
    """
    Parse the stacked-header input format.

    CSV structure:
        row 0: temperature labels
        row 1: w, G1, G2 repeated
        row 2: IGOR trace/wave names
        row 3 onward: numeric data
    """
    raw = read_raw_rheology_table(config.data_path, delimiter=config.input_delimiter)

    return parse_stacked_header_table(raw, config)


def parse_stacked_header_table(raw: pd.DataFrame, config: TTSConfig, *, strict: bool = False):
    """Parse the same three-header-row layout from a file or the editor."""
    if config.measurement != "dynamic":
        from .scalar import parse_scalar_table
        return parse_scalar_table(raw, config, strict=strict)
    min_rows = max(
        config.stacked_header_temperature_row,
        config.stacked_header_variable_row,
        config.stacked_header_trace_row,
        config.stacked_header_data_start_row,
    ) + 1
    if raw.shape[0] < min_rows:
        raise ValueError(
            f"The stacked-header input requires at least {min_rows} rows, "
            f"but the file has {raw.shape[0]} rows."
        )

    trace_map = build_trace_map_from_stacked_header(raw, config)
    numeric_raw = raw.iloc[config.stacked_header_data_start_row:, :].reset_index(drop=True)

    data: dict[str, dict[str, np.ndarray]] = {}

    for T_label, block in trace_map.groupby("T_label", sort=False):
        col_by_var = {
            str(row["var"]): int(row["source_column_index"])
            for _, row in block.iterrows()
        }
        trace_by_var = {
            str(row["var"]): str(row["trace"])
            for _, row in block.iterrows()
        }

        missing = {"w", "G1", "G2"} - set(col_by_var)
        if missing:
            raise ValueError(f"T={T_label}: missing variables in stacked header: {sorted(missing)}")

        tmp = numeric_raw[[col_by_var["w"], col_by_var["G1"], col_by_var["G2"]]].copy()
        tmp.columns = ["omega", "Gp", "Gpp"]
        tmp = tmp.replace(r"(?i)^\s*(?:nan)?\s*$", np.nan, regex=True)
        if strict:
            complete = tmp.notna().all(axis=1)
            numbers = tmp.apply(pd.to_numeric, errors="coerce")
            converted = convert_to_linear(numbers.to_numpy(), config.input_scale)
            valid_rows = np.isfinite(converted).all(axis=1) & (converted > 0).all(axis=1)
            bad = complete.to_numpy() & ~valid_rows
            if bad.any():
                row = int(np.flatnonzero(bad)[0]) + config.stacked_header_data_start_row + 1
                raise ValueError(f"Row {row}, T={T_label}: enter three finite numeric values "
                                 "that are positive after scale conversion, rows with missing values are skipped.")
            if int(valid_rows.sum()) < 4:
                raise ValueError(f"T={T_label}: at least 4 data points are required.")
        tmp = tmp.apply(pd.to_numeric, errors="coerce")
        tmp = tmp.replace([np.inf, -np.inf], np.nan).dropna()

        omega = convert_to_linear(tmp["omega"].to_numpy(), config.input_scale)
        Gp = convert_to_linear(tmp["Gp"].to_numpy(), config.input_scale)
        Gpp = convert_to_linear(tmp["Gpp"].to_numpy(), config.input_scale)

        valid = np.isfinite(omega) & np.isfinite(Gp) & np.isfinite(Gpp)
        valid &= (omega > 0) & (Gp > 0) & (Gpp > 0)

        omega = omega[valid]
        Gp = Gp[valid]
        Gpp = Gpp[valid]

        if len(omega) < 4:
            warnings.warn(f"Skipped T={T_label}: fewer than 4 valid points.")
            continue

        order = np.argsort(omega)
        omega = omega[order]
        Gp = Gp[order]
        Gpp = Gpp[order]
        tan_delta = Gpp / Gp

        data[str(T_label)] = {
            "omega": omega,
            "Gp": Gp,
            "Gpp": Gpp,
            "x": np.log10(omega),
            "logGp": np.log10(Gp),
            "logGpp": np.log10(Gpp),
            "tan_delta": tan_delta,
            "logTanDelta": np.log10(tan_delta),
            "trace_w": trace_by_var["w"],
            "trace_G1": trace_by_var["G1"],
            "trace_G2": trace_by_var["G2"],
        }

    if len(data) == 0:
        raise ValueError(
            "No valid temperature blocks were found. "
            "Check the stacked-header rows, delimiter, and input scale."
        )

    trace_map = trace_map[trace_map["T_label"].isin(data.keys())].reset_index(drop=True)
    return data, trace_map

def build_trace_map_from_column_names(
    omega_cols: dict[str, str],
    g1_cols: dict[str, str],
    g2_cols: dict[str, str],
) -> pd.DataFrame:
    """Build a trace map from the legacy column-name input format."""
    rows = []
    for T_label, omega_col in omega_cols.items():
        if T_label not in g1_cols or T_label not in g2_cols:
            continue
        for var, trace in [("w", omega_col), ("G1", g1_cols[T_label]), ("G2", g2_cols[T_label])]:
            rows.append({
                "T_label": T_label,
                "T_value": temp_sort_value(T_label),
                "var": var,
                "trace": str(trace),
                "source_column_index": np.nan,
                "block_index": np.nan,
            })
    return pd.DataFrame(rows)

def parse_rheology_input(config: TTSConfig) -> tuple[dict[str, dict[str, np.ndarray]], pd.DataFrame]:
    """Parse rheology input and return both data and trace metadata."""
    fmt = str(config.input_format).lower()

    if fmt in {"column_names", "columns", "legacy"}:
        if config.measurement != "dynamic" or config.condition_name.lower() != "temperature":
            raise ValueError("Use stacked_header input for time-domain or non-temperature data.")
        data = parse_rheology_csv(config)
        df = read_rheology_table(config.data_path, delimiter=config.input_delimiter)
        omega_cols = build_column_map_by_temperature(
            df=df,
            prefixes=config.omega_col_prefixes,
            suffixes=config.omega_col_suffixes,
            role_name="omega",
            config=config,
        )
        g1_cols = build_column_map_by_temperature(
            df=df,
            prefixes=config.gp_col_prefixes,
            suffixes=config.gp_col_suffixes,
            role_name="G1/Gp",
            config=config,
        )
        g2_cols = build_column_map_by_temperature(
            df=df,
            prefixes=config.gpp_col_prefixes,
            suffixes=config.gpp_col_suffixes,
            role_name="G2/Gpp",
            config=config,
        )
        trace_map = build_trace_map_from_column_names(omega_cols, g1_cols, g2_cols)
        trace_map = trace_map[trace_map["T_label"].isin(data.keys())].reset_index(drop=True)
        return data, trace_map

    if fmt in {"stacked_header", "three_row_header", "3row_header"}:
        return parse_stacked_header_csv(config)

    raise ValueError(
        "input_format must be 'column_names' or 'stacked_header'."
    )

def parse_rheology_csv(config: TTSConfig) -> dict[str, dict[str, np.ndarray]]:
    df = read_rheology_table(config.data_path, delimiter=config.input_delimiter)

    omega_cols = build_column_map_by_temperature(
        df=df,
        prefixes=config.omega_col_prefixes,
        suffixes=config.omega_col_suffixes,
        role_name="omega",
        config=config,
    )

    g1_cols = build_column_map_by_temperature(
        df=df,
        prefixes=config.gp_col_prefixes,
        suffixes=config.gp_col_suffixes,
        role_name="G1/Gp",
        config=config,
    )

    g2_cols = build_column_map_by_temperature(
        df=df,
        prefixes=config.gpp_col_prefixes,
        suffixes=config.gpp_col_suffixes,
        role_name="G2/Gpp",
        config=config,
    )

    data = {}

    for T_label, omega_col in omega_cols.items():
        g1_col = g1_cols.get(T_label)
        g2_col = g2_cols.get(T_label)

        if g1_col is None or g2_col is None:
            warnings.warn(
                f"Skipped T={T_label}: corresponding Gp/Gpp columns were not found."
            )
            continue

        tmp = df[[omega_col, g1_col, g2_col]].copy()
        tmp.columns = ["omega", "Gp", "Gpp"]
        tmp = tmp.apply(pd.to_numeric, errors="coerce")
        tmp = tmp.replace([np.inf, -np.inf], np.nan).dropna()

        omega = convert_to_linear(tmp["omega"].to_numpy(), config.input_scale)
        Gp = convert_to_linear(tmp["Gp"].to_numpy(), config.input_scale)
        Gpp = convert_to_linear(tmp["Gpp"].to_numpy(), config.input_scale)

        valid = np.isfinite(omega) & np.isfinite(Gp) & np.isfinite(Gpp)
        valid &= (omega > 0) & (Gp > 0) & (Gpp > 0)

        omega = omega[valid]
        Gp = Gp[valid]
        Gpp = Gpp[valid]

        if len(omega) < 4:
            warnings.warn(f"Skipped T={T_label}: fewer than 4 valid points.")
            continue

        order = np.argsort(omega)
        omega = omega[order]
        Gp = Gp[order]
        Gpp = Gpp[order]
        tan_delta = Gpp / Gp

        data[T_label] = {
            "omega": omega,
            "Gp": Gp,
            "Gpp": Gpp,
            "x": np.log10(omega),
            "logGp": np.log10(Gp),
            "logGpp": np.log10(Gpp),
            "tan_delta": tan_delta,
            "logTanDelta": np.log10(tan_delta),
        }

    if len(data) == 0:
        raise ValueError(
            "No valid temperature blocks were found. "
            "Check column names, delimiter, input scale, and column prefix/suffix settings."
        )

    return data
