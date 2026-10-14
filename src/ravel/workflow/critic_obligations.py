"""Review obligations for the scientific critic, built from the request plan.

The critic reviews the quantity the request asks for under the scientific contracts the plan
actually applies. Each claim kind contributes the checks its quantity needs, each planned stage
and operation effect contributes the invariants of that contract, and a few checks apply to
every review. An exclusion check is therefore one specialization, selected only when a claim is
an exclusion. Obligations name what to verify, never a fixed artifact file: the critic locates
the evidence through the review packet index.

Usage: ``python -m ravel.workflow.critic_obligations --plan <run>/inputs/plan.json``
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# Checks every review carries, whatever the request.
COMMON = (
    ('provenance', 'Tool versions, seeds, inputs and their source identities are recorded for every quoted number.'),
    ('scope', 'Each claim stays inside its declared scope; integrity, calibration, diagnostic agreement and '
              'publication reproduction remain distinct claims.'),
    ('units-and-conventions', 'Units, conventions and observed/expected roles are stated and consistent across '
                              'inputs and outputs.'),
)

# Checks contributed by the requested quantity (the claim kind).
BY_CLAIM = {
    'exclusion': (
        ('statistic-as-declared', 'The delivered statistic is the declared one ({definition}); a prescribed '
                                  'statistic is the primary result and is evaluated as written.'),
        ('root-resolved', 'Every reported exclusion boundary is a resolved crossing of the declared threshold, '
                          'with its bracket and fit diagnostics; an endpoint is reported as a bound.'),
        ('statistical-model', "The statistical model is the analysis's own or a stated, justified approximation, "
                              'with all channels and controls the source declares.'),
        ('not-discovery', 'The result is phrased as an exclusion under the stated assumptions, never as a '
                          'discovery or as general viability.'),
    ),
    'estimate': (
        ('statistic-as-declared', 'The interval construction is the declared one ({definition}).'),
        ('fit-quality', 'Fitted values carry intervals, goodness of fit and the treatment of nuisance '
                        'parameters; optimizer success is checked against the objective, bounds and gradient.'),
        ('parameter-conventions', 'Parameter definitions, priors or constraints and their correlations are stated.'),
    ),
    'significance': (
        ('statistic-as-declared', 'The test statistic is the declared one ({definition}) with its null hypothesis.'),
        ('observed-expected', 'Observed and expected values are distinguished and the expectation basis is stated.'),
    ),
    'prediction': (
        ('model-inputs', 'Model parameters, orders and the observable definition match the request.'),
        ('prediction-uncertainty', 'Scale, PDF, parametric and statistical uncertainties are reported or '
                                   'declared absent.'),
    ),
    'agreement': (
        ('metric-and-tolerance', 'The comparison uses the declared metric and tolerance; missing reference '
                                 'covariance is unresolved, never zero.'),
        ('like-for-like', 'Compared quantities share basis, selection, binning and normalization.'),
    ),
    'calculation': (
        ('independent-check', 'The result has an independent check (a limit, symmetry, second method or '
                              'analytic special case).'),
        ('calculation-conventions', 'Schemes, orders, renormalization choices and input values are stated.'),
    ),
    'finding': (
        ('source-support', 'Each statement is traced to a located source passage, table or figure.'),
    ),
    'method_performance': (
        ('baseline', 'The method is compared with the declared baseline on the declared data.'),
        ('held-out', 'Performance is measured on data the method did not tune on.'),
    ),
    'document': (
        ('carried-claims', 'Every number and figure in the document traces to a reviewed claim of this plan.'),
    ),
}

# Checks contributed by the stages and effects of the planned operations.
BY_STAGE = {
    'model-derivation': (('model-derivation', 'The derived model reproduces its stated Lagrangian, parameters '
                                              'and conventions.'),),
    'spectrum': (('spectrum-and-decays', 'Generated masses, mixings and decay tables match the intended model, '
                                         'and the intended decays occur.'),),
    'generation': (('normalization-basis', 'Cross-section order, collision energy, charge/flavour basis, '
                                           'branching convention and any correction factor match the supplied '
                                           'model inputs and their source.'),),
    'shower': (('shower-settings', 'Shower and merging settings follow the stated prescription; merged '
                                   'samples use a matching hook and validated weights.'),),
    'detector': (('detector-response', 'The detector description and object definitions match the analysis '
                                       'or are flagged as approximations with an estimated effect.'),),
    'analysis': (('selection-and-acceptance', 'The implemented selection matches the source definition; '
                                              'acceptance residuals against any supplied reference are attributed '
                                              'with a bounded effect on the result.'),),
    'figure': (('figure-criteria', 'Figures pass docs/workflow/checklists/plot-criteria.md and match any '
                                   'declared reference figure in axes and binning.'),),
}
BY_EFFECT = {
    'generates_events': BY_STAGE['generation'],
    'acquires_published': (('source-applicability', 'Acquired sources apply to the stated model, energy and '
                                                    'selection, and their precision is reported.'),),
}


def _signatures():
    from ravel.validation import validate_request_plan as rp
    return rp.signatures()


def obligations(plan, *, signatures=None):
    """Return the ordered review obligations for ``plan``.

    Each obligation is ``{'id', 'check', 'because'}``; ``because`` names the claim kind, stage or
    effect that selected it. ``signatures`` maps an operation name to its signature entry and
    defaults to the shipped operation signatures.
    """
    signed = _signatures() if signatures is None else signatures
    rows, seen = [], set()

    def add(oid, check, because):
        if oid in seen:
            for row in rows:
                if row['id'] == oid and because not in row['because']:
                    row['because'].append(because)
            return
        seen.add(oid)
        rows.append({'id': oid, 'check': check, 'because': [because]})

    for oid, check in COMMON:
        add(oid, check, 'every review')
    for claim in plan.get('claims', []):
        kind = claim.get('kind')
        if kind not in BY_CLAIM:
            raise ValueError(f'unknown claim kind: {kind!r}')
        definition = ((claim.get('statistic') or {}).get('definition')) or 'as declared in the plan'
        for oid, check in BY_CLAIM[kind]:
            add(f'{kind}:{oid}', check.format(definition=definition), f"claim {claim.get('id')} ({kind})")
    for node in plan.get('nodes', []):
        entry = signed.get(node.get('operation')) or {}
        for stage in entry.get('stages', []):
            for oid, check in BY_STAGE.get(stage, ()):
                add(oid, check, f'stage {stage}')
        for effect in entry.get('effects', []):
            for oid, check in BY_EFFECT.get(effect, ()):
                add(oid, check, f'effect {effect}')
    return rows


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('--plan', required=True, type=Path, help='the run request plan (inputs/plan.json)')
    args = parser.parse_args(argv)
    json.dump(obligations(json.loads(args.plan.read_text())), sys.stdout, indent=2)
    sys.stdout.write('\n')
    return 0


if __name__ == '__main__':
    sys.exit(main())
