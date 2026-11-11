from dataclasses import replace
import numpy as np
import pandas as pd
import pytest

from rheo_superposition.controller import TTSController
from rheo_superposition.models import TTSConfig
from rheo_superposition.readers import parse_stacked_header_table
from tests.test_shifts import _series
from tests.test_time_domain import raw_data, config


@pytest.mark.parametrize('kind',['dynamic','relaxation','creep'])
@pytest.mark.parametrize('mode',['both','horizontal_only'])
def test_vertical_without_horizontal_fit(kind,mode):
    cfg=config(measurement=kind,shift_mode=mode)
    if kind=='dynamic':
        x=np.linspace(-2,2,65)
        data={'sampleC':_series(x,1+.3*x,1+.6*x+.03*x*x),
              'sample2':_series(x,1+.3*x+.25,1+.6*x+.03*x*x+.25)}
        traces=pd.DataFrame()
    else:
        data,traces=parse_stacked_header_table(raw_data(kind,dx=0,dy=-.25),cfg,strict=True)
    controller=TTSController()
    controller.set_data(data,traces,cfg)
    result=controller.run_vertical(None,cfg)
    assert controller.state.config.shift_mode=='vertical_only'
    assert np.all(result.aT.to_numpy()==1)
    row=result.set_index('T_label').loc['sample2']
    assert row.success_bT
    assert not row.bT_is_fixed
    assert row.log10_bT==pytest.approx(-.25,abs=1e-4)
    assert result.set_index('T_label').loc['sampleC'].bT==1
    assert controller.state.horizontal_shifts is not None


@pytest.mark.parametrize('kind',['dynamic','relaxation','creep'])
def test_vertical_preserves_existing_horizontal_result(kind):
    cfg=config(measurement=kind,shift_mode='both')
    if kind=='dynamic':
        x=np.linspace(-2,2,65)
        gp=lambda z:1+.3*z+.02*z*z
        gpp=lambda z:1+.6*z+.03*z*z
        data={'sampleC':_series(x,gp(x),gpp(x)),
              'sample2':_series(x,gp(x+.4)+.25,gpp(x+.4)+.25)}
        traces=pd.DataFrame()
    else:
        data,traces=parse_stacked_header_table(raw_data(kind),cfg,strict=True)
    controller=TTSController()
    controller.set_data(data,traces,cfg)
    h=controller.run_horizontal(cfg)
    original=h.copy(deep=True)
    result=controller.run_vertical(h,cfg)
    np.testing.assert_array_equal(result.aT,h.aT)
    pd.testing.assert_frame_equal(h,original)
