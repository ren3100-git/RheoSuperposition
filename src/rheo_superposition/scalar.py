"""Single-response time-domain data and logarithmic curve registration.

Internal legacy column names aT/bT represent direct x/y multipliers, not
physical time-temperature shift factors. Public exports define a_x/b_y.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from .losses import custom_composite_loss
from .readers import (build_trace_map_from_stacked_header, convert_to_linear,
                      normalize_condition_label, temp_sort_value)


def parse_scalar_table(raw, config, *, strict=False):
    start = config.stacked_header_data_start_row
    if len(raw) <= max(start, config.stacked_header_trace_row,
                       config.stacked_header_variable_row, config.stacked_header_temperature_row):
        raise ValueError("Three header rows and at least four data rows are required.")
    traces = build_trace_map_from_stacked_header(raw, config)
    data = {}
    for label, block in traces.groupby('T_label', sort=False):
        cols = block.set_index('var')['source_column_index']
        values = raw.iloc[start:, [int(cols['t']), int(cols[config.response_name])]]
        values = values.replace(r'(?i)^\s*(?:nan)?\s*$', np.nan, regex=True)
        complete = values.notna().all(axis=1).to_numpy()
        numbers = values.apply(pd.to_numeric, errors='coerce').to_numpy(dtype=float)
        with np.errstate(over='ignore', invalid='ignore'):
            numbers = convert_to_linear(numbers, config.input_scale)
        valid = np.isfinite(numbers).all(axis=1) & (numbers > 0).all(axis=1)
        if np.any(complete & ~valid):
            row = int(np.flatnonzero(complete & ~valid)[0]) + start + 1
            raise ValueError(f"Row {row}, condition {label}: both values must be finite and positive after conversion. Rows with missing values are skipped.")
        numbers = numbers[valid]
        if len(numbers) < 4 or len(np.unique(numbers[:, 0])) < 4:
            raise ValueError(f"Condition {label}: at least four distinct positive times are required.")
        numbers = numbers[np.argsort(numbers[:, 0])]
        data[label] = dict(time=numbers[:, 0], response=numbers[:, 1],
                           x=np.log10(numbers[:, 0]), log_response=np.log10(numbers[:, 1]),
                           measurement=config.measurement, response_name=config.response_name)
    if not data:
        raise ValueError('No valid condition blocks were found.')
    return data, traces


def fit_curve(ref, target, config, *, fixed_x=None, fixed_y=None):
    """Profile out vertical displacement and search all feasible x intervals."""
    from scipy.optimize import minimize_scalar
    from .shifts import make_cubic_spline
    spline, (xmin, xmax), _, _ = make_cubic_spline(ref['x'], ref['log_response'])
    x, y = np.asarray(target['x']), np.asarray(target['log_response'])
    lower, upper = config.log10_aT_bounds
    lower = max(lower, xmin - np.max(x))
    upper = min(upper, xmax - np.min(x))
    by = config.log10_bT_bounds

    def evaluate(dx):
        mask = (x + dx >= xmin) & (x + dx <= xmax)
        n = int(mask.sum())
        if n < config.min_overlap_points:
            return np.inf, np.nan, n, False
        residual = y[mask] - spline(x[mask] + dx)
        def loss(dy):
            return custom_composite_loss(residual + dy, b=config.loss_b, c=config.loss_c)
        if fixed_y is None:
            result = minimize_scalar(loss, bounds=by, method='bounded', options={'xatol': 1e-9})
            dy = float(result.x)
        else:
            dy = float(fixed_y)
        slopes = spline(x[mask] + dx, 1)
        ambiguous = bool(fixed_x is None and fixed_y is None and np.std(slopes) < 1e-3)
        if fixed_x is None and fixed_y is not None and np.max(np.abs(slopes)) < 1e-6:
            ambiguous = True
        return float(loss(dy)), dy, n, ambiguous

    if fixed_x is not None:
        dx = float(fixed_x)
    elif lower >= upper:
        dx = np.nan
    else:
        # Include overlap boundaries so narrow feasible regions cannot be missed.
        n = config.min_overlap_points
        xs = np.sort(x)
        edges = np.concatenate(([lower, upper], xmin-xs[:len(xs)-n+1], xmax-xs[n-1:])) if len(xs) >= n else np.array([lower, upper])
        edges = np.unique(np.clip(edges, lower, upper))
        grid = np.unique(np.concatenate((np.linspace(lower, upper, 241), edges, (edges[:-1]+edges[1:])/2)))
        scores = np.array([evaluate(v)[0] for v in grid])
        candidates = [(scores[i], grid[i]) for i in np.argsort(scores)[:8] if np.isfinite(scores[i])]
        for _, guess in candidates.copy():
            i = int(np.searchsorted(grid, guess))
            lo, hi = grid[max(0, i-1)], grid[min(len(grid)-1, i+1)]
            if hi > lo:
                result = minimize_scalar(lambda dx: evaluate(dx)[0], bounds=(lo, hi), method='bounded', options={'xatol': 1e-8})
                if np.isfinite(result.fun):
                    candidates.append((float(result.fun), float(result.x)))
        dx = min(candidates)[1] if candidates else np.nan
    loss, dy, count, ambiguous = evaluate(dx) if np.isfinite(dx) else (np.inf, np.nan, 0, False)
    success = bool(np.isfinite(loss) and not ambiguous)
    return dict(dx=dx, dy=dy, loss=loss, count=count, success=success,
                ambiguous=ambiguous, diagnostic='Shifts cannot be separated; fix one factor.' if ambiguous else ('' if success else 'Insufficient overlap or no valid fit.'))


def scalar_horizontal(data, config):
    from .shifts import (normalize_shift_mode, get_temperature_fit_order, add_boundary_flags,
                         make_fixed_aT_result, make_fixed_bT_result)
    mode = normalize_shift_mode(config.shift_mode)
    reference = normalize_condition_label(config.T_ref, config)
    if reference not in data:
        raise ValueError('Reference condition was not found in the data.')
    rows = {}
    for order, label in enumerate([reference] + get_temperature_fit_order(data, reference)):
        is_ref = label == reference
        fitted = [k for k, r in rows.items() if r['success_aT'] and r['success_bT']]
        anchor = None if is_ref else min(fitted, key=lambda k: abs(temp_sort_value(k)-temp_sort_value(label))) if np.isfinite(temp_sort_value(label)) and any(np.isfinite(temp_sort_value(k)) for k in fitted) else (fitted[-1] if fitted else reference)
        if is_ref:
            fit = dict(dx=0., dy=0., loss=0., count=len(data[label]['x']), success=True, ambiguous=False, diagnostic='')
        elif mode == 'none':
            fit = dict(dx=config.fixed_log10_aT, dy=config.fixed_log10_bT,
                       loss=np.nan, count=0, success=True, ambiguous=False, diagnostic='Fixed transformation; no fit performed.')
        else:
            ar = rows[anchor]
            ref = dict(x=data[anchor]['x'] + ar['log10_aT'], log_response=data[anchor]['log_response'] + ar['log10_bT'])
            fit = fit_curve(ref, data[label], config,
                            fixed_x=config.fixed_log10_aT if mode in {'vertical_only', 'none'} else None,
                            fixed_y=config.fixed_log10_bT if mode in {'horizontal_only', 'none'} else None)
        dx, dy = fit['dx'], fit['dy']
        row = dict(T_label=label, T_value=temp_sort_value(label),
                   **make_fixed_aT_result(dx, fit['count']), **make_fixed_bT_result(dy, fit['count']))
        row.update(loss_aT=fit['loss'], loss_bT=fit['loss'], success_aT=fit['success'], success_bT=fit['success'],
                   aT_search_lower=config.log10_aT_bounds[0], aT_search_upper=config.log10_aT_bounds[1],
                   bT_search_lower=config.log10_bT_bounds[0], bT_search_upper=config.log10_bT_bounds[1],
                   aT_is_fixed=is_ref or mode in {'vertical_only','none'}, bT_is_fixed=is_ref or mode in {'horizontal_only','none'},
                   match_to=anchor, match_to_aT=anchor, match_to_bT=anchor, fit_order=order, is_reference=is_ref,
                   log10_aT_local=0. if is_ref else dx-rows[anchor]['log10_aT'],
                   log10_bT_local=0. if is_ref else dy-rows[anchor]['log10_bT'],
                   shift_mode=mode, calculation_stage='joint' if mode == 'both' else mode,
                   identifiable=not fit['ambiguous'], diagnostic=fit['diagnostic'])
        row['aT_local'] = 10. ** row['log10_aT_local']
        row['bT_local'] = 10. ** row['log10_bT_local']
        rows[label] = row
    return add_boundary_flags(pd.DataFrame(rows.values()))


def scalar_vertical(data, horizontal, config):
    from .shifts import add_boundary_flags, normalize_shift_mode
    mode = normalize_shift_mode(config.shift_mode)
    reference = normalize_condition_label(config.T_ref, config)
    if set(horizontal.T_label) != set(data) or reference not in data:
        raise ValueError('Condition mismatch. Re-run horizontal shifts.')
    out = horizontal.copy()
    if mode == 'none':
        return add_boundary_flags(out)
    completed = {}
    for index in out.sort_values('fit_order').index:
        row = out.loc[index]
        label = str(row.T_label)
        if bool(row.is_reference):
            completed[label] = (0., 0.)
            continue
        if not row.success_aT:
            out.loc[index, 'success_bT'] = False
            continue
        anchor = row.match_to_aT if row.match_to_aT in completed else reference
        ax, ay = completed[anchor]
        ref = dict(x=data[anchor]['x']+ax, log_response=data[anchor]['log_response']+ay)
        fit = fit_curve(ref, data[label], config, fixed_x=float(row.log10_aT),
                        fixed_y=config.fixed_log10_bT if mode in {'horizontal_only','none'} else None)
        dy = fit['dy']
        for key, value in dict(log10_bT=dy, bT=10.**dy, loss_bT=fit['loss'], success_bT=fit['success'],
                               n_overlap_bT=fit['count'], match_to_bT=anchor,
                               log10_bT_local=dy-ay, bT_local=10.**(dy-ay), diagnostic=fit['diagnostic']).items():
            out.loc[index,key] = value
        if fit['success']:
            completed[label] = (float(row.log10_aT), dy)
    return add_boundary_flags(out)


def scalar_shifted_dataframe(data, shifts):
    rows = []
    factors = shifts.set_index('T_label')
    for label, d in data.items():
        row = factors.loc[label]
        for time, response in zip(d['time'], d['response']):
            rows.append(dict(condition=label, time=time, response=response,
                             response_name=d['response_name'], measurement=d['measurement'],
                             a_x=row.aT, b_y=row.bT, time_shifted=time*row.aT,
                             response_shifted=response*row.bT,
                             success=bool(row.success_aT and row.success_bT)))
    return pd.DataFrame(rows)
