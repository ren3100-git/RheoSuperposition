"""Arial typography for plots, without changing the application theme."""
from matplotlib import rcParams


def configure_plot_fonts() -> None:
    rcParams.update({
        "font.family": "Arial",
        "font.sans-serif": ["Arial"],
        "mathtext.fontset": "custom",
        "mathtext.rm": "Arial",
        "mathtext.it": "Arial:italic",
        "mathtext.bf": "Arial:bold",
        "mathtext.sf": "Arial",
        "mathtext.tt": "Arial",
        "mathtext.cal": "Arial:italic",
    })
