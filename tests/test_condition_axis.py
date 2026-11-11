import numpy as np
import pytest
from matplotlib.figure import Figure
from matplotlib.backends.backend_agg import FigureCanvasAgg
from matplotlib.ticker import LogLocator
from rheo_superposition.plotting import configure_condition_axis, condition_positions
from rheo_superposition.models import TTSConfig


def test_log_condition_axis_keeps_numerical_coordinates():
    fig=Figure(); ax=fig.subplots()
    labels=['0.001','0.01','0.1']
    positions=configure_condition_axis(ax,labels,'log')
    np.testing.assert_allclose(positions,[.001,.01,.1])
    ax.scatter(positions,[0,1,2])
    FigureCanvasAgg(fig).draw()
    screen=ax.transData.transform(np.column_stack([positions,[0,0,0]]))[:,0]
    np.testing.assert_allclose(np.diff(screen),np.repeat(np.diff(screen)[0],2))
    assert ax.get_xscale()=='log'
    assert isinstance(ax.xaxis.get_major_locator(),LogLocator)
    assert ax.get_xlim()[0]>0
    assert ax.get_xlabel()=='Condition'


@pytest.mark.parametrize('labels',[['0','1'],['-1','2'],['sampleA','sampleB']])
def test_invalid_log_conditions_rejected(labels):
    with pytest.raises(ValueError,match='positive numeric'):
        condition_positions(labels,'log')


def test_switch_from_categorical_to_log_and_back():
    ax=Figure().subplots()
    configure_condition_axis(ax,['A','B'],'linear')
    assert [t.get_text() for t in ax.get_xticklabels()]==['A','B']
    configure_condition_axis(ax,['.01','.1'],'log')
    assert isinstance(ax.xaxis.get_major_locator(),LogLocator)
    configure_condition_axis(ax,['-10','0','10'],'linear')
    assert ax.get_xscale()=='linear'
    assert ax.get_xlim()[0]<-10 and ax.get_xlim()[1]>10


def test_single_condition_log_limits_and_named_label():
    ax=Figure().subplots()
    configure_condition_axis(ax,['.009921854'],'log',TTSConfig().condition_axis_label)
    assert ax.get_xlim()[0]<.009921854<ax.get_xlim()[1]
    assert ax.get_xlabel()=='Temperature (°C)'


@pytest.mark.parametrize('name,unit,expected', [('Concentration','%','Concentration (%)'),('Pressure','MPa','Pressure (MPa)'),('Humidity','','Humidity')])
def test_condition_name_and_unit_label(name,unit,expected):
    assert TTSConfig(condition_name=name,condition_unit=unit).condition_axis_label==expected
