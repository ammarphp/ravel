"""Owner interfaces of the scalar likelihood review checks.

``check_cross_engine`` compares two engines' results for one physical comparison input:
``doc`` is ``{"signals": <higgs-signals result>, "likelihood": <higgs-lilith result>}``, the
result records each operation writes. The comparison itself is ``lilith_bridge.cross_engine``
(signed SM-relative delta chi2, its declared tolerance and the measurement census of each
database). This returns the typed status record of the review checks. Agreement is a
numerical cross-check, not physics validation.
"""
from __future__ import annotations

from ravel.physics import lilith_bridge

IDENTITY = 'check:higgs.cross_engine'


def check_cross_engine(doc):
    if not isinstance(doc, dict) or set(doc) != {'signals', 'likelihood'} or not all(
            isinstance(doc[k], dict) for k in doc):
        return {'status': 'inconclusive', 'findings': [], 'outcome': 'inputs_missing',
                'detail': 'cross-engine check needs the signals and likelihood result records'}
    try:
        report = lilith_bridge.cross_engine(doc['signals'], doc['likelihood'])
    except (ValueError, TypeError, KeyError) as exc:
        # Mismatched engines, different comparison inputs or a failed engine result.
        return {'status': 'inconclusive', 'findings': [], 'outcome': 'inputs_invalid', 'detail': str(exc)}
    if report['status'] == 'passed':
        return {'status': 'passed', 'findings': [], 'outcome': 'passed', 'comparison': report}
    summary = (f"engines differ by {report['difference']:g} in delta chi2 against tolerance "
               f"{report['tolerance']:g}")
    return {'status': 'failed', 'outcome': 'flagged_conflict', 'comparison': report,
            'findings': [{'id': IDENTITY + ':engine-difference', 'code': 'engine-difference',
                          'materiality': 'B', 'summary': summary}]}
