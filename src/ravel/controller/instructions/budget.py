"""Instruction packet budgets derived from the seat's declared model windows.

A seat's packet must fit the input window of every model that may serve it. The window comes
from the model catalogue (``context_tokens`` less the model's declared ``max_output_tokens``,
which the provider reserves for the answer); the candidates come from the run's frozen agent
preferences for the card's tier (and the cheap tier when the card allows it). A candidate the
catalogue lists without a declared window is budgeted at the smallest window any catalogue row
declares, and the budget records that basis; nothing here is a fixed token number.

Without frozen preferences (an engagement projection of an installed route, or a check of a
packet outside a run) the budget is the smallest window among the catalogue's current models
for the card's tiers: the most conservative declared value a later selection could meet.
"""
from __future__ import annotations

from ravel.workflow import model_catalogue

class BudgetUnavailable(ValueError):
    """No candidate model window can be derived; ``remedy`` names the declaration to add."""

    def __init__(self, message, remedy):
        super().__init__(message)
        self.remedy = remedy


def _window(row):
    context, output = row.get('context_tokens'), row.get('max_output_tokens')
    if type(context) is not int or context <= 0:
        return None
    if type(output) is not int or output < 0 or output >= context:
        output = 0
    return context - output


def _floor(catalogue):
    windows = [(w, row['id']) for row in catalogue['models'] if (w := _window(row)) is not None]
    if not windows:
        raise BudgetUnavailable('no catalogue model declares its context window',
                                'declare context_tokens and max_output_tokens for the seat models in the model '
                                'catalogue (`ravel models show <id>`)')
    return min(windows)


def _tiers(card):
    model = (card or {}).get('model') or {}
    tiers = [model.get('tier')] if model.get('tier') else []
    if model.get('cheap_ok') is True:
        tiers.append('cheap')
    return tiers


def _candidate(model_id, catalogue, floor):
    row = model_catalogue.lookup(model_id, catalogue) if type(model_id) is str else None
    window = _window(row) if row is not None else None
    if window is not None:
        return {'model': model_id, 'window_tokens': window, 'context_tokens': row['context_tokens'],
                'max_output_tokens': row.get('max_output_tokens'), 'basis': 'declared'}
    return {'model': model_id, 'window_tokens': floor[0], 'context_tokens': None, 'max_output_tokens': None,
            'basis': 'undeclared_window_catalogue_floor', 'floor_model': floor[1],
            'catalogued': row is not None}


def seat_budget(card, preferences=None, *, catalogue=None):
    """The packet budget of a seat: ``{'packet_tokens', 'basis', 'candidates', ...}``.

    ``preferences`` is the run's frozen ``agent-preferences`` record; its ``tier_models`` name the
    model each transport serves per tier. The budget is the smallest candidate window."""
    catalogue = model_catalogue.load() if catalogue is None else catalogue
    floor = _floor(catalogue)
    tiers = _tiers(card)
    candidates = []
    if type(preferences) is dict and type(preferences.get('tier_models')) is dict:
        order = preferences.get('transport_preference') or []
        for tier in tiers:
            routes = preferences['tier_models'].get(tier)
            if type(routes) is not dict:
                continue
            for transport in sorted(routes, key=lambda t: (order.index(t) if t in order else len(order), t)):
                candidates.append({**_candidate(routes[transport], catalogue, floor),
                                   'tier': tier, 'transport': transport})
        basis = 'frozen_preferences'
    if not candidates:
        basis = 'catalogue_projection'
        for row in catalogue['models']:
            if row.get('status') == 'current' and set(row.get('tiers') or ()) & set(tiers or ('agent',)):
                window = _window(row)
                if window is not None:
                    candidates.append({'model': row['id'], 'window_tokens': window,
                                       'context_tokens': row['context_tokens'],
                                       'max_output_tokens': row.get('max_output_tokens'), 'basis': 'declared'})
        if not candidates:
            candidates.append(_candidate(None, catalogue, floor))
    binding = min(candidates, key=lambda c: (c['window_tokens'], str(c['model'])))
    return {'schema_version': 1, 'kind': 'instruction-packet-budget', 'packet_tokens': binding['window_tokens'],
            'basis': basis, 'binding_model': binding['model'], 'tiers': tiers,
            'candidates': sorted(candidates, key=lambda c: (c['window_tokens'], str(c['model'])))}


def selected_problem(selection, packet_tokens, *, catalogue=None):
    """A refusal sentence when the selected model's window cannot hold this packet, else None."""
    model = (selection or {}).get('model')
    catalogue = model_catalogue.load() if catalogue is None else catalogue
    window = _candidate(model, catalogue, _floor(catalogue))['window_tokens']
    if packet_tokens <= window:
        return None
    return (f'the selected model {model!r} has an input window of about {window} tokens, which cannot hold this '
            f'{packet_tokens}-token instruction packet; select a model with a larger declared context window for '
            'this seat or narrow the step')
