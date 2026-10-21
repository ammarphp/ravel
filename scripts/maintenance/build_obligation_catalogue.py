#!/usr/bin/env python3
"""Compile the obligation catalogue of the controller's ledger from the census and the coverage table.

The catalogue is read-only package data (``src/ravel/data/obligations/catalogue.json``). It has one row per
coverage row: every census obligation plus the supplementary rows of the controller specification (bypass
switches, unread card fields, cross-family removals, judgment and controller duties). Each row carries its id,
ledger class, census category, mechanisms, enforcement class (E, L, R or I), the stage, scope and selector that
decide where a run instantiates it, the node that discharges it, its waivability and its source pin.

Applicability follows the specification's materialisation table: rows that apply to every run at intake, step,
point, check-in and gate rows at plan, role rows for each seat, review rows for each review seat, and delivery
rows for each delivered artifact. A selector whose fact is unknown at run time keeps its row (unknown
applicability stays on result paths). Waivability follows the specification's waiver table: authority, scope,
statistic and budget rows are waivable by the physicist or operator; independence, review credit, custody, sink,
confinement and the other integrity mechanisms are never waivable for an accepted result; instruction delivery
and acknowledgement are never waivable.

The catalogue also pins the digest of the decision-gate provider registry so that a controller run can refuse a
registry that differs from the one the catalogue was built with.

Usage:
  build_obligation_catalogue.py --census CENSUS.jsonl.gz --coverage coverage.csv [--out PATH]
  build_obligation_catalogue.py --census ... --coverage ... --check     exit 1 when PATH differs from a rebuild
  build_obligation_catalogue.py --refresh-pins [--out PATH]              re-pin the provider registry digest only
Standard library only. Exit 0 on success, 1 on drift or invalid input, 2 on usage error.
"""
from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import io
import json
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
OUT = REPO / 'src' / 'ravel' / 'data' / 'obligations' / 'catalogue.json'
PROVIDERS = REPO / 'src' / 'ravel' / 'data' / 'gates' / 'providers.json'
SCHEMA = 'obligation-catalogue.v1'

LEDGER_CLASSES = ('route', 'role/instruction', 'delegation/independence', 'authority/approval', 'execution/tool',
                  'review/credit', 'delivery/claims', 'budget/stop')
CLASSES = ('E', 'L', 'R', 'I')
MECHANISMS = tuple('M%02d' % n for n in range(1, 30))
SOURCE_KINDS = ('census-decision', 'census-structural', 'census-role-field', 'xreview-switch', 'spec-obligation',
                'unread-card-field', 'cross-family-removal')
CENSUS_KINDS = SOURCE_KINDS[:3]

# Documents that every governed plan delivers (check-in templates, the judgment-site rules): a census condition
# naming them holds for every controller plan. Any other conditional document must be among the plan's sources.
ALWAYS_DOCUMENTS = ('docs/workflow/checklists/check-ins.md', 'docs/workflow/README.md')

# Waiver table (CONTROLLER-SPEC 7.3). Only the four kinds the table names are waivable, by the physicist at the
# terminal or the operator's configuration (never a worker): authority requirements, scope, the requested statistic
# and budget ceilings. Instruction delivery and acknowledgement are never waivable. Every other row (independence,
# review credit, custody, sink, confinement, and the integrity of pins, authority sources, stop supervision,
# switch closures, labels and endings) is not waivable for an accepted result: unmet, it leaves the result a
# labelled diagnostic.
WAIVABLE = (
    ('authority', r'^(A01|A05|A08|A09|A11|C04|C07|C15|C31|CHECKIN-.+)$'),
    ('scope', r'^(R02|R03|R04|R05|R06|R07|R08|R09|R12|C26|ROUTE-.+)$'),
    ('statistic', r'^D02$'),
    ('budget', r'^(A07|B01|B02|C02|E21|CF02|ROLE-.+-stop)$'),
)
NEVER_MECHANISMS = ('M12', 'M13')
TEXT_LIMIT = 240

# Discharging node (base, before any [parameter]) -> (stage, scope, extra selector) for decision and supplementary
# rows. Stages: intake, plan, seat (every dispatched worker, launch or review seat), review (review seats only),
# deliver, event (instantiated when the decision or check-in occurs).
INTAKE_RUN = {'stage': 'intake', 'scope': 'run'}
NODE_RULES = {
    'controller.intake': INTAKE_RUN, 'controller.route_select': INTAKE_RUN, 'controller.resume': INTAKE_RUN,
    'controller.store': INTAKE_RUN, 'controller.command_policy': INTAKE_RUN, 'controller.stop': INTAKE_RUN,
    'controller.deviation': INTAKE_RUN, 'controller.escalation': INTAKE_RUN, 'controller.bounded_end': INTAKE_RUN,
    'authority.service': INTAKE_RUN, 'authority.terminal': INTAKE_RUN, 'authority.revocation': INTAKE_RUN,
    'authority.steering': INTAKE_RUN, 'authority.checkin': INTAKE_RUN, 'authority.deviation': INTAKE_RUN,
    'authority.r3': INTAKE_RUN, 'hosts.surface': INTAKE_RUN, 'ledger.gate': INTAKE_RUN,
    'ledger.parent_join': {'stage': 'intake', 'scope': 'deliverable'},
    # The controller's own plan checks, recorded when a plan is materialised (each revision re-records them).
    'controller.plan': {'stage': 'plan', 'scope': 'run'},
    'authority.ci1': {'stage': 'plan', 'scope': 'run'},
    'authority.ci2': {'stage': 'plan', 'scope': 'waypoint'},
    'authority.ci3': {'stage': 'plan', 'scope': 'run'},
    'authority.final': {'stage': 'plan', 'scope': 'run'},
    'judgment.classify': {'stage': 'plan', 'scope': 'run', 'select': {'has_step_kind': 'decide'}},
    'judgment.method_ladder': {'stage': 'plan', 'scope': 'step', 'select': {'step_kind': ['decide']}},
    'judgment.default': {'stage': 'plan', 'scope': 'step', 'select': {'step_kind': ['decide']}},
    'judgment.source_ladder': {'stage': 'plan', 'scope': 'step', 'select': {'step_kind': ['decide']}},
    'judgment.recovery': {'stage': 'plan', 'scope': 'step', 'select': {'step_kind': ['decide']}},
    'judgment.protocol': {'stage': 'plan', 'scope': 'step', 'select': {'step_kind': ['decide']}},
    'judgment.record': {'stage': 'plan', 'scope': 'step', 'select': {'step_kind': ['decide']}},
    'route.analysis': {'stage': 'plan', 'scope': 'run', 'select': {'route': ['analysis']}},
    'route.analysis.inputs': {'stage': 'plan', 'scope': 'run', 'select': {'route': ['analysis']}},
    'route.analysis.waypoint': {'stage': 'plan', 'scope': 'waypoint', 'select': {'route': ['analysis']}},
    'route.analysis.scan': {'stage': 'plan', 'scope': 'step', 'select': {'points': True}},
    'route.study.calculation': {'stage': 'plan', 'scope': 'run', 'select': {'route': ['calculation']}},
    'route.study.chain': {'stage': 'plan', 'scope': 'run', 'select': {'route': ['chain']}},
    'route.study.scoped': {'stage': 'plan', 'scope': 'run', 'select': {'route': ['scoped']}},
    'route.research': {'stage': 'plan', 'scope': 'run', 'select': {'route': ['research']}},
    'route.research.children': {'stage': 'plan', 'scope': 'run', 'select': {'route': ['research']}},
    'route.research.ideas': {'stage': 'plan', 'scope': 'run', 'select': {'route': ['research']}},
    'route.research.meta_review': {'stage': 'plan', 'scope': 'run', 'select': {'route': ['research']}},
    'route.research.prereg': {'stage': 'plan', 'scope': 'run', 'select': {'route': ['research']}},
    'route.research.stage': {'stage': 'plan', 'scope': 'run', 'select': {'route': ['research']}},
    'route.manuscript': {'stage': 'plan', 'scope': 'run', 'select': {'route': ['manuscript']}},
    'route.ml': {'stage': 'plan', 'scope': 'run', 'select': {'route': ['ml']}},
    'step.seat_derivation': {'stage': 'plan', 'scope': 'step'},
    'step.plan_bind': {'stage': 'plan', 'scope': 'step'},
    'step.reserve': {'stage': 'seat', 'scope': 'seat'},
    'step.preflight': {'stage': 'seat', 'scope': 'seat'},
    'step.packet': {'stage': 'seat', 'scope': 'seat'},
    'step.validate': {'stage': 'seat', 'scope': 'seat'},
    'step.adopt': {'stage': 'seat', 'scope': 'seat'},
    'step.reconcile': {'stage': 'seat', 'scope': 'seat'},
    'step.tool_observe': {'stage': 'seat', 'scope': 'seat'},
    'step.dispatch': {'stage': 'seat', 'scope': 'seat', 'select': {'seat_kind': ['worker', 'review']}},
    # A worker's escalation duties exist only when it escalates: the escalation occurrence instantiates them.
    'step.escalation': {'stage': 'event', 'scope': 'event', 'select': {'checkin': 'escalation'}},
    'step.consult': {'stage': 'seat', 'scope': 'seat', 'select': {'seat_kind': ['worker', 'review']}},
    'step.transport_select': {'stage': 'seat', 'scope': 'seat', 'select': {'seat_kind': ['worker', 'review']}},
    'step.launch': {'stage': 'seat', 'scope': 'seat', 'select': {'seat_kind': ['launch']}},
    'step.wms_submit': {'stage': 'seat', 'scope': 'seat', 'select': {'seat_kind': ['launch'], 'wms': True}},
    'step.acquire': {'stage': 'seat', 'scope': 'seat', 'select': {'step_kind': ['acquire']}},
    'step.compare': {'stage': 'seat', 'scope': 'seat', 'select': {'step_kind': ['compare']}},
    'step.pilot': {'stage': 'seat', 'scope': 'seat', 'select': {'rung': ['pilot']}},
    'confine.launch': {'stage': 'seat', 'scope': 'seat', 'select': {'seat_kind': ['launch']}},
    'confine.probe': {'stage': 'seat', 'scope': 'seat'},
    'confine.worker': {'stage': 'seat', 'scope': 'seat', 'select': {'seat_kind': ['worker', 'review']}},
    'step.observe': {'stage': 'seat', 'scope': 'seat'},
    'engagement.decide': {'stage': 'plan', 'scope': 'run'},
    'engagement.facts': {'stage': 'plan', 'scope': 'run'},
    'engagement.apply': {'stage': 'plan', 'scope': 'run'},
    'engagement.fold': {'stage': 'seat', 'scope': 'seat'},
    'engagement.observe': {'stage': 'event', 'scope': 'event'},
    'engagement.envelope': {'stage': 'deliver', 'scope': 'run'},
    'review.packet': {'stage': 'review', 'scope': 'seat'},
    'review.credit': {'stage': 'review', 'scope': 'seat'},
    'review.mustcheck': {'stage': 'review', 'scope': 'seat'},
    'review.cycle': {'stage': 'review', 'scope': 'seat'},
    'review.repair': {'stage': 'review', 'scope': 'seat', 'select': {'review_kind': ['repair']}},
    'review.crosscheck': {'stage': 'review', 'scope': 'seat', 'select': {'review_kind': ['crosscheck']}},
    'review.certify': {'stage': 'review', 'scope': 'seat', 'select': {'review_kind': ['certify']}},
    'review.final': {'stage': 'review', 'scope': 'seat', 'select': {'review_kind': ['final']}},
    'rdj.case': {'stage': 'review', 'scope': 'seat', 'select': {'review_kind': ['rdj']}},
    'controller.deliver': {'stage': 'deliver', 'scope': 'run'},
}
# Delivery rows instantiated per delivered artifact (CONTROLLER-SPEC 7.2); the other sink rows are per delivery.
ARTIFACT_ROWS = re.compile(r'^(D\d+|C22|C27|E20|E25|E26)$')
# Per scan point (the point rows of the scan node); the other scan-node rows are per scan step.
POINT_ROWS = ('P04', 'E24')

# Decision gates (decision_gate.GATES): when the instance exists. Event gates are instantiated when the decision
# occurs or when a plan declares them.
GATE_RULES = {
    'approve_plan': {'stage': 'plan', 'scope': 'run'},
    'launch': {'stage': 'plan', 'scope': 'step', 'select': {'launches': True}},
    'checkin2_accept': {'stage': 'plan', 'scope': 'waypoint'},
    'delivery': {'stage': 'deliver', 'scope': 'run'},
    'final_task': {'stage': 'deliver', 'scope': 'run'},
}
CHECKIN_RULES = {
    '1': {'stage': 'plan', 'scope': 'run'}, '3': {'stage': 'plan', 'scope': 'run'},
    'final': {'stage': 'plan', 'scope': 'run'}, '2': {'stage': 'plan', 'scope': 'waypoint'},
}


class CatalogueError(ValueError):
    pass


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def canonical(value) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False).encode()


def node_base(node: str) -> str:
    return node.split('[', 1)[0]


def read_census(path: Path) -> dict:
    rows = {}
    with gzip.open(path, 'rt', encoding='utf-8') as handle:
        for number, line in enumerate(handle, 1):
            if not line.strip():
                continue
            row = json.loads(line)
            if row['id'] in rows:
                raise CatalogueError('census line %d repeats id %s' % (number, row['id']))
            rows[row['id']] = row
    return rows


def read_coverage(path: Path) -> list[dict]:
    with open(path, newline='', encoding='utf-8') as handle:
        rows = list(csv.DictReader(handle))
    seen = set()
    for row in rows:
        if row['row_id'] in seen:
            raise CatalogueError('coverage repeats id %s' % row['row_id'])
        seen.add(row['row_id'])
    return rows


def waivability(row: dict) -> tuple[str, str | None]:
    """(waivability, waiver kind): 'authority' with its kind, 'never' or 'diagnostic'."""
    if row['class'] == 'I' or any(m in row['mechanisms'] for m in NEVER_MECHANISMS):
        return 'never', None
    for kind, pattern in WAIVABLE:
        if re.match(pattern, row['id']):
            return 'authority', kind
    return 'diagnostic', None


def condition_document(census_routes: str) -> str | None:
    if not census_routes.startswith('conditional:'):
        return None
    document = census_routes.split(':', 1)[1].strip()
    return None if document in ALWAYS_DOCUMENTS else document


def with_select(rule: dict, **extra) -> dict:
    select = dict(rule.get('select') or {})
    select.update({k: v for k, v in extra.items() if v is not None})
    result = {'stage': rule['stage'], 'scope': rule['scope']}
    if select:
        result['select'] = dict(sorted(select.items()))
    return result


def structural_applicability(rid: str, census: dict) -> dict:
    prefix, name = rid.split('-', 1)
    if prefix == 'ROUTE':
        return {'stage': 'intake', 'scope': 'run', 'select': {'task_mode': name}}
    if prefix in ('TOOL', 'EXEC', 'HOST'):
        return {'stage': 'plan', 'scope': 'step', 'select': {'operation': name}}
    if prefix == 'MODE':
        return {'stage': 'plan', 'scope': 'step', 'select': {'mode': name}}
    if prefix == 'STEP':
        return {'stage': 'plan', 'scope': 'step', 'select': {'workflow_step': name}}
    if prefix == 'STAGE':
        return {'stage': 'plan', 'scope': 'step', 'select': {'research_stage': name}}
    if prefix == 'CHECKIN':
        rule = CHECKIN_RULES.get(name, {'stage': 'event', 'scope': 'event'})
        return with_select(rule, checkin=name)
    if prefix == 'GATE':
        rule = GATE_RULES.get(name, {'stage': 'event', 'scope': 'event'})
        return with_select(rule, gate=name)
    raise CatalogueError('no applicability rule for structural row %s' % rid)


def role_applicability(rid: str, census: dict, node: str) -> dict:
    role = census['routes'].split(':', 1)[1]
    if not rid.startswith('ROLE-%s-' % role):
        raise CatalogueError('role row %s does not name its role %s' % (rid, role))
    if node_base(node) in ('step.seat_derivation', 'step.plan_bind'):
        return {'stage': 'plan', 'scope': 'step', 'select': {'role': role}}
    if node_base(node) == 'step.escalation':
        # Instantiated by the escalation occurrence of a seat of this role, never at every seat.
        return {'stage': 'event', 'scope': 'event', 'select': {'checkin': 'escalation', 'role': role}}
    return {'stage': 'seat', 'scope': 'seat', 'select': {'role': role}}


def decision_applicability(rid: str, node: str, census_routes: str | None) -> dict:
    base = node_base(node)
    if rid in ('JR10',):
        return dict(INTAKE_RUN)
    if rid.startswith('JR') or rid == 'R10':
        return {'stage': 'plan', 'scope': 'run', 'select': {'route': ['judgment']}}
    rule = NODE_RULES.get(base)
    if rule is None:
        raise CatalogueError('no applicability rule for node %s (row %s)' % (node, rid))
    document = condition_document(census_routes or 'all')
    if base == 'route.analysis.scan' and rid in POINT_ROWS:
        rule = {'stage': 'plan', 'scope': 'point'}
    if base == 'controller.deliver' and ARTIFACT_ROWS.match(rid):
        rule = {'stage': 'deliver', 'scope': 'artifact'}
    if document and rule['stage'] == 'intake':
        raise CatalogueError('conditional row %s cannot be selected at intake' % rid)
    return with_select(rule, document=document)


def source_pin(cov: dict, census: dict | None) -> tuple[str, str | None]:
    """(path[:line], census source digest). A supplementary row is pinned to the first path and line its source
    names; the rest of its free source text stays in the coverage table, outside the package."""
    if census is not None:
        line = census.get('line')
        return ('%s:%s' % (census['source'], line) if line else census['source']), census.get('source_sha256')
    text = ' '.join(cov['source'].split())
    match = re.match(r'([^\s:;,()]+)(?::(\d+))?', text)
    path = match.group(1) if match else text
    return ('%s:%s' % (path, match.group(2)) if match and match.group(2) else path), None


def short(text: str, limit: int = TEXT_LIMIT) -> str:
    text = ' '.join((text or '').split())
    return text if len(text) <= limit else text[:limit - 3].rstrip() + '...'


def build_row(cov: dict, census: dict | None) -> dict:
    rid = cov['row_id']
    kind = cov['source_kind']
    if kind not in SOURCE_KINDS:
        raise CatalogueError('row %s has unknown source kind %s' % (rid, kind))
    mechanisms = cov['mechanisms'].split()
    if not mechanisms or any(m not in MECHANISMS for m in mechanisms):
        raise CatalogueError('row %s has invalid mechanisms %r' % (rid, cov['mechanisms']))
    if cov['class_1_3_0'] not in CLASSES:
        raise CatalogueError('row %s has invalid class %r' % (rid, cov['class_1_3_0']))
    if cov['ledger_class'] not in LEDGER_CLASSES:
        raise CatalogueError('row %s has invalid ledger class %r' % (rid, cov['ledger_class']))
    # A row discharged by two nodes names the primary one first ("a.b + c.d"); the catalogue binds the primary
    # node and the coverage table keeps the rest.
    node = cov['graph_node'].split(' + ', 1)[0].strip()
    if not node or not cov['package'].strip():
        raise CatalogueError('row %s has no discharging node or package' % rid)
    if kind in CENSUS_KINDS and census is None:
        raise CatalogueError('census row %s is absent from the census' % rid)
    if kind == 'census-structural':
        applicability = structural_applicability(rid, census)
    elif kind == 'census-role-field':
        applicability = role_applicability(rid, census, node)
    else:
        applicability = decision_applicability(rid, node, census['routes'] if census else None)
    row = {
        'id': rid,
        'kind': kind,
        'ledger_class': cov['ledger_class'],
        'category': census['category'] if census else cov['census_category'],
        'class': cov['class_1_3_0'],
        'mechanisms': mechanisms,
        'node': node,
        'package': cov['package'].strip(),
        'applicability': applicability,
        'text': short(cov['obligation']),
    }
    row['source'], digest = source_pin(cov, census)
    if digest:
        row['source_sha256'] = digest
    if census is not None and census.get('result_path', True) is not True:
        row['result_path'] = False  # every row is on a result path unless the census says otherwise
    if census is not None and kind == 'census-structural' and rid.split('-', 1)[0] in ('TOOL', 'EXEC', 'MODE'):
        row['family'] = census['routes']
    row['waivability'], waiver = waivability(row)
    if waiver:
        row['waiver'] = waiver
    return row


def provider_pin(path: Path | None = None) -> dict:
    data = (path or PROVIDERS).read_bytes()
    registry = json.loads(data)
    return {'path': 'src/ravel/data/gates/providers.json', 'sha256': sha256_bytes(data),
            'providers': sorted(p['id'] for p in registry['providers'])}


def build(census_path: Path, coverage_path: Path, providers_path: Path | None = None) -> dict:
    census = read_census(census_path)
    coverage = read_coverage(coverage_path)
    census_in_coverage = {r['row_id'] for r in coverage if r['source_kind'] in CENSUS_KINDS}
    if census_in_coverage != set(census):
        missing = sorted(set(census) - census_in_coverage)[:10]
        extra = sorted(census_in_coverage - set(census))[:10]
        raise CatalogueError('census and coverage id sets differ (census only %s; coverage only %s)'
                             % (missing, extra))
    rows = [build_row(r, census.get(r['row_id'])) for r in coverage]
    sources = {}
    for row in rows:
        digest = row.get('source_sha256')
        if digest is None:
            continue
        path = row['source'].split(':', 1)[0]
        if sources.setdefault(path, digest) == digest:
            del row['source_sha256']  # the table below carries it; a differing digest stays on its row
    counts = {
        'rows': len(rows),
        'census_rows': len(census),
        'by_kind': {k: sum(r['kind'] == k for r in rows) for k in SOURCE_KINDS},
        'by_class': {c: sum(r['class'] == c for r in rows) for c in CLASSES},
        'by_ledger_class': {c: sum(r['ledger_class'] == c for r in rows) for c in LEDGER_CLASSES},
        'by_stage': {},
        'by_waivability': {},
    }
    for row in rows:
        stage = row['applicability']['stage']
        counts['by_stage'][stage] = counts['by_stage'].get(stage, 0) + 1
        counts['by_waivability'][row['waivability']] = counts['by_waivability'].get(row['waivability'], 0) + 1
    counts['by_stage'] = dict(sorted(counts['by_stage'].items()))
    counts['by_waivability'] = dict(sorted(counts['by_waivability'].items()))
    rows.sort(key=lambda r: r['id'])
    return {
        'schema': SCHEMA,
        'generated_by': 'scripts/maintenance/build_obligation_catalogue.py',
        'inputs': {
            'census': {'name': census_path.name, 'sha256': sha256_bytes(census_path.read_bytes()),
                       'rows': len(census)},
            'coverage': {'name': coverage_path.name, 'sha256': sha256_bytes(coverage_path.read_bytes()),
                         'rows': len(coverage)},
        },
        'gate_registry': provider_pin(providers_path),
        'source_digests': dict(sorted(sources.items())),
        'counts': counts,
        'rows_sha256': sha256_bytes(canonical(rows)),
        'rows': rows,
    }


def render(catalogue: dict) -> str:
    """One row per line under a sorted header, so a change to one row is a one-line diff."""
    head = {k: v for k, v in catalogue.items() if k != 'rows'}
    out = io.StringIO()
    out.write('{\n')
    for key in sorted(head):
        out.write('  %s: %s,\n' % (json.dumps(key), json.dumps(head[key], sort_keys=True, ensure_ascii=False)))
    out.write('  "rows": [\n')
    lines = [json.dumps(r, sort_keys=True, ensure_ascii=False, separators=(',', ':')) for r in catalogue['rows']]
    out.write(',\n'.join('    ' + line for line in lines))
    out.write('\n  ]\n}\n')
    return out.getvalue()


def refresh_pins(path: Path, providers_path: Path | None = None) -> dict:
    catalogue = json.loads(path.read_text(encoding='utf-8'))
    if catalogue.get('schema') != SCHEMA:
        raise CatalogueError('%s is not an %s file' % (path, SCHEMA))
    catalogue['gate_registry'] = provider_pin(providers_path)
    return catalogue


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split('\n', 1)[0])
    parser.add_argument('--census', type=Path)
    parser.add_argument('--coverage', type=Path)
    parser.add_argument('--out', type=Path, default=OUT)
    parser.add_argument('--population-out', type=Path, help='write the exact source-derived row population')
    parser.add_argument('--check', action='store_true', help='compare a rebuild with --out; change nothing')
    parser.add_argument('--refresh-pins', action='store_true', help='re-pin the provider registry digest only')
    args = parser.parse_args(argv)
    try:
        if args.refresh_pins:
            if args.census or args.coverage or args.check:
                parser.error('--refresh-pins takes no census, coverage or --check')
            text = render(refresh_pins(args.out))
        else:
            if not (args.census and args.coverage):
                parser.error('--census and --coverage are required')
            text = render(build(args.census, args.coverage))
    except (OSError, KeyError, ValueError) as exc:
        print('build_obligation_catalogue: %s' % exc, file=sys.stderr)
        return 1
    if args.population_out:
        document = json.loads(text)
        population = {'ids': sorted(row['id'] for row in document['rows']),
                      'count': document['counts']['rows'],
                      'by_kind': document['counts']['by_kind'],
                      'by_class': document['counts']['by_class'],
                      'inputs': document['inputs']}
        population_text = json.dumps(population, indent=1, sort_keys=True) + '\n'
        if args.check:
            if not args.population_out.is_file() or args.population_out.read_text() != population_text:
                print('build_obligation_catalogue: row population differs', file=sys.stderr)
                return 1
        else:
            args.population_out.write_text(population_text, encoding='utf-8')
    if args.check:
        current = args.out.read_text(encoding='utf-8') if args.out.exists() else ''
        if current != text:
            print('build_obligation_catalogue: %s differs from a rebuild' % args.out, file=sys.stderr)
            return 1
        print('build_obligation_catalogue: %s is current' % args.out)
        return 0
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(text, encoding='utf-8')
    catalogue = json.loads(text)
    print('build_obligation_catalogue: wrote %s (%d rows)' % (args.out, catalogue['counts']['rows']))
    return 0


if __name__ == '__main__':
    sys.exit(main())
