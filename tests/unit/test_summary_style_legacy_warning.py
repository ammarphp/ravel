"""A publication opt-in must not alter the unrelated legacy diagnostic warning."""
import numpy as np

from ravel.plotting import mplhep_style as house


def test_legacy_legend_collision_failure_remains_a_warning(monkeypatch, capsys):
    legend = object()

    class Canvas:
        def draw(self):
            raise RuntimeError('fabricated collision observer failure')

    class Figure:
        canvas = Canvas()

    class Axis:
        figure = Figure()
        def legend(self, *args, **kwargs):
            return legend

    monkeypatch.setattr(house, '_occupancy_points', lambda ax: np.empty((0, 2)))
    assert house.smart_legend(Axis()) is legend
    assert 'legend collision check skipped (fabricated collision observer failure)' in capsys.readouterr().err


def test_publication_style_is_still_an_explicit_required_opt_in():
    import inspect
    assert inspect.signature(house.apply_style).parameters['required'].default is False
