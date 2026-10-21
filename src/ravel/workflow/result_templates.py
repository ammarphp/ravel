"""Fill a user-supplied numeric result template from an accepted RAVEL result.

A request can supply the exact form its numbers must take, for example a
HEPData-style YAML table whose independent variables give the bin edges and whose
dependent values are empty. This module copies values from one accepted binned
result into that form. It never interpolates, extrapolates or changes an edge:

- every template bin must match result bins exactly, or through a declared
  rebinning whose result bins tile the template bin and preserve the total;
- overflow and underflow follow metadata or an evidence-backed CLI declaration;
- units must agree wherever the template states them;
- the result must be captured by a current accepted review of the named scope.

A provisional fill is the one exception, and only at a declared study deadline
(``study_deadline``): inside the delivery margin it fills from an output that a
valid stage receipt pins and that an open, unresolved review is examining. The
filled file and its provenance say ``provisional: true`` and name the open review.
A later reviewed fill supersedes it in place through ``deliver_into`` with
``supersedes``; the provisional record is never rewritten, a sidecar links both.
No accepted result, claim, CHECK-IN 3 record or submission export takes a
provisional pin (``provisional_errors``).

The filled template is written next to a provenance record holding the template,
result and output hashes, the acceptance scope, units, conventions and the
per-bin mapping. Any doubt refuses; nothing is filled from a guess.
"""
from copy import deepcopy
import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import re
import tempfile

OVERFLOW = ('last-bin', 'excluded')
UNDERFLOW = ('first-bin', 'excluded')
FLOW_WORDS = re.compile(r'\b(over|under)flow', re.I)
FLOW_PHRASES = {
    'overflow': re.compile(r'\b(?:rightmost|last|final)\s+bin\b[^.!?;]*'
                           r'\b(?:inclusive|includes\s+all|and\s+above|greater\s+than)\b', re.I),
    'underflow': re.compile(r'\b(?:leftmost|first)\s+bin\b[^.!?;]*'
                            r'\b(?:inclusive|includes\s+all|and\s+below|less\s+than)\b', re.I),
}
MAX_BYTES = 2_000_000
PROVISIONAL_MARK = '# RAVEL PROVISIONAL FILL'
SUPERSEDED_SUFFIX = '.superseded.json'


def _pin(path, raw):
    return {'path': str(path), 'sha256': hashlib.sha256(raw).hexdigest(), 'size': len(raw)}


def _number(value, label):
    if type(value) not in (int, float) or not math.isfinite(value):
        raise ValueError(f'{label} must be a finite number')
    return float(value)


def _text(value):
    return value.strip() if isinstance(value, str) else ''


def _normalized(text):
    return ' '.join(text.split())


def _strings(value, ancestors=()):
    """Walk all documents' textual keys and values, including metadata-only ones."""
    if isinstance(value, str):
        yield value
    elif isinstance(value, (dict, list)):
        if id(value) in ancestors:
            raise ValueError('recursive template aliases are unsupported')
        ancestors = (*ancestors, id(value))
        if isinstance(value, dict):
            for key, child in value.items():
                yield from _strings(key, ancestors)
                yield from _strings(child, ancestors)
        else:
            for child in value:
                yield from _strings(child, ancestors)


def _read(path):
    path = Path(path)
    if path.is_symlink() or not path.is_file():
        raise ValueError(f'regular file required: {path}')
    raw = path.read_bytes()
    if not 1 <= len(raw) <= MAX_BYTES:
        raise ValueError(f'{path} must be nonempty and at most 2 MB')
    return raw


def _json(raw, label):
    def unique(pairs):
        out = {}
        for k, v in pairs:
            if k in out:
                raise ValueError(f'{label} repeats key {k!r}')
            out[k] = v
        return out

    def constant(name):
        raise ValueError(f'{label} contains non-finite {name}')
    return json.loads(raw, object_pairs_hook=unique, parse_constant=constant)


# ---------------------------------------------------------------- templates
class Template:
    """One table of a supplied template, normalized to edges, units and conventions."""

    def __init__(self, path, raw, *, table=None, column=None,
                 overflow=None, underflow=None, flow_evidence=None):
        self.path, self.raw = Path(path), raw
        self.cli_conventions = {k: v for k, v in (('overflow', overflow), ('underflow', underflow)) if v is not None}
        self.flow_evidence = flow_evidence
        suffix = self.path.suffix.lower()
        if suffix in ('.yaml', '.yml'):
            import yaml
            self.format = 'hepdata-yaml'
            try:
                self.documents = list(yaml.safe_load_all(raw.decode('utf8')))
            except (yaml.YAMLError, UnicodeError) as exc:
                raise ValueError(f'template is not readable YAML: {exc}') from None
        elif suffix == '.json':
            self.documents = [_json(raw, 'template')]
            if not isinstance(self.documents[0], dict):
                raise ValueError('JSON template must be an object')
            self.format = 'table-json' if self.documents[0].get('kind') == 'result_template' else 'hepdata-json'
        else:
            raise ValueError('template must be .yaml, .yml or .json')
        self.original = deepcopy(self.documents)
        if self.format == 'table-json':
            self._simple(column)
        else:
            self._hepdata(table, column)

    def _hepdata(self, table, column):
        tables = [i for i, d in enumerate(self.documents)
                  if isinstance(d, dict) and 'independent_variables' in d and 'dependent_variables' in d]
        if table is None:
            if len(tables) != 1:
                raise ValueError(f'template has {len(tables)} tables; choose one with --table')
            table = 0
        if type(table) is not int or not 0 <= table < len(tables):
            raise ValueError('table index is outside the template')
        self.table, self.document_index = table, tables[table]
        doc = self.documents[self.document_index]
        ivs, dvs = doc['independent_variables'], doc['dependent_variables']
        if not isinstance(ivs, list) or not ivs or not isinstance(dvs, list) or not dvs:
            raise ValueError('template table needs independent and dependent variables')
        rows = None
        self.axes, columns = [], []
        for iv in ivs:
            header = iv.get('header') or {}
            values = iv.get('values')
            if not isinstance(values, list) or not values:
                raise ValueError('every independent variable needs values')
            if rows is not None and len(values) != rows:
                raise ValueError('independent variables have different row counts')
            rows = len(values)
            for v in values:
                if not isinstance(v, dict) or 'low' not in v or 'high' not in v:
                    raise ValueError('template independent variables must give bin low and high edges')
            self.axes.append({'name': _text(header.get('name')), 'unit': _text(header.get('units')) or None})
            columns.append([(_number(v['low'], 'template edge'), _number(v['high'], 'template edge')) for v in values])
        self.bins = [(tuple(c[i][0] for c in columns), tuple(c[i][1] for c in columns)) for i in range(rows)]
        empty = [i for i, dv in enumerate(dvs) if isinstance(dv, dict) and self._empty(dv.get('values'), rows)]
        if column is None:
            if len(empty) != 1:
                raise ValueError(f'template has {len(empty)} empty dependent columns; choose one with --column')
            index = empty[0]
        else:
            names = [_text((dv.get('header') or {}).get('name')) for dv in dvs]
            index = column if type(column) is int else (names.index(column) if names.count(column) == 1 else None)
            if index is None or not 0 <= index < len(dvs):
                raise ValueError('column must name exactly one dependent variable')
            if index not in empty:
                raise ValueError('selected column already holds values; a filled template is never overwritten')
        self.column = index
        dv = dvs[index]
        header = dv.get('header') or {}
        self.column_name = _text(header.get('name'))
        self.unit = _text(header.get('units')) or None
        qualifiers = dv.get('qualifiers') or []
        declared = {}
        for q in qualifiers:
            name = _text(q.get('name')).lower() if isinstance(q, dict) else ''
            if name in ('overflow', 'underflow'):
                if name in declared:
                    raise ValueError(f'template declares {name} twice')
                declared[name] = _text(str(q.get('value')))
        self._conventions(declared)

    @staticmethod
    def _empty(values, rows):
        if values == []:
            return True
        return (isinstance(values, list) and len(values) == rows
                and all(isinstance(v, dict) and v.get('value') is None for v in values))

    def _simple(self, column):
        doc = self.documents[0]
        allowed = {'schema_version', 'kind', 'axes', 'unit', 'bins', 'overflow', 'underflow', 'description'}
        if set(doc) - allowed or not {'schema_version', 'kind', 'axes', 'bins'} <= set(doc):
            raise ValueError(f'JSON result template accepts only {sorted(allowed)}')
        if doc['schema_version'] != 1 or column is not None:
            raise ValueError('JSON result template version 1 has one value column')
        self.table, self.document_index, self.column, self.column_name = None, 0, None, ''
        self.axes = [{'name': _text(a.get('name')), 'unit': _text(a.get('unit')) or None} for a in doc['axes']]
        self.unit = _text(doc.get('unit')) or None
        if not isinstance(doc['bins'], list) or not doc['bins']:
            raise ValueError('JSON result template needs bins')
        self.bins = []
        for b in doc['bins']:
            if not isinstance(b, dict) or set(b) != {'low', 'high', 'value'} or b['value'] is not None:
                raise ValueError('every template bin needs low, high and a null value')
            if len(b['low']) != len(self.axes) or len(b['high']) != len(self.axes):
                raise ValueError('template bin edges must match its axes')
            self.bins.append((tuple(_number(x, 'template edge') for x in b['low']),
                              tuple(_number(x, 'template edge') for x in b['high'])))
        declared = {k: _text(doc[k]) for k in ('overflow', 'underflow') if k in doc}
        self._conventions(declared)

    def _conventions(self, declared):
        from ravel.physics.quantities import validate_binning
        validate_binning([{'name': a['name'] or f'axis{i}', 'unit': a['unit'] or 'unstated'} for i, a in enumerate(self.axes)],
                         [{'id': str(i), 'low': list(lo), 'high': list(hi)} for i, (lo, hi) in enumerate(self.bins)])
        metadata = dict(declared)
        self.convention_provenance = {'source': 'template metadata'}
        texts = [(i, _normalized(t)) for i, doc in enumerate(self.documents) for t in _strings(doc)]
        if self.cli_conventions:
            if not _text(self.flow_evidence):
                raise ValueError('CLI flow declaration needs nonempty --flow-evidence from the template')
            quote = _normalized(self.flow_evidence)
            matches = [i for i, text in texts if quote in text]
            if not matches:
                raise ValueError('flow evidence does not occur verbatim (whitespace-normalised) in the template')
            for name, value in self.cli_conventions.items():
                if name in declared and declared[name] != value:
                    raise ValueError(f'CLI {name} conflicts with the template declaration {declared[name]!r}')
                declared[name] = value
            self.convention_provenance = {'source': 'cli-declaration', 'evidence': self.flow_evidence,
                                         'document_index': matches[0], 'template_declarations': metadata}
        elif self.flow_evidence is not None:
            raise ValueError('--flow-evidence requires an --overflow or --underflow declaration')
        if declared.get('overflow', 'excluded') not in OVERFLOW:
            raise ValueError(f'overflow convention must be one of {OVERFLOW}')
        if declared.get('underflow', 'excluded') not in UNDERFLOW:
            raise ValueError(f'underflow convention must be one of {UNDERFLOW}')
        for index, text in texts:
            for sentence in re.split(r'(?<=[.!?;])\s+', text):
                words = {m.group(1).lower() + 'flow' for m in FLOW_WORDS.finditer(sentence)}
                words.update(name for name, pattern in FLOW_PHRASES.items() if pattern.search(sentence))
                for word in sorted(words):
                    if word not in declared:
                        options = '/'.join(OVERFLOW if word == 'overflow' else UNDERFLOW)
                        raise ValueError(f'template text mentions {word} in document {index}: {sentence!r} '
                                         f'but does not declare its convention; add a {word} qualifier '
                                         f'or --{word} ({options}) with --flow-evidence')
        if any(v != 'excluded' for v in declared.values()) and len(self.axes) != 1:
            raise ValueError('overflow and underflow placement is defined for one axis only')
        self.conventions = {'overflow': declared.get('overflow'), 'underflow': declared.get('underflow')}

    def filled(self, values, uncertainties, label):
        documents = deepcopy(self.documents)
        if self.format == 'table-json':
            for b, v in zip(documents[0]['bins'], values):
                b['value'] = v
            return documents
        dv = documents[self.document_index]['dependent_variables'][self.column]
        rows = dv.get('values') or [{} for _ in values]
        out = []
        for row, v, u in zip(rows, values, uncertainties):
            row = dict(row)
            row['value'] = v
            if label is not None:
                row['errors'] = [{'symerror': u, 'label': label}]
            out.append(row)
        dv['values'] = out
        return documents

    def dump(self, documents, provisional=None):
        """Serialize; a provisional notice is a YAML comment header or a top-level JSON key."""
        if self.format == 'hepdata-yaml':
            import yaml
            text = yaml.safe_dump_all(documents, sort_keys=False, allow_unicode=True)
            if provisional is not None:
                text = ''.join(f'# {line}\n' for line in [PROVISIONAL_MARK[2:], *_notice_lines(provisional)]) + text
            return text.encode()
        document = documents[0] if provisional is None else {**documents[0], 'provisional': provisional}
        return (json.dumps(document, indent=2, allow_nan=False) + '\n').encode()

    def unchanged_except_values(self, documents, provisional=False):
        """Everything but the filled value column must survive byte-for-byte in meaning."""
        before, after = deepcopy(self.original), deepcopy(documents)
        if provisional and self.format != 'hepdata-yaml':
            if not isinstance(after[0], dict) or not isinstance(after[0].pop('provisional', None), dict):
                return False
        if self.format == 'table-json':
            for b in after[0]['bins']:
                b['value'] = None
        else:
            before[self.document_index]['dependent_variables'][self.column].pop('values', None)
            after[self.document_index]['dependent_variables'][self.column].pop('values', None)
        return before == after


def _notice_lines(notice):
    review = notice['open_review']
    return ['provisional: true',
            f"values come from an unreviewed result; open review {review['state']} cycle {review['cycle_id']}",
            f"claim scope under review: {notice['claim_scope']}",
            'a reviewed fill supersedes these values; do not use them for a claim or submission']


# ---------------------------------------------------------------- results
class Result:
    """One accepted binned result: weighted quantities or a simple binned table."""

    def __init__(self, raw, *, weight=None):
        from ravel.physics.quantities import validate_binning
        doc = _json(raw, 'result')
        kind = doc.get('kind') if isinstance(doc, dict) else None
        self.kind = kind
        normalization = doc.get('normalization', {}) if isinstance(doc, dict) else {}
        self.fraction_normalized = (normalization.get('histogram_mode') in ('fraction', 'density')
                                    or normalization.get('kind') == 'shape')
        if kind == 'weighted_quantities':
            if doc.get('finalization_pending') is not False:
                raise ValueError('weighted quantity result is not finalized')
            contract = doc['contract']
            names = contract['weight_names']
            if weight is None:
                if len(names) != 1:
                    raise ValueError(f'result has weights {names}; choose one with --weight')
                weight = names[0]
            if weight not in names:
                raise ValueError(f'weight {weight!r} is not in the result')
            self.weight = weight
            self.axes = [{'name': a['name'], 'unit': a['unit']} for a in contract['axes']]
            self.bins = [(tuple(map(float, b['low'])), tuple(map(float, b['high']))) for b in contract['bins']]
            self.values = [_number(v, 'result value') for v in doc['values'][weight]]
            self.unit = doc['unit']
            self.representation = contract['representation']
            n, k = len(self.bins), names.index(weight)
            order = [(r['weight'], r['bin_id']) for r in doc['covariance_order']]
            expected = [(name, b['id']) for name in names for b in contract['bins']]
            if order != expected:
                raise ValueError('result covariance order differs from its contract')
            self.covariance = [row[k*n:(k+1)*n] for row in doc['covariance'][k*n:(k+1)*n]]
            self.flow = {'combined_sumw': doc['flow'][weight]['sumw'], 'unit': doc['flow'][weight]['unit'],
                         'separable': False}
            self.overflow = self.underflow = None
            self.overflow_in_last = self.underflow_in_first = False
        elif kind == 'binned_values':
            from ravel.physics.binned_values import validate, KEYS
            validate(doc)
            allowed = KEYS
            if set(doc) - allowed or not {'schema_version', 'kind', 'axes', 'unit', 'representation', 'bins'} <= set(doc):
                raise ValueError(f'binned_values result accepts only {sorted(allowed)}')
            if doc['schema_version'] != 1 or doc['representation'] not in ('integrated', 'differential'):
                raise ValueError('binned_values version 1 with integrated or differential representation required')
            if weight is not None:
                raise ValueError('a binned_values result has one value column; --weight does not apply')
            self.weight = None
            self.axes = [{'name': a['name'], 'unit': a['unit']} for a in doc['axes']]
            self.unit, self.representation = _text(doc['unit']), doc['representation']
            if not self.unit:
                raise ValueError('binned_values result must state its value unit')
            self.bins, self.values, sigma = [], [], []
            for b in doc['bins']:
                if not isinstance(b, dict) or not {'low', 'high', 'value'} <= set(b) <= {'low', 'high', 'value', 'uncertainty', 'sumw2'}:
                    raise ValueError('result bins need low, high, value and optional uncertainty')
                self.bins.append((tuple(_number(x, 'result edge') for x in b['low']),
                                  tuple(_number(x, 'result edge') for x in b['high'])))
                self.values.append(_number(b['value'], 'result value'))
                variance = b.get('sumw2', doc.get('sumw2', [None] * len(doc['bins']))[len(sigma)])
                sigma.append(_number(b['uncertainty'], 'result uncertainty') if 'uncertainty' in b
                             else math.sqrt(variance) if variance is not None else None)
            if any(s is not None and s < 0 for s in sigma):
                raise ValueError('result uncertainties must be non-negative')
            self.covariance = doc.get('covariance')
            self.sigma = sigma
            self.overflow = None if 'overflow' not in doc else _number(doc['overflow'], 'overflow')
            self.underflow = None if 'underflow' not in doc else _number(doc['underflow'], 'underflow')
            self.overflow_in_last = doc.get('overflow_in_last_bin', False) is True
            self.underflow_in_first = doc.get('underflow_in_first_bin', False) is True
            if self.overflow_in_last and self.overflow is not None or self.underflow_in_first and self.underflow is not None:
                raise ValueError('result declares flow both inside its edge bin and separately')
            self.flow = {'overflow': self.overflow, 'underflow': self.underflow,
                         'overflow_in_last_bin': self.overflow_in_last, 'underflow_in_first_bin': self.underflow_in_first,
                         'separable': True}
            combined = (doc.get('provenance') or {}).get('combined_flow')
            if combined is not None:
                if self.overflow is not None or self.underflow is not None or self.overflow_in_last or self.underflow_in_first:
                    raise ValueError('combined flow cannot also be declared separately or inside an edge bin')
                self.flow = {**combined, 'separable': False}
        else:
            raise ValueError('result must be a weighted_quantities or binned_values document')
        self.volumes = validate_binning(self.axes, [{'id': str(i), 'low': list(lo), 'high': list(hi)}
                                                    for i, (lo, hi) in enumerate(self.bins)])

    def uncertainty(self, weights):
        """Standard deviation of sum(w_i * value_i), or None when correlations are unknown."""
        if self.covariance is not None:
            var = sum(wi * self.covariance[i][j] * wj for i, wi in weights.items() for j, wj in weights.items())
            return math.sqrt(max(var, 0.0))
        if len(weights) == 1:
            (i, w), = weights.items()
            return None if self.sigma[i] is None else abs(w) * self.sigma[i]
        return None


# ---------------------------------------------------------------- matching
def _tiles(target, parts, result):
    """True when result bins `parts` exactly cover the rectangle `target` without gaps."""
    lo, hi = target
    if any(any(a < l or b > h for a, b, l, h in zip(result.bins[j][0], result.bins[j][1], lo, hi)) for j in parts):
        return False
    volume = math.prod(h - l for l, h in zip(lo, hi))
    covered = sum(result.volumes[j] for j in parts)
    return math.isclose(covered, volume, rel_tol=1e-12, abs_tol=0.0)


def _bind(template, result, rebinning):
    if len(template.axes) != len(result.axes):
        raise ValueError('template and result have different numbers of axes')
    units = []
    for t, r in zip(template.axes, result.axes):
        if t['unit'] is not None and t['unit'] != r['unit']:
            raise ValueError(f"axis unit differs: template {t['unit']!r}, result {r['unit']!r}; units are never converted")
        units.append({'template_name': t['name'], 'template_unit': t['unit'], 'result_name': r['name'], 'result_unit': r['unit']})
    if template.unit is not None and template.unit != result.unit:
        raise ValueError(f'value unit differs: template {template.unit!r}, result {result.unit!r}; units are never converted')
    over, under = template.conventions['overflow'], template.conventions['underflow']
    if result.fraction_normalized and (result.overflow is not None or result.underflow is not None):
        raise ValueError('a fraction-normalised result carries separate flow; fold flow before normalising')
    for name, value, declaration, options in (('overflow', result.overflow, over, OVERFLOW),
                                             ('underflow', result.underflow, under, UNDERFLOW)):
        if value is not None and declaration is None:
            raise ValueError(f'result carries separate {name} but no convention is declared; '
                             f'choose --{name} ({"/".join(options)}) with --flow-evidence or a template qualifier')
    if (over in ('last-bin',) or under in ('first-bin',)) and result.representation != 'integrated':
        raise ValueError('flow placement needs integrated values; a differential result cannot absorb flow')
    if (over == 'last-bin' or under == 'first-bin') and not result.flow['separable']:
        raise ValueError('this result records flow as one combined sum (under- and overflow together); '
                         'it cannot fill a template bin that includes overflow or underflow')
    if over != 'last-bin' and result.overflow_in_last:
        raise ValueError('result last bin includes overflow but the template does not declare overflow in its last bin')
    if under != 'first-bin' and result.underflow_in_first:
        raise ValueError('result first bin includes underflow but the template does not declare underflow in its first bin')
    exact = {(lo, hi): j for j, (lo, hi) in enumerate(result.bins)}
    merges = {}
    if rebinning is not None:
        if (not isinstance(rebinning, dict) or set(rebinning) != {'schema_version', 'reason', 'merges'}
                or rebinning['schema_version'] != 1 or not _text(rebinning['reason'])
                or not isinstance(rebinning['merges'], list) or not rebinning['merges']):
            raise ValueError('rebinning needs schema_version 1, a stated reason and merges')
        for m in rebinning['merges']:
            if not isinstance(m, dict) or set(m) != {'template_bin', 'result_bins'}:
                raise ValueError('each merge names template_bin and result_bins')
            t, parts = m['template_bin'], m['result_bins']
            if type(t) is not int or not 0 <= t < len(template.bins) or t in merges:
                raise ValueError('merge template_bin must be a distinct template row index')
            if (not isinstance(parts, list) or len(parts) < 2 or len(set(parts)) != len(parts)
                    or any(type(j) is not int or not 0 <= j < len(result.bins) for j in parts)):
                raise ValueError('merge result_bins must list two or more distinct result bin indices')
            merges[t] = list(parts)
    last = len(template.bins) - 1
    edge = {}
    if over == 'last-bin':
        edge[last] = 'overflow'
    if under == 'first-bin':
        edge[0] = 'underflow' if 0 not in edge else 'both'
    if set(edge) & set(merges):
        raise ValueError('a bin that absorbs flow is filled from the flow convention, not a declared merge')
    rows, used = [], set()
    for i, (lo, hi) in enumerate(template.bins):
        if i in merges:
            parts = merges[i]
            if not _tiles((lo, hi), parts, result):
                raise ValueError(f'declared merge for template bin {i} does not tile its edges exactly')
            operation = 'declared-merge'
        elif i in edge:
            low = -math.inf if edge[i] in ('underflow', 'both') else lo[0]
            high = math.inf if edge[i] in ('overflow', 'both') else hi[0]
            parts = [j for j, (rl, rh) in enumerate(result.bins) if rl[0] >= low and rh[0] <= high]
            parts.sort(key=lambda j: result.bins[j][0][0])
            if not parts or (edge[i] == 'overflow' and result.bins[parts[0]][0][0] != lo[0]) \
                    or (edge[i] == 'underflow' and result.bins[parts[-1]][1][0] != hi[0]):
                raise ValueError(f'result bins do not start exactly at template bin {i} edges')
            for a, b in zip(parts, parts[1:]):
                if result.bins[a][1][0] != result.bins[b][0][0]:
                    raise ValueError(f'result bins absorbed into template bin {i} leave a gap')
            if edge[i] in ('overflow', 'both') and result.overflow is None and not result.overflow_in_last:
                raise ValueError('template last bin includes overflow but the result gives no overflow content')
            if edge[i] in ('underflow', 'both') and result.underflow is None and not result.underflow_in_first:
                raise ValueError('template first bin includes underflow but the result gives no underflow content')
            if result.overflow_in_last and edge[i] in ('overflow', 'both') and parts[-1] != len(result.bins) - 1:
                raise ValueError('result overflow sits in a bin outside the template last bin')
            operation = {'overflow': 'includes-overflow', 'underflow': 'includes-underflow', 'both': 'includes-underflow-and-overflow'}[edge[i]]
        else:
            if (lo, hi) not in exact:
                raise ValueError(f'template bin {i} {list(lo)}-{list(hi)} has no result bin with exactly these edges; '
                                 'declare a rebinning or produce the result on the template edges')
            parts, operation = [exact[(lo, hi)]], 'exact'
        if used & set(parts):
            raise ValueError('a result bin would fill two template bins')
        used |= set(parts)
        rows.append({'template_index': i, 'low': list(lo), 'high': list(hi), 'result_bins': parts, 'operation': operation})
    return rows, used, units


def _values(template, result, rows):
    integrated = result.representation == 'integrated'
    template_total = result_total = 0.0
    for row in rows:
        lo, hi = row['low'], row['high']
        volume = math.prod(h - l for l, h in zip(lo, hi))
        if integrated:
            weights = {j: 1.0 for j in row['result_bins']}
        else:
            weights = {j: result.volumes[j] / volume for j in row['result_bins']}
        value = math.fsum(w * result.values[j] for j, w in weights.items())
        added = []
        if row['operation'] in ('includes-overflow', 'includes-underflow-and-overflow') and result.overflow is not None:
            value += result.overflow
            added.append({'flow': 'overflow', 'value': result.overflow})
        if row['operation'] in ('includes-underflow', 'includes-underflow-and-overflow') and result.underflow is not None:
            value += result.underflow
            added.append({'flow': 'underflow', 'value': result.underflow})
        # Flow content carries no per-bin uncertainty of its own here, so none is propagated.
        sigma = None if added else result.uncertainty(weights)
        row.update(value=value, uncertainty=sigma, flow_added=added)
        result_total += math.fsum(result.values[j] * (1.0 if integrated else result.volumes[j]) for j in row['result_bins'])
        result_total += math.fsum(a['value'] for a in added)
        template_total += value * (1.0 if integrated else volume)
    if not math.isclose(template_total, result_total, rel_tol=1e-12, abs_tol=1e-300):
        raise ValueError('filled values do not preserve the result total')
    return template_total, result_total


# ---------------------------------------------------------------- acceptance
def delivery_gate_errors(rundir):
    """Epoch-two delivery gate for a filled template; an older contract keeps its review acceptance.

    A delegated run passes the whole wired ``delivery`` gate, exactly as result packaging
    does. A run without delegation delivers under its human approvals, so no machine decision
    case is asked of it; every refusal of the review-point provider still stands for it:
    pending points, standing findings, changed obligations, an action outside the plan, an
    unsafe fan-out, a required decision receipt and a requirement no accepted output maps to.
    """
    from . import gate_wiring, review_points
    rd = Path(rundir).resolve()
    action = gate_wiring.delivery_action(rd)
    errors = list(gate_wiring.delegated_errors(rd, 'delivery', action))
    # The wired gate of a delegated run already holds the review-point provider.
    if not errors and gate_wiring.epoch_two(rd) and not review_points._facts(rd)['delegated']:
        errors = list(review_points.gate_errors(rd, 'delivery', action))
    return errors


def accepted(result_path, *, rundir, claim_scope, base_dir):
    """Capture the result inside a current accepted review of `claim_scope`, past the delivery gate."""
    from . import task_completion as tc
    inputs = tc._Inputs(Path(base_dir).resolve())
    try:
        pin = inputs.capture(Path(result_path).resolve())
        refused = provisional_errors([pin['path']])
        if refused:
            raise ValueError(refused[0])
        rd, cycle = tc._accepted_review(str(Path(rundir).resolve()), claim_scope, inputs)
        gated = delivery_gate_errors(rd)
        if gated:
            raise ValueError('decision gate refuses delivery: '
                             + '; '.join(f'{e.provider}:{e.code}: {e.message}' for e in gated))
        if not tc._in_cycle(pin, rd, cycle):
            raise ValueError('the accepted review did not capture this result artifact')
        raw, _ = inputs.file(pin)
        inputs.finish()
    finally:
        inputs.close()
    from .architecture_receipt import label_delivery
    labelling = label_delivery(rd, [{'path': pin['path'], 'sha256': pin['sha256'], 'kind': 'number'}],
                               label='diagnostic' if claim_scope == 'diagnostic' else 'accepted')
    # `accepted` is the scientific delivery label; a diagnostic scope never carries it, though
    # the result was captured by the current accepted review of that scope.
    return raw, pin, {'rundir': str(rd), 'claim_scope': claim_scope,
                     'review_sequence': cycle['sequence'], 'review_accepted': True,
                     'accepted': labelling['delivery_label'] == 'accepted', **labelling}


def captured(result_path, *, rundir, claim_scope, base_dir):
    """Capture an unreviewed output that a valid stage receipt pins and an open review examines."""
    from . import execution, physics_review, study_deadline
    from . import task_completion as tc
    inputs = tc._Inputs(Path(base_dir).resolve())
    try:
        pin = inputs.capture(Path(result_path).resolve())
        refused = provisional_errors([pin['path']])
        if refused:
            raise ValueError(refused[0])
        rd = Path(rundir).resolve()
        session = inputs.review_session(rd)
        state = execution.load_execution(rd)
        receipts = [name for name, record in sorted(state['stages'].items())
                    if isinstance(record, dict) and record.get('status') == 'succeeded'
                    and _receipt_pins(record, pin)]
        receipts = [name for name in receipts if not execution.stage_errors(rd, name, state, _session=session)]
        if not receipts:
            raise ValueError('no valid stage receipt pins this output; a provisional fill takes only a captured result')
        view = physics_review.status(rd, _session=session)
        if view.get('state') == 'accepted':
            raise ValueError('the review has accepted; fill from the accepted result without --provisional')
        if view.get('state') not in study_deadline.OPEN_REVIEW:
            raise ValueError(f"a provisional fill needs an open, unresolved review; review state is {view.get('state')!r}")
        reg, events = physics_review._read(rd, _session=session)
        cycle = physics_review._view(reg, events)['cycle']
        if not tc._in_cycle(pin, rd, cycle):
            raise ValueError('the open review is not examining this result artifact')
        raw, _ = inputs.file(pin)
        inputs.finish()
    finally:
        inputs.close()
    record = state['stages'][receipts[0]]
    return raw, pin, {'rundir': str(rd), 'claim_scope': claim_scope, 'accepted': False,
                      'receipt': {'stage': receipts[0], 'attempt_id': record.get('attempt_id'),
                                  'receipt_sha256': record.get('receipt_sha256')},
                      'open_review': {'state': view['state'], 'cycle_id': view.get('cycle_id'),
                                      'review_sequence': cycle['sequence'], 'attestation': view.get('attestation')}}


def _receipt_pins(record, pin):
    """True when a stage's committed output snapshot holds these exact bytes at this path."""
    target = Path(pin['path'])
    for key, entry in (record.get('output_snapshot') or {}).items():
        root = Path(key)
        if target != root and not target.is_relative_to(root):
            continue
        name = '.' if target == root else target.relative_to(root).as_posix()
        if any(f.get('name') == name and f.get('sha256') == pin['sha256'] and f.get('size') == pin['size']
               for f in entry.get('files', [])):
            return True
    return False


def provisional_errors(paths):
    """Errors for every path that is a provisional fill or its record; [] when none is.

    Claims, CHECK-IN 3 records, submission exports and accepted fills call this so a
    provisional delivery can never stand in for reviewed evidence.
    """
    errors = []
    for value in paths:
        path = Path(value)
        sidecar = path.with_name(path.name + '.provenance.json')
        for candidate in (path, sidecar):
            if candidate.is_symlink() or not candidate.is_file() or candidate.stat().st_size > MAX_BYTES:
                continue
            raw = candidate.read_bytes()
            if raw.startswith(PROVISIONAL_MARK.encode()) or _provisional_document(raw):
                errors.append(f'{path} is a provisional fill; a claim, CHECK-IN 3 record or export '
                              'requires the accepted, reviewed result')
                break
    return errors


def _provisional_document(raw):
    try:
        document = json.loads(raw)
    except (ValueError, UnicodeError, RecursionError):
        return False
    if not isinstance(document, dict):
        return False
    return (isinstance(document.get('provisional'), dict) and document['provisional'].get('provisional') is True
            or document.get('kind') in ('filled-result-template', 'provisional-fill-supersession')
            and document.get('provisional') is True)


# ---------------------------------------------------------------- public entry
def fill(template, result, out, *, rundir, claim_scope, base_dir=None, table=None, column=None,
         weight=None, rebinning=None, uncertainty_label=None, overflow=None, underflow=None,
         flow_evidence=None, deliver_into=None, require_nonnegative=False, provisional=False,
         supersedes=None):
    """Write a filled copy of `template` and its provenance; return the provenance record.

    `rebinning` is an optional declared merge document (dict). `uncertainty_label`
    writes each bin's propagated standard deviation as a symmetric HEPData error
    with that label; without it only values are written. `provisional` fills from a
    receipt-pinned output under an open review, only inside a declared deadline
    margin. `supersedes` names the provenance record of a provisional fill that
    this reviewed fill replaces in `deliver_into`.
    """
    from ravel.controller.sink import legacy as sink_legacy
    for path in (rundir, out, deliver_into):
        sink_legacy.refuse_controller_owned(path, 'template fill')
    if type(provisional) is not bool:
        raise ValueError('provisional must be explicit')
    if provisional and supersedes is not None:
        raise ValueError('a provisional fill never supersedes; only a reviewed fill does')
    if supersedes is not None and deliver_into is None:
        raise ValueError('superseding a provisional fill replaces its requester file; give deliver-into')
    deadline = None
    if provisional:
        from . import study_deadline
        deadline = study_deadline.require_margin(rundir)
    out = Path(out)
    provenance_path = out.with_name(out.name + '.provenance.json')
    for p in (out, provenance_path):
        if p.exists() or p.is_symlink():
            raise ValueError(f'{p} already exists; filled templates are never overwritten')
    template_raw = _read(template)
    template_hash = hashlib.sha256(template_raw).hexdigest()
    target = None if deliver_into is None else Path(deliver_into)
    superseded, before_hash = None, template_hash
    if target is not None:
        if target.resolve() in (out.resolve(), provenance_path.resolve()):
            raise ValueError('deliver-into must differ from --out and its provenance path')
        if supersedes is not None:
            superseded = _superseded(Path(supersedes), target, template_hash)
            before_hash = superseded['delivered_sha256']
        _delivery_pin(target, before_hash)
    shape = Template(template, template_raw, table=table, column=column,
                     overflow=overflow, underflow=underflow, flow_evidence=flow_evidence)
    if uncertainty_label is not None and (shape.format == 'table-json' or not _text(uncertainty_label)):
        raise ValueError('an uncertainty label applies to HEPData templates and must be nonempty')
    base = Path(base_dir if base_dir is not None else Path(result).resolve().parent)
    if provisional and shape.format != 'hepdata-yaml' and 'provisional' in shape.original[0]:
        raise ValueError('the template already uses the provisional key; it cannot carry a provisional notice')
    capture = captured if provisional else accepted
    result_raw, result_pin, acceptance = capture(result, rundir=rundir, claim_scope=claim_scope, base_dir=base)
    data = Result(result_raw, weight=weight)
    rows, used, units = _bind(shape, data, rebinning)
    template_total, result_total = _values(shape, data, rows)
    values = [r['value'] for r in rows]
    for i, value in enumerate(values):
        _number(value, f'filled value in bin {i}')
        if require_nonnegative and value < 0:
            raise ValueError(f'negative filled value in bin {i} ({rows[i]["low"]}-{rows[i]["high"]}): {value}')
    sigmas = [r['uncertainty'] for r in rows]
    if uncertainty_label is not None and any(s is None for s in sigmas):
        raise ValueError('an uncertainty is unavailable for at least one bin; fill values only')
    documents = shape.filled(values, sigmas, uncertainty_label)
    if not shape.unchanged_except_values(documents):
        raise ValueError('internal check failed: filling changed template content other than values')
    notice = None if not provisional else {'provisional': True, 'claim_scope': claim_scope,
                                           'open_review': {k: acceptance['open_review'][k] for k in ('state', 'cycle_id')}}
    payload = shape.dump(documents, notice)
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open('xb') as stream:
        stream.write(payload)
    record = {
        'schema_version': 1, 'kind': 'filled-result-template',
        'template': _pin(Path(template).resolve(), template_raw), 'template_format': shape.format,
        'table_index': shape.table, 'column': {'index': shape.column, 'name': shape.column_name},
        'result': result_pin, 'result_kind': data.kind, 'weight': data.weight, 'acceptance': acceptance,
        'output': _pin(out.resolve(), payload),
        'units': {'axes': units, 'value': {'template': shape.unit, 'result': data.unit}},
        'representation': data.representation,
        'conventions': {**shape.conventions, **shape.convention_provenance},
        'result_flow': data.flow,
        'rebinning': deepcopy(rebinning),
        'bins': rows,
        'unused_result_bins': [j for j in range(len(data.bins)) if j not in used],
        'totals': {'filled': template_total, 'from_result': result_total},
        'uncertainty_label': uncertainty_label,
        'edges_unchanged': True, 'values_from_result_only': True,
        'physics_validated': False,
        'provisional': provisional,
    }
    if provisional:
        record.update(open_review=acceptance['open_review'], notice=notice,
                      deadline={k: deadline[k] for k in ('deadline_utc', 'margin_s', 'source', 'now_utc', 'seconds_left')})
    excluded = {name: {'value': value, 'declaration': 'excluded', **shape.convention_provenance}
                for name, value in (('overflow', data.overflow), ('underflow', data.underflow))
                if value is not None and shape.conventions[name] == 'excluded'}
    if excluded:
        record['flow_excluded'] = excluded
    with provenance_path.open('x') as stream:
        stream.write(json.dumps(record, indent=2, sort_keys=True, allow_nan=False) + '\n')
    if target is not None:
        _deliver_into(target, before_hash, payload, shape, provisional)
        record['delivered_into'] = {'path': str(target.resolve()), 'sha256_before': before_hash,
                                    'sha256_after': hashlib.sha256(payload).hexdigest()}
        if superseded is not None:
            record['supersedes'] = {'provisional_record': superseded['pin'],
                                    'sidecar': str(superseded['sidecar'])}
        final = (json.dumps(record, indent=2, sort_keys=True, allow_nan=False) + '\n').encode()
        _replace_bytes(provenance_path, final)
        if superseded is not None:
            link = {'schema_version': 1, 'kind': 'provisional-fill-supersession', 'provisional': True,
                    'provisional_record': superseded['pin'],
                    'superseded_by': _pin(provenance_path.resolve(), final),
                    'requester_file': record['delivered_into'],
                    'reviewed_acceptance': acceptance}
            with superseded['sidecar'].open('x') as stream:
                stream.write(json.dumps(link, indent=2, sort_keys=True, allow_nan=False) + '\n')
    return record


def _superseded(record_path, target, template_hash):
    """Check that `target` still holds exactly what the named provisional fill delivered."""
    raw = _read(record_path)
    record = _json(raw, 'provisional record')
    if not isinstance(record, dict) or record.get('kind') != 'filled-result-template' or record.get('provisional') is not True:
        raise ValueError('supersedes must name the provenance record of a provisional fill')
    sidecar = record_path.with_name(record_path.name + SUPERSEDED_SUFFIX)
    if sidecar.exists() or sidecar.is_symlink():
        raise ValueError('this provisional fill has already been superseded')
    if (record.get('template') or {}).get('sha256') != template_hash:
        raise ValueError('the provisional fill used a different template')
    delivered = record.get('delivered_into') or {}
    if delivered.get('path') != str(target.resolve()):
        raise ValueError('the provisional fill was not delivered into this requester file')
    if hashlib.sha256(_read(target)).hexdigest() != delivered.get('sha256_after'):
        raise ValueError('the requester file changed since the provisional fill delivered into it')
    return {'pin': _pin(record_path.resolve(), raw), 'sidecar': sidecar, 'delivered_sha256': delivered['sha256_after']}


def _delivery_pin(path, template_hash):
    if hashlib.sha256(_read(path)).hexdigest() != template_hash:
        raise ValueError(f'deliver-into {path} changed or already holds values; sha256 differs from the template pin')


def _replace_bytes(path, payload, before_replace=None):
    """Stage bytes beside the target and atomically replace it, cleaning up on refusal."""
    fd, name = tempfile.mkstemp(prefix=f'.{path.name}.', suffix='.tmp', dir=path.parent)
    staged = Path(name)
    try:
        with os.fdopen(fd, 'wb') as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(staged, path.stat().st_mode & 0o777)
        if before_replace is not None:
            before_replace(staged)
        os.replace(staged, path)
    finally:
        staged.unlink(missing_ok=True)


def _deliver_into(path, template_hash, payload, shape, provisional=False):
    def check(staged):
        raw = staged.read_bytes()
        if shape.format == 'hepdata-yaml':
            import yaml
            documents = list(yaml.safe_load_all(raw.decode('utf8')))
        else:
            documents = [_json(raw, 'delivered template')]
        if not shape.unchanged_except_values(documents, provisional):
            raise ValueError('delivery changed template content other than values')
        _delivery_pin(path, template_hash)
    _replace_bytes(path, payload, check)


def deliver(fills, *, base_dir):
    """Fill every template a request supplied; each entry holds `fill` keyword arguments."""
    if not isinstance(fills, list) or not fills:
        raise ValueError('at least one template fill is required')
    return [fill(**{**entry, 'base_dir': entry.get('base_dir', base_dir)}) for entry in fills]


def main(argv=None):
    parser = argparse.ArgumentParser(prog='ravel fill-template', description=__doc__.splitlines()[0])
    parser.add_argument('--template', type=Path, required=True, help='supplied template (.yaml, .yml or .json)')
    parser.add_argument('--result', type=Path, required=True, help='accepted result (weighted_quantities or binned_values JSON)')
    parser.add_argument('--out', type=Path, required=True, help='filled template to write; provenance goes to OUT.provenance.json')
    parser.add_argument('--rundir', type=Path, required=True, help='study whose accepted review captured the result')
    parser.add_argument('--claim-scope', required=True, help='accepted review claim scope')
    parser.add_argument('--base', type=Path, help='evidence base directory (default: the result directory)')
    parser.add_argument('--table', type=int, help='table index when the template holds several tables')
    parser.add_argument('--column', help='dependent column index or header name when several are empty')
    parser.add_argument('--weight', help='weight stream of a weighted_quantities result')
    parser.add_argument('--rebinning', type=Path, help='declared merge document')
    parser.add_argument('--uncertainty-label', help='also write symmetric errors with this label')
    parser.add_argument('--overflow', choices=OVERFLOW, help='explicit overflow convention backed by template text')
    parser.add_argument('--underflow', choices=UNDERFLOW, help='explicit underflow convention backed by template text')
    parser.add_argument('--flow-evidence', help='verbatim template text supporting the flow declaration')
    parser.add_argument('--deliver-into', type=Path, help='atomically replace an unchanged copy of the pinned template')
    parser.add_argument('--require-nonnegative', action='store_true', help='refuse negative filled values for event yields')
    parser.add_argument('--provisional', action='store_true',
                        help='inside a declared deadline margin, fill from a receipt-pinned output under open review, labelled provisional')
    parser.add_argument('--supersedes', type=Path, help='provenance record of the provisional fill this reviewed fill replaces')
    args = parser.parse_args(argv)
    try:
        column = int(args.column) if args.column is not None and args.column.isdigit() else args.column
        rebinning = None if args.rebinning is None else _json(_read(args.rebinning), 'rebinning')
        record = fill(args.template, args.result, args.out, rundir=args.rundir, claim_scope=args.claim_scope,
                      base_dir=args.base, table=args.table, column=column, weight=args.weight,
                      rebinning=rebinning, uncertainty_label=args.uncertainty_label, overflow=args.overflow,
                      underflow=args.underflow, flow_evidence=args.flow_evidence,
                      deliver_into=args.deliver_into, require_nonnegative=args.require_nonnegative,
                      provisional=args.provisional, supersedes=args.supersedes)
    except (OSError, ValueError, KeyError, TypeError, AttributeError, IndexError) as exc:
        parser.exit(1, f'fill-template refused: {exc}\n')
    print(json.dumps({'output': record['output'], 'bins': len(record['bins']), 'acceptance': record['acceptance'],
                      'provisional': record['provisional']}, indent=2, sort_keys=True))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
