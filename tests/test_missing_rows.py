import numpy as np
import pandas as pd
import pytest
from rheo_superposition.models import TTSConfig
from rheo_superposition.readers import parse_stacked_header_table, parse_rheology_input


@pytest.mark.parametrize('kind', ['relaxation', 'creep', 'dynamic'])
@pytest.mark.parametrize('scale', ['linear', 'log10', 'ln'])
@pytest.mark.parametrize('missing', [np.nan, None, '', '  ', 'NaN'])
def test_partial_missing_rows_skip_only_their_condition(kind, scale, missing, tmp_path):
    variables = ['w', 'G1', 'G2'] if kind == 'dynamic' else ['t', 'J' if kind == 'creep' else 'G']
    size = len(variables)
    numbers = np.array([[i, i*10, i*5][:size]*2 for i in range(1, 9)], dtype=float)
    if scale == 'log10': numbers = np.log10(numbers)
    if scale == 'ln': numbers = np.log(numbers)
    raw = pd.DataFrame([['1']+['']*(size-1)+['2']+['']*(size-1), variables*2,
                        [f'trace{i}' for i in range(size*2)]]+numbers.tolist())
    # Missing horizontal value and missing response on separate rows.
    raw.iat[4,0] = missing
    raw.iat[6,1] = missing
    cfg=TTSConfig(measurement=kind,input_scale=scale,T_ref='1', data_path=tmp_path/'input.csv')
    data,_=parse_stacked_header_table(raw,cfg,strict=True)
    xkey='omega' if kind=='dynamic' else 'time'
    np.testing.assert_allclose(data['1'][xkey], [1,3,5,6,7,8])
    np.testing.assert_allclose(data['2'][xkey], np.arange(1,9))
    raw.to_csv(cfg.data_path,header=False,index=False)
    loaded,_=parse_rheology_input(cfg)
    np.testing.assert_allclose(loaded['1'][xkey], data['1'][xkey])


@pytest.mark.parametrize('kind', ['relaxation','creep','dynamic'])
def test_too_few_complete_rows_rejected(kind):
    variables=['w','G1','G2'] if kind=='dynamic' else ['t','J' if kind=='creep' else 'G']
    n=len(variables)
    raw=pd.DataFrame([['1']+['']*(n-1), variables, [f'w{i}' for i in range(n)]] +
                     [[i]+[i*2]*(n-1) for i in range(1,6)])
    raw.iat[3,1]=np.nan
    raw.iat[4,0]=np.nan
    with pytest.raises(ValueError,match='4|four'):
        parse_stacked_header_table(raw,TTSConfig(measurement=kind),strict=True)
