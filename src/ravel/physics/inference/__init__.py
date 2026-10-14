"""General statistical inference engines for declared, supplied inputs.

Each engine evaluates exactly what its input document declares: formulas over
parameter grids, coupling-polynomial morphing, requester-prescribed statistics,
binned search statistics with pyhf, and correlated differential-measurement
likelihoods. Every engine writes one ``inference.json`` record (see ``record``).
Task specifics (bins, yields, formulas, thresholds) are data, never code.

The five science modes below run through the ordinary plan/approve/run
lifecycle (``ravel plan`` with ``schema_version: 2``). ``ravel inference``
checks a task document, lists its inputs and writes a study specification.
"""

MODES = ('formula-grid', 'coupling-morphing', 'prescribed-statistic', 'search-statistics',
         'differential-likelihood')
