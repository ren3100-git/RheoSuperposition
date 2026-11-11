from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import Mock
import json
import numpy as np
import pandas as pd
import pytest
from matplotlib.figure import Figure

from rheo_superposition.models import TTSConfig
from rheo_superposition.readers import parse_stacked_header_table, normalize_condition_label, temp_sort_value
from rheo_superposition.shifts import estimate_shift_factors, estimate_horizontal_shift_factors
from rheo_superposition.scalar import fit_curve
from rheo_superposition.exporters import save_tts_outputs, build_igor_trace_shift_commands
from rheo_superposition.plotting import draw_unshifted_preview
from rheo_superposition.gui.input_table import InputTable


def raw_data(kind='relaxation', scale='linear', dx=0.4, dy=-0.25):
    x = np.linspace(-2, 2, 65)
    fn = (lambda z: 1.6 - 0.4*z - 0.12*z*z) if kind == 'relaxation' else (lambda z: -1.6 + 0.4*z + 0.12*z*z)
    y = 'G' if kind == 'relaxation' else 'J'
    values = np.array([10**x, 10**fn(x), 10**x, 10**(fn(x+dx)-dy)]).T
    if scale == 'log10': values = np.log10(values)
    if scale == 'ln': values = np.log(values)
    return pd.DataFrame([['sampleC', '', 'sample2', ''], ['t', y, 't', y], ['t0', 'y0', 't1', 'y1']] + values.tolist())


def config(**kwargs):
    return TTSConfig(measurement=kwargs.pop('measurement','relaxation'), condition_name='Concentration', condition_unit='%', T_ref='sampleC', log10_aT_bounds=(-1,1), log10_bT_bounds=(-1,1), **kwargs)


@pytest.mark.parametrize('kind', ['relaxation','creep'])
@pytest.mark.parametrize('scale', ['linear','log10','ln'])
def test_time_domain_end_to_end(kind, scale, tmp_path):
    cfg = config(measurement=kind, input_scale=scale, output_dir=tmp_path)
    data, traces = parse_stacked_header_table(raw_data(kind, scale), cfg, strict=True)
    shifts = estimate_shift_factors(data, cfg)
    target = shifts.set_index('T_label').loc['sample2']
    assert target.success_aT and target.success_bT
    assert target.log10_aT == pytest.approx(.4, abs=2e-4)
    assert target.log10_bT == pytest.approx(-.25, abs=2e-4)
    shifted = save_tts_outputs(data, shifts, cfg)
    assert np.allclose(shifted.query("condition == 'sample2'").time_shifted, data['sample2']['time'] * 10**.4, rtol=1e-3)
    factors = pd.read_csv(tmp_path/'rheo_shift_factors.csv')
    assert {'a_x','b_y','condition','reference_condition','x_transform'} <= set(factors)
    assert json.loads((tmp_path/'analysis_metadata.json').read_text())['measurement'] == kind
    text = build_igor_trace_shift_commands(traces, shifts, input_scale=scale, measurement=kind)
    assert '(y1)' in text and '(t1)' not in text
    fig = Figure()
    a,b = fig.subplots(2)
    draw_unshifted_preview(a,b,data)
    assert not b.get_visible() and len(a.lines) == 2


@pytest.mark.parametrize('mode', ['horizontal_only','vertical_only','none'])
def test_fixed_modes(mode):
    cfg=config(shift_mode=mode, fixed_log10_aT=.4, fixed_log10_bT=-.25)
    data,_=parse_stacked_header_table(raw_data(),cfg)
    target=estimate_shift_factors(data,cfg).set_index('T_label').loc['sample2']
    assert target.log10_aT == pytest.approx(.4,abs=2e-4)
    assert target.log10_bT == pytest.approx(-.25,abs=2e-4)
    assert target.success_aT and target.success_bT


def test_power_law_ambiguity_and_fixed_y_recovery():
    x=np.linspace(-2,2,81)
    ref=dict(x=x,log_response=.5*x)
    target=dict(x=x,log_response=.5*(x+.4))
    ambiguous=fit_curve(ref,target,config())
    assert ambiguous['ambiguous'] and not ambiguous['success']
    recovered=fit_curve(ref,target,config(),fixed_y=0)
    assert recovered['success'] and recovered['dx']==pytest.approx(.4,abs=1e-4)


def test_no_overlap_is_failure():
    ref=dict(x=np.linspace(0,1,20), log_response=np.linspace(0,1,20)**2)
    target=dict(x=np.linspace(10,11,20),log_response=np.linspace(0,1,20)**2)
    assert not fit_curve(ref,target,config())['success']


@pytest.mark.parametrize('bad', [0, -1, 'bad', np.inf])
def test_invalid_pairs_rejected(bad):
    raw=raw_data(); raw.iloc[4,1]=bad
    with pytest.raises(ValueError,match='Row 5'):
        parse_stacked_header_table(raw, config(), strict=True)


def test_duplicate_conditions_and_times_rejected():
    raw=raw_data(); raw.iloc[0,2]='sampleC'
    with pytest.raises(ValueError,match='Duplicate'):
        parse_stacked_header_table(raw, config())
    raw=raw_data(); raw.iloc[3:,0]=1
    with pytest.raises(ValueError,match='distinct'):
        parse_stacked_header_table(raw,config())


def test_condition_normalization():
    assert normalize_condition_label('sampleC', config())=='sampleC'
    assert normalize_condition_label('-20 °C', TTSConfig())=='-20'
    assert normalize_condition_label('1e-3', config())=='0.001'
    assert np.isinf(temp_sort_value('sample2'))
    assert temp_sort_value('1e-3')==.001


def test_delete_pair(monkeypatch):
    table=SimpleNamespace(rows=[['A','','B',''],['t','J','t','J'],['a','b','c','d']],
                          variables=('t','J'),cell=(0,2),commit=Mock(),render=Mock(),changed=Mock())
    monkeypatch.setattr('rheo_superposition.gui.input_table.messagebox.askyesno', lambda *a,**k:True)
    InputTable.delete_block(table)
    assert table.rows==[['A',''],['t','J'],['a','b']]


def test_categorical_colors_are_distinct():
    from rheo_superposition.plotting import get_temperature_colors
    colors=get_temperature_colors({'sampleC':{},'sample2':{}})
    assert colors['sampleC'] != colors['sample2']


def test_dynamic_custom_condition_labels():
    cfg = config(measurement='dynamic')
    x=np.linspace(-2,2,21)
    values=np.array([10**x,10**(1+.3*x),10**(1+.4*x+.01*x*x)]).T
    raw=pd.DataFrame([['sampleC','',''],['w','G1','G2'],['w0','g0','h0']]+values.tolist())
    data,_=parse_stacked_header_table(raw,cfg,strict=True)
    assert list(data)==['sampleC']
    result=estimate_shift_factors(data,cfg)
    assert result.iloc[0].aT==1 and result.iloc[0].bT==1


def test_fixed_transformation_does_not_require_overlap():
    cfg=config(shift_mode='none', fixed_log10_aT=12., fixed_log10_bT=0.)
    data,_=parse_stacked_header_table(raw_data(),cfg)
    target=estimate_shift_factors(data,cfg).set_index('T_label').loc['sample2']
    assert target.aT==1e12 and target.bT==1
    assert target.success_aT and target.success_bT
