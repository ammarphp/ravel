"""Figures for columnar analysis results: single histograms and stacked control plots.

Labels come from the recipe's natural-language axis labels and the declared process
labels; nothing is drawn from a machine identifier. Every figure passes the house layout
lint before it is saved as PDF and PNG. A stacked control plot shows simulated
backgrounds stacked, signals as lines and any pseudo-data as points labelled as
simulation, with the Monte Carlo statistical uncertainty of the background total.
"""
import json
import math
from pathlib import Path

import numpy as np

ROLES = ('background', 'signal', 'pseudo-data')
_VALUE_LABELS = {'events': 'Events per bin', 'sum of event weights': 'Sum of event weights per bin',
                 'fraction of events': 'Fraction of events per bin'}


def _axis_title(axis):
    from ravel.plotting.display_labels import display_label, unit_label
    name = display_label(axis['name'], axis['name'])
    return name if axis['unit'] == '1' else f'{name} [{unit_label(axis["unit"])}]'


def _value_title(unit, explicit=None):
    from ravel.plotting.display_labels import display_label, unit_label
    if explicit:
        return display_label(explicit, explicit)
    if unit in _VALUE_LABELS:
        return _VALUE_LABELS[unit]
    return f'Value [{unit_label(unit)}]'


def _edges(doc):
    if len(doc['axes']) != 1:
        raise ValueError('only one-dimensional histograms are drawn')
    lows = [b['low'][0] for b in doc['bins']]
    return np.array(lows + [doc['bins'][-1]['high'][0]], float)


def _save(fig, out, plt, house):
    failures = house.lint_figure(fig)
    if failures:
        plt.close(fig)
        raise ValueError('figure layout failed: ' + '; '.join(failures))
    out = Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    for ext in ('pdf', 'png'):
        fig.savefig(out.with_suffix('.' + ext), dpi=220, bbox_inches='tight')
    plt.close(fig)


def histogram_figure(doc, *, title, out, value_label=None):
    """Draw one binned_values histogram with its uncertainty band."""
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    from ravel.plotting import mplhep_style as house
    from ravel.plotting.display_labels import label_errors
    house.apply_style('ATLAS')
    edges = _edges(doc)
    values = np.array([b['value'] for b in doc['bins']])
    errors = np.array([b.get('uncertainty', 0.0) for b in doc['bins']])
    fig, ax = plt.subplots(figsize=(8, 5.6))
    ax.stairs(values, edges, color='#0072B2', linewidth=1.8, label='Selected events')
    ax.stairs(values + errors, edges, baseline=values - errors, fill=True, color='#0072B2', alpha=0.25,
              hatch='///', label='Simulation statistical uncertainty')
    ax.set_xlabel(_axis_title(doc['axes'][0]))
    ax.set_ylabel(_value_title(doc['unit'], value_label))
    ax.set_xlim(edges[0], edges[-1])
    top = float(np.max(values + errors)) if len(values) else 1.0
    ax.set_ylim(0, top * 1.45 if top > 0 else 1.0)
    house.tick_hygiene(ax)
    house.smart_legend(ax, fontsize=11)
    if not label_errors(title):
        ax.set_title(title, fontsize=13)
    _save(fig, out, plt, house)
    return {'plot_lint': 'PASS', 'png_dpi': 220,
            'display_labels': {'x': _axis_title(doc['axes'][0]), 'y': _value_title(doc['unit'], value_label)},
            'normalization': 'Values and uncertainties read unchanged from the binned_values file'}


def _load_histogram(result_dir, histogram):
    result_dir = Path(result_dir)
    summary = json.loads((result_dir / 'analysis-result.json').read_text())
    if histogram not in summary['histograms']:
        raise ValueError(f'{result_dir} has no histogram {histogram!r}')
    file = summary['histograms'][histogram]['nominal']['file']
    return json.loads((result_dir / file).read_text())


def control_plot(entries, histogram, out, *, log=False):
    """Stack backgrounds, overlay signals and label any pseudo-data; entries have result, label and role."""
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    from ravel.plotting import mplhep_style as house
    from ravel.plotting.display_labels import label_errors
    if not entries:
        raise ValueError('at least one process is needed')
    docs = []
    for e in entries:
        if e['role'] not in ROLES:
            raise ValueError(f'role must be one of {ROLES}')
        problems = label_errors(e['label'])
        if problems:
            raise ValueError(f'process label {e["label"]!r} is not natural language: {"; ".join(problems)}')
        docs.append(_load_histogram(e['result'], histogram))
    edges = _edges(docs[0])
    unit, axis = docs[0]['unit'], docs[0]['axes'][0]
    for d in docs[1:]:
        if not np.allclose(_edges(d), edges) or d['unit'] != unit or d['axes'][0]['unit'] != axis['unit']:
            raise ValueError('all processes must share the histogram edges and units')
    if not any(e['role'] == 'background' for e in entries):
        raise ValueError('a control plot needs at least one background process')
    house.apply_style('ATLAS')
    fig, ax = plt.subplots(figsize=(8.5, 6))
    bottom = np.zeros(len(edges) - 1)
    variance = np.zeros(len(edges) - 1)
    k = 0
    for e, d in zip(entries, docs):
        if e['role'] != 'background':
            continue
        v = np.array([b['value'] for b in d['bins']])
        variance += np.array([b.get('uncertainty', 0.0) ** 2 for b in d['bins']])
        ax.stairs(bottom + v, edges, baseline=bottom, fill=True, color=house.process_color(e['label'], k),
                  label=e['label'], edgecolor='black', linewidth=0.4)
        bottom = bottom + v
        k += 1
    sigma = np.sqrt(variance)
    ax.stairs(bottom + sigma, edges, baseline=bottom - sigma, fill=False, hatch='////', color='0.35', linewidth=0,
              label='Background simulation statistical uncertainty')
    for e, d in zip(entries, docs):
        v = np.array([b['value'] for b in d['bins']])
        if e['role'] == 'signal':
            ax.stairs(v, edges, color=house.SIGNAL_COLOR, linewidth=2.0, linestyle='--', label=e['label'])
        elif e['role'] == 'pseudo-data':
            centres = 0.5 * (edges[1:] + edges[:-1])
            ax.errorbar(centres, v, yerr=np.sqrt(np.maximum(v, 0.0)), fmt='o', color='black', ms=4,
                        label=f'{e["label"]} (pseudo-data from simulation)')
    ax.set_xlabel(_axis_title(axis))
    ax.set_ylabel(_value_title(unit))
    ax.set_xlim(edges[0], edges[-1])
    tops = [float(np.max(bottom + sigma))] + [float(max(b['value'] for b in d['bins'])) for d in docs]
    top = max(tops) if tops else 1.0
    if log:
        positive = [b['value'] for d in docs for b in d['bins'] if b['value'] > 0]
        low = min(positive) if positive else 1e-3
        ax.set_yscale('log'); ax.set_ylim(low * 0.5, top * 50 if top > 0 else 10)
    else:
        ax.set_ylim(0, top * 1.6 if top > 0 else 1.0)
    house.tick_hygiene(ax, logy=log)
    house.smart_legend(ax, fontsize=10)
    _save(fig, out, plt, house)
    return {'stem': str(out), 'files': [str(Path(out).with_suffix('.pdf')), str(Path(out).with_suffix('.png'))],
            'plot_lint': 'PASS', 'processes': [{'label': e['label'], 'role': e['role'], 'result': str(e['result'])} for e in entries],
            'normalization': 'Each process uses its own declared normalisation; values are not rescaled at plot time'}
