"""Deterministic scorer for the tool-selection battery: restraint as well as recall.

A plan names the operations, checks, roles and knowledge entries a request needs, the operations
it must not draw on, how many consults it may spend, and the ambiguities that must be asked about.
A submission is what an agent (or a stub) actually selected. The scorer reports:

- the unnecessary native-operation rate and count (a native operation the plan does not expect);
- unnecessary consults (spent beyond the plan's limit, one by default);
- cost-weighted precision over the submitted operations;
- the under-call rate on twin plans (twins need a tool that their negative sibling does not);
- per-field precision and recall for operations, checks, roles and knowledge;
- must-ask ambiguity recall, scored by meaning (id or accepted phrase), not exact string.

Entries marked ``(NEW: <tag>)`` depend on work that has not landed. They are listed as
``expected_after_landing`` and leave precision and recall untouched until the tag is passed in
``landed``. The held-out battery is never loaded here: ``HeldOutBattery`` is an interface that a
caller outside this package implements, and this module holds no path to it.
"""
from __future__ import annotations

import abc
import hashlib
import json
import re
from pathlib import Path

FIELDS = {'operations': 'expected_operations', 'checks': 'expected_checks',
          'roles': 'expected_roles', 'knowledge': 'expected_knowledge'}
KINDS = ('sibling', 'negative', 'minimal', 'twin')
NATIVE_EFFECTS = frozenset({'executes_native', 'generates_events', 'simulates_detector', 'runs_authored_code'})
COST_BY_EFFECT = {'generates_events': 20.0, 'simulates_detector': 10.0, 'runs_authored_code': 10.0,
                  'executes_native': 5.0}
COST_OTHER_EFFECT = 2.0
COST_PLAIN = 1.0
DEFAULT_CONSULT_LIMIT = 1

_NEW = re.compile(r'\s*\(NEW:\s*([^)]+?)\s*\)\s*$')
_OPTIONAL = re.compile(r'^\s*\(optional\)\s*', re.I)
_ARROW = re.compile(r'\s*(?:→|->)\s*')
_SIGNATURES = Path(__file__).resolve().parents[1] / 'data' / 'operation_signatures.json'

# Identifier shapes that never belong in an exported synthetic plan.
IDENTIFIER_PATTERNS = (
    re.compile(r'arxiv\s*:?\s*\d', re.I),
    re.compile(r'\b\d{4}\.\d{4,5}(?:v\d+)?\b'),
    re.compile(r'\b(?:ATLAS|CMS|LHCb|ALICE)[-\s][A-Z]{2,6}[-\s]\d{2,4}(?:[-\s]\d{1,3})?\b'),
    re.compile(r'\b[A-Z]{3,5}-\d{2,4}-\d{2,3}\b'),
    re.compile(r'\bCERN-(?:EP|PH)-\d'),
    re.compile(r'\b10\.\d{4,}/\S+'),
    re.compile(r'\bins(?:pire)?\s*:?\s*\d{5,}\b', re.I),
    re.compile(r'\bhepdata\s*:?\s*ins\d', re.I),
)


# ---- operation vocabulary -------------------------------------------------------------------
def _effects():
    document = json.loads(_SIGNATURES.read_text())
    return {'op:' + name: tuple(sig.get('effects', ())) for name, sig in document['operations'].items()}


def native_operations(effects=None):
    """Atlas ids of registered operations whose declared effects run native or authored code."""
    effects = _effects() if effects is None else effects
    return frozenset(op for op, declared in effects.items() if NATIVE_EFFECTS & set(declared))


def operation_cost(op, effects):
    declared = set(effects.get(op, ()))
    costs = [COST_BY_EFFECT[e] for e in declared if e in COST_BY_EFFECT]
    if costs:
        return max(costs)
    return COST_OTHER_EFFECT if declared else COST_PLAIN


# ---- entry parsing --------------------------------------------------------------------------
def split_new(entry):
    """``'conv:x (NEW: SG-1)'`` -> ``('conv:x', 'SG-1')``; an unmarked entry has tag ``None``."""
    entry = entry.strip()
    match = _NEW.search(entry)
    if not match:
        return entry, None
    return entry[:match.start()].strip(), match.group(1)


def _atoms(entry):
    """Entries of the operation field may be ordered chains and may be optional."""
    optional = bool(_OPTIONAL.match(entry))
    body = _OPTIONAL.sub('', entry)
    body, tag = split_new(body)
    return [(atom.strip(), optional, tag) for atom in _ARROW.split(body) if atom.strip()]


def flatten_operations(entries):
    return [atom for entry in entries for atom, _, _ in _atoms(entry)]


def required_operations(entries):
    return {atom for entry in entries for atom, optional, _ in _atoms(entry) if not optional}


def _field_entries(plan, field, landed):
    """Return (required, allowed, pending) id sets for one field; pending ids await landing."""
    required, allowed, pending = set(), set(), set()
    for raw in plan.get(FIELDS[field], []):
        parts = _atoms(raw) if field == 'operations' else [(split_new(raw)[0], False, split_new(raw)[1])]
        for ident, optional, tag in parts:
            if tag is not None and tag not in landed:
                pending.add(ident)
                continue
            allowed.add(ident)
            if not optional:
                required.add(ident)
    return required, allowed, pending


def shape_of(plan):
    """Structure counts of a plan; siblings preserve these, never text."""
    entries = plan['expected_operations']
    new = sum(split_new(x)[1] is not None for k in ('expected_checks', 'expected_knowledge')
              for x in plan[k]) + sum(split_new(_OPTIONAL.sub('', x))[1] is not None for x in entries)
    return {'operations': len(entries), 'ordering_arrows': sum(len(_atoms(x)) - 1 for x in entries),
            'optional': sum(bool(_OPTIONAL.match(x)) for x in entries), 'checks': len(plan['expected_checks']),
            'roles': len(plan['expected_roles']), 'knowledge': len(plan['expected_knowledge']),
            'forbidden': len(plan['forbidden_operations']), 'new': new}


# ---- battery loading and validation ---------------------------------------------------------
def load_battery(directory):
    """Load every plan file (``*.json`` with a top-level ``plans`` list) in an exported directory."""
    plans = []
    for path in sorted(Path(directory).glob('*.json')):
        document = json.loads(path.read_text())
        if isinstance(document, dict) and 'plans' in document:
            plans.extend(document['plans'])
    return plans


def validate_plans(plans):
    errors, seen = [], set()
    by_id = {p.get('case_id'): p for p in plans}
    for plan in plans:
        cid = plan.get('case_id')
        if cid in seen:
            errors.append(f'{cid}: duplicate case_id')
        seen.add(cid)
        if plan.get('kind') not in KINDS:
            errors.append(f'{cid}: kind must be one of {KINDS}')
        for key in ('request', 'notes', 'must_ask', 'expected_consults_max', 'forbidden_operations',
                    *FIELDS.values()):
            if key not in plan:
                errors.append(f'{cid}: missing {key}')
        for item in plan.get('must_ask', []):
            if not item.get('id') or not item.get('accept'):
                errors.append(f'{cid}: must_ask entries need id and accept phrases')
        if plan.get('kind') == 'twin':
            if plan.get('twin_of') not in by_id or by_id[plan['twin_of']].get('kind') not in ('negative', 'minimal'):
                errors.append(f'{cid}: twin_of must name a negative or minimal plan')
            if not required_operations(plan.get('expected_operations', [])):
                errors.append(f'{cid}: a twin needs at least one required operation')
        elif plan.get('kind') in ('negative', 'minimal') and 'situation' not in plan:
            errors.append(f'{cid}: restraint plans carry a situation tag')
        overlap = set(flatten_operations(plan.get('expected_operations', []))) & set(plan.get('forbidden_operations', []))
        if overlap:
            errors.append(f'{cid}: expected and forbidden operations overlap: {sorted(overlap)}')
    return errors


# ---- identifier scan (R-10) -----------------------------------------------------------------
def _tokens(text):
    return re.findall(r'[a-z0-9]+', text.lower())


def digest_terms(text):
    """Digests of every word and word-trigram of ``text``; the harness supplies these, never the words."""
    words = [w for w in _tokens(text) if len(w) >= 3]
    grams = words + [' '.join(words[i:i + 3]) for i in range(len(words) - 2)]
    grams += [' '.join(words[i:i + 2]) for i in range(len(words) - 1)]
    return frozenset(hashlib.sha256(g.encode()).hexdigest() for g in grams)


def _plan_text(plan):
    parts = [json.dumps(plan, ensure_ascii=False)]
    return '\n'.join(parts)


def scan_identifiers(plans, blocked_digests=frozenset()):
    """Return findings: paper-identifier shapes, plus anything matching harness-supplied digests."""
    findings = []
    for plan in plans:
        text = _plan_text(plan)
        for pattern in IDENTIFIER_PATTERNS:
            if pattern.search(text):
                findings.append(f"{plan.get('case_id')}: identifier shape {pattern.pattern}")
        if blocked_digests:
            hit = digest_terms(text) & blocked_digests
            if hit:
                findings.append(f"{plan.get('case_id')}: {len(hit)} blocked term digest(s)")
    return findings


# ---- scoring --------------------------------------------------------------------------------
def _ratio(num, den):
    return None if den == 0 else num / den


def _norm_text(text):
    return ' '.join(_tokens(str(text)))


def _asked(plan, submission):
    """Matched must-ask ids: the id itself, or any accepted phrase inside an asked text."""
    asked = [_norm_text(a) for a in submission.get('asked', [])]
    matched = []
    for item in plan.get('must_ask', []):
        phrases = [_norm_text(item['id'])] + [_norm_text(a) for a in item['accept']]
        if any(p and (p == a or p in a) for p in phrases for a in asked):
            matched.append(item['id'])
    return matched


def score_case(plan, submission, *, effects=None, landed=frozenset()):
    effects = _effects() if effects is None else effects
    native = native_operations(effects)
    landed = frozenset(landed)
    out = {'case_id': plan['case_id'], 'kind': plan['kind'], 'fields': {}, 'expected_after_landing': {},
           'counts': {}}
    for field in FIELDS:
        required, allowed, pending = _field_entries(plan, field, landed)
        chosen = set(submission.get(field, ()))
        chosen_scored = chosen - pending
        hit = chosen_scored & allowed
        out['fields'][field] = {'precision': _ratio(len(hit), len(chosen_scored)),
                                'recall': _ratio(len(required & chosen), len(required))}
        out['counts'][field] = {'chosen': len(chosen_scored), 'hit': len(hit), 'required': len(required),
                                'recalled': len(required & chosen)}
        out['expected_after_landing'][field] = sorted(pending)
    required, allowed, pending = _field_entries(plan, 'operations', landed)
    expected_any = allowed | pending
    chosen_ops = [op for op in submission.get('operations', ())]
    scored_ops = [op for op in chosen_ops if op not in pending]
    unnecessary_native = sorted({op for op in chosen_ops if op in native and op not in expected_any})
    forbidden = sorted(set(chosen_ops) & set(plan.get('forbidden_operations', ())))
    weights = {op: operation_cost(op, effects) for op in scored_ops}
    out['unnecessary_native'] = unnecessary_native
    out['forbidden_violations'] = forbidden
    out['native_chosen'] = sorted({op for op in chosen_ops if op in native})
    out['cost'] = {'good': sum(weights[op] for op in scored_ops if op in allowed),
                   'total': sum(weights.values())}
    out['cost_weighted_precision'] = _ratio(out['cost']['good'], out['cost']['total'])
    limit = plan.get('expected_consults_max', DEFAULT_CONSULT_LIMIT)
    out['unnecessary_consults'] = max(0, int(submission.get('consults', 0)) - limit)
    out['missing_required_operations'] = sorted(required - set(chosen_ops))
    ask_total = len(plan.get('must_ask', []))
    matched = _asked(plan, submission)
    out['must_ask'] = {'total': ask_total, 'matched': matched}
    out['must_ask_recall'] = _ratio(len(matched), ask_total)
    return out


def _micro(cases, field, key):
    num = den = 0
    for case in cases:
        counts = case['counts'][field]
        if key == 'precision':
            num, den = num + counts['hit'], den + counts['chosen']
        else:
            num, den = num + counts['recalled'], den + counts['required']
    return _ratio(num, den)


def score_battery(plans, submissions, *, effects=None, landed=frozenset()):
    effects = _effects() if effects is None else effects
    by_case = {s.get('case_id'): s for s in submissions}
    cases = []
    for plan in plans:
        if plan['case_id'] not in by_case:
            raise ValueError(f"no submission for {plan['case_id']}")
        cases.append(score_case(plan, by_case[plan['case_id']], effects=effects, landed=landed))
    restraint = [c for c in cases if c['kind'] in ('negative', 'minimal')]
    twins = [c for c in cases if c['kind'] == 'twin']
    ask_cases = [c for c in cases if c['must_ask']['total']]
    cost_good = sum(c['cost']['good'] for c in cases)
    cost_total = sum(c['cost']['total'] for c in cases)
    chosen_native = sum(len(c['native_chosen']) for c in cases)
    unnecessary_native = sum(len(c['unnecessary_native']) for c in cases)
    over = [c for c in cases if c['unnecessary_consults']]
    return {
        'plans': len(cases),
        'unnecessary_native_operation_rate': _ratio(sum(bool(c['unnecessary_native']) for c in cases), len(cases)) or 0,
        'unnecessary_native_operations': {'total': unnecessary_native, 'of_native_chosen': chosen_native},
        'unnecessary_consults': {'total': sum(c['unnecessary_consults'] for c in cases),
                                 'plans_over_limit': len(over)},
        'cost_weighted_precision': _ratio(cost_good, cost_total),
        'under_call_rate_on_twins': _ratio(sum(bool(c['missing_required_operations']) for c in twins), len(twins)),
        'fields': {f: {'precision': _micro(cases, f, 'precision'), 'recall': _micro(cases, f, 'recall')}
                   for f in FIELDS},
        'must_ask_recall': _ratio(sum(len(c['must_ask']['matched']) for c in ask_cases),
                                  sum(c['must_ask']['total'] for c in ask_cases)),
        'restraint': {'plans': len(restraint),
                      'native_overcalls': sum(len(c['unnecessary_native']) for c in restraint),
                      'forbidden_violations': sum(len(c['forbidden_violations']) for c in restraint)},
        'expected_after_landing': {c['case_id']: c['expected_after_landing'] for c in cases
                                   if any(c['expected_after_landing'].values())},
        'cases': cases,
    }


# ---- stubs (no model, no native run) --------------------------------------------------------
def _submission(plan, operations, **extra):
    base = {'case_id': plan['case_id'], 'operations': operations, 'checks': [], 'roles': [],
            'knowledge': [], 'consults': 0, 'asked': []}
    base.update(extra)
    return base


def stub_oracle(plan):
    """The expected selection: everything required and already landed, every must-ask asked."""
    chosen = {}
    for field in FIELDS:
        required, _, _ = _field_entries(plan, field, frozenset())
        chosen[field] = sorted(required)
    return _submission(plan, chosen.pop('operations'), asked=[a['accept'][0] for a in plan.get('must_ask', [])],
                       **chosen)


def stub_overcall(plan, native_op):
    """The oracle selection plus one native operation and extra consults: the failure under test."""
    sub = stub_oracle(plan)
    sub['operations'] = sub['operations'] + [native_op]
    sub['consults'] = DEFAULT_CONSULT_LIMIT + 2
    return sub


def stub_empty(plan):
    """An agent that selects nothing: right on a negative plan, an under-call on every twin."""
    return _submission(plan, [])


# ---- held-out battery: interface only -------------------------------------------------------
class HeldOutBattery(abc.ABC):
    """Implemented by a caller outside this package; product code and CI never load a held-out battery."""

    @abc.abstractmethod
    def load(self):
        """Return the held-out plans in the plan format validated by ``validate_plans``."""


def score_held_out(loader, submissions, *, effects=None, landed=frozenset()):
    plans = loader.load()
    return score_battery(plans, submissions, effects=effects, landed=landed)
