"""P02 obligation catalogue: the builder on fictional inputs and the installed catalogue against the coverage ids."""
from __future__ import annotations

import csv
import gzip
import importlib.util
import json
import os
from pathlib import Path
import re

import pytest

from ravel.controller.ledger import catalogue as catalogue_module
from ravel.workflow import decision_gate

ROOT = Path(__file__).resolve().parents[3]
BUILDER = ROOT / 'scripts' / 'maintenance' / 'build_obligation_catalogue.py'
COVERAGE_IDS = Path(__file__).with_name('test_p02_coverage_ids.json')
COLUMNS = ['row_id', 'source_kind', 'census_category', 'ledger_class', 'census_class', 'memo_tag', 'obligation',
           'source', 'mechanisms', 'mechanism_names', 'class_1_3_0', 'residual_advisory', 'graph_node', 'package',
           'test_idea', 'case_binding', 'canary']


def builder():
    spec = importlib.util.spec_from_file_location('build_obligation_catalogue_p02', BUILDER)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def census_row(rid, category, routes, *, source='docs/workflow/start.md', line=3, **extra):
    return {'id': rid, 'category': category, 'routes': routes, 'class': 'ADVISORY', 'source': source, 'line': line,
            'source_sha256': 'a' * 64, 'result_path': True, 'obligation': f'fictional obligation {rid}', **extra}


def coverage_row(rid, kind, ledger_class, mechanisms, cls, node, package='P99', category='fixture', source=None):
    return {'row_id': rid, 'source_kind': kind, 'census_category': category, 'ledger_class': ledger_class,
            'census_class': 'ADVISORY', 'memo_tag': '', 'obligation': f'fictional obligation {rid}',
            'source': source or 'docs/workflow/start.md:3', 'mechanisms': mechanisms, 'mechanism_names': '',
            'class_1_3_0': cls, 'residual_advisory': '', 'graph_node': node, 'package': package, 'test_idea': 'x',
            'case_binding': 'x', 'canary': 'C1'}


CENSUS = [
    census_row('R05', 'route', 'all'),
    census_row('A01', 'authority', 'all'),
    census_row('E06', 'budget', 'conditional: docs/workflow/steps/03-generate.md'),
    census_row('C02', 'budget', 'conditional: docs/workflow/checklists/check-ins.md'),
    census_row('D01', 'delivery', 'all'),
    census_row('B04', 'label', 'all'),
    census_row('TOOL-alpha', 'tools', 'scans and projections', declared_value={}),
    census_row('EXEC-alpha', 'spawn', 'scans and projections', declared_value='maker'),
    census_row('MODE-alpha', 'route', 'scans and projections'),
    census_row('STEP-03-generate', 'checkin', 'workflow-step:03-generate'),
    census_row('STAGE-ideas', 'research', 'open research'),
    census_row('CHECKIN-1', 'checkin', 'checkin:1'),
    census_row('CHECKIN-deviation', 'checkin', 'checkin:deviation'),
    census_row('GATE-launch', 'authority', 'gate:launch'),
    census_row('GATE-unblind', 'authority', 'gate:unblind'),
    census_row('ROUTE-scan', 'route', 'route:scan'),
    census_row('ROLE-maker-protocol-0', 'instructions', 'role:maker'),
    census_row('ROLE-maker-stop', 'stop', 'role:maker'),
    census_row('ROLE-maker-ownership', 'custody', 'role:maker'),
]
COVERAGE = [
    coverage_row('R05', 'census-decision', 'route', 'M01 M27', 'E', 'ledger.parent_join', 'P02'),
    coverage_row('A01', 'census-decision', 'authority/approval', 'M04 M01', 'E', 'authority.ci1'),
    coverage_row('E06', 'census-decision', 'budget/stop', 'M17', 'E', 'step.reserve'),
    coverage_row('C02', 'census-decision', 'budget/stop', 'M17 M04', 'E', 'step.reserve'),
    coverage_row('D01', 'census-decision', 'delivery/claims', 'M19 M20', 'L', 'controller.deliver'),
    coverage_row('B04', 'census-decision', 'delivery/claims', 'M20', 'L', 'controller.deliver'),
    coverage_row('TOOL-alpha', 'census-structural', 'execution/tool', 'M07 M09 M17 M11', 'E', 'step.operation[alpha]'),
    coverage_row('EXEC-alpha', 'census-structural', 'delegation/independence', 'M06', 'E', 'step.dispatch[alpha]'),
    coverage_row('MODE-alpha', 'census-structural', 'route', 'M07 M06 M10 M04', 'E', 'step.operation[alpha]'),
    coverage_row('STEP-03-generate', 'census-structural', 'authority/approval', 'M12 M13 M01', 'E',
                 'route.analysis.step[03-generate]'),
    coverage_row('STAGE-ideas', 'census-structural', 'route', 'M01 M15 M06', 'E', 'route.research.stage[ideas]'),
    coverage_row('CHECKIN-1', 'census-structural', 'authority/approval', 'M05 M04 M01', 'E', 'authority.ci1'),
    coverage_row('CHECKIN-deviation', 'census-structural', 'authority/approval', 'M05 M04 M01', 'E',
                 'controller.deviation'),
    coverage_row('GATE-launch', 'census-structural', 'authority/approval', 'M01 M26 M23', 'E', 'ledger.gate[launch]'),
    coverage_row('GATE-unblind', 'census-structural', 'authority/approval', 'M01 M26 M23', 'E',
                 'ledger.gate[unblind]'),
    coverage_row('ROUTE-scan', 'census-structural', 'route', 'M02 M01 M27', 'E', 'route.scan'),
    coverage_row('ROLE-maker-protocol-0', 'census-role-field', 'role/instruction', 'M12 M13', 'I',
                 'step.packet[maker]'),
    coverage_row('ROLE-maker-stop', 'census-role-field', 'budget/stop', 'M17 M06', 'E', 'step.dispatch[maker]'),
    coverage_row('ROLE-maker-ownership', 'census-role-field', 'execution/tool', 'M09', 'E', 'step.plan_bind[maker]'),
    coverage_row('SW01', 'xreview-switch', 'authority/approval', 'M04 M22', 'E', 'authority.service', 'P06',
                 'switch', 'src/ravel/workflow/example-gate.py:10-23; other-hook.sh:7'),
    coverage_row('CT01', 'spec-obligation', 'execution/tool', 'M02', 'E', 'controller.intake', 'P01', 'controller',
                 'CONTROLLER-SPEC.md'),
    coverage_row('JR01', 'spec-obligation', 'route', 'M02 M21', 'E', 'judgment.frame', 'P08', 'judgment',
                 'CONTROLLER-SPEC.md'),
    coverage_row('CF01', 'unread-card-field', 'role/instruction', 'M11', 'I', 'step.escalation', 'P04',
                 'instructions', 'src/ravel/data/roles/schema/card.json'),
    coverage_row('XF01', 'cross-family-removal', 'delegation/independence', 'M20', 'L', 'step.dispatch', 'P13',
                 'independence', 'src/ravel/data/roles/registry.json:4521-4523'),
]


def write_inputs(directory: Path, census=CENSUS, coverage=COVERAGE):
    census_path = directory / 'census.jsonl.gz'
    with gzip.open(census_path, 'wt', encoding='utf-8') as handle:
        for row in census:
            handle.write(json.dumps(row) + '\n')
    coverage_path = directory / 'coverage.csv'
    with open(coverage_path, 'w', newline='', encoding='utf-8') as handle:
        writer = csv.DictWriter(handle, fieldnames=COLUMNS)
        writer.writeheader()
        writer.writerows(coverage)
    providers = directory / 'providers.json'
    providers.write_text(json.dumps({'providers': [{'id': 'one'}, {'id': 'two'}], 'required_providers': {}}))
    return census_path, coverage_path, providers


# ---- builder ------------------------------------------------------------------------------------------

def test_p02_builder_compiles_every_coverage_row_with_its_applicability(tmp_path):
    module = builder()
    census, coverage, providers = write_inputs(tmp_path)
    catalogue = module.build(census, coverage, providers)
    rows = {r['id']: r for r in catalogue['rows']}
    assert sorted(rows) == sorted(r['row_id'] for r in COVERAGE)
    app = {rid: r['applicability'] for rid, r in rows.items()}
    assert app['R05'] == {'stage': 'intake', 'scope': 'deliverable'}
    assert app['A01'] == {'stage': 'plan', 'scope': 'run'}
    assert app['E06'] == {'stage': 'seat', 'scope': 'seat', 'select': {'document': 'docs/workflow/steps/03-generate.md'}}
    assert app['C02'] == {'stage': 'seat', 'scope': 'seat'}  # check-in templates apply to every governed plan
    assert app['D01'] == {'stage': 'deliver', 'scope': 'artifact'}
    assert app['B04'] == {'stage': 'deliver', 'scope': 'run'}
    assert app['TOOL-alpha'] == app['EXEC-alpha'] == {'stage': 'plan', 'scope': 'step', 'select': {'operation': 'alpha'}}
    assert app['MODE-alpha']['select'] == {'mode': 'alpha'}
    assert app['STEP-03-generate']['select'] == {'workflow_step': '03-generate'}
    assert app['STAGE-ideas']['select'] == {'research_stage': 'ideas'}
    assert app['CHECKIN-1'] == {'stage': 'plan', 'scope': 'run', 'select': {'checkin': '1'}}
    assert app['CHECKIN-deviation'] == {'stage': 'event', 'scope': 'event', 'select': {'checkin': 'deviation'}}
    assert app['GATE-launch'] == {'stage': 'plan', 'scope': 'step', 'select': {'gate': 'launch', 'launches': True}}
    assert app['GATE-unblind'] == {'stage': 'event', 'scope': 'event', 'select': {'gate': 'unblind'}}
    assert app['ROUTE-scan'] == {'stage': 'intake', 'scope': 'run', 'select': {'task_mode': 'scan'}}
    assert app['ROLE-maker-protocol-0'] == {'stage': 'seat', 'scope': 'seat', 'select': {'role': 'maker'}}
    assert app['ROLE-maker-ownership'] == {'stage': 'plan', 'scope': 'step', 'select': {'role': 'maker'}}
    assert app['SW01'] == app['CT01'] == {'stage': 'intake', 'scope': 'run'}
    assert app['JR01'] == {'stage': 'plan', 'scope': 'run', 'select': {'route': ['judgment']}}
    # A worker's escalation duties exist only when it escalates: the escalation occurrence instantiates them.
    assert app['CF01'] == {'stage': 'event', 'scope': 'event', 'select': {'checkin': 'escalation'}}
    assert rows['SW01']['source'] == 'src/ravel/workflow/example-gate.py:10'   # a hyphenated name stays whole
    assert rows['CT01']['source'] == 'CONTROLLER-SPEC.md'
    assert not any('source_ref' in r for r in rows.values())   # free source text never enters package data
    assert rows['TOOL-alpha']['family'] == 'scans and projections'
    assert catalogue['source_digests'] == {'docs/workflow/start.md': 'a' * 64}
    assert catalogue['gate_registry']['providers'] == ['one', 'two']
    assert catalogue['counts']['rows'] == len(COVERAGE)
    assert catalogue['counts']['census_rows'] == len(CENSUS)


def test_p02_builder_waivability_follows_the_waiver_table(tmp_path):
    module = builder()
    catalogue = module.build(*write_inputs(tmp_path))
    rows = {r['id']: r for r in catalogue['rows']}
    waivable = {rid: r.get('waiver') for rid, r in rows.items() if r['waivability'] == 'authority'}
    assert waivable == {'R05': 'scope', 'A01': 'authority', 'C02': 'budget', 'CHECKIN-1': 'authority',
                        'CHECKIN-deviation': 'authority', 'ROUTE-scan': 'scope', 'ROLE-maker-stop': 'budget'}
    assert rows['ROLE-maker-protocol-0']['waivability'] == 'never'  # instruction delivery and acknowledgement
    assert rows['CF01']['waivability'] == 'never'
    assert rows['STEP-03-generate']['waivability'] == 'never'      # M12/M13 instruction receipt rows
    for rid in ('D01', 'B04', 'TOOL-alpha', 'EXEC-alpha', 'GATE-launch', 'SW01', 'CT01', 'XF01', 'ROLE-maker-ownership',
                'E06', 'JR01'):
        assert rows[rid]['waivability'] == 'diagnostic', rid


def test_p02_builder_check_mode_detects_drift_and_refresh_pins_repins(tmp_path, capsys):
    module = builder()
    census, coverage, providers = write_inputs(tmp_path)
    out = tmp_path / 'catalogue.json'
    original = module.PROVIDERS
    module.PROVIDERS = providers
    try:
        assert module.main(['--census', str(census), '--coverage', str(coverage), '--out', str(out)]) == 0
        first = out.read_bytes()
        assert module.main(['--census', str(census), '--coverage', str(coverage), '--out', str(out), '--check']) == 0
        assert module.main(['--census', str(census), '--coverage', str(coverage), '--out', str(out)]) == 0
        assert out.read_bytes() == first  # deterministic
        out.write_text(first.decode().replace('fictional obligation A01', 'edited'), encoding='utf-8')
        assert module.main(['--census', str(census), '--coverage', str(coverage), '--out', str(out), '--check']) == 1
        assert 'differs from a rebuild' in capsys.readouterr().err
        out.write_bytes(first)
        providers.write_text(json.dumps({'providers': [{'id': 'one'}], 'required_providers': {}}))
        assert module.main(['--refresh-pins', '--out', str(out)]) == 0
        repinned = json.loads(out.read_text())
        assert repinned['gate_registry']['providers'] == ['one']
        assert repinned['rows'] == json.loads(first)['rows']
    finally:
        module.PROVIDERS = original


def test_p02_builder_stops_when_census_and_coverage_id_sets_differ(tmp_path, capsys):
    module = builder()
    census, coverage, providers = write_inputs(tmp_path, census=CENSUS + [census_row('R99', 'route', 'all')])
    assert module.main(['--census', str(census), '--coverage', str(coverage), '--out', str(tmp_path / 'c.json')]) == 1
    assert 'census and coverage id sets differ' in capsys.readouterr().err
    assert not (tmp_path / 'c.json').exists()
    census, coverage, providers = write_inputs(tmp_path, census=CENSUS[1:])
    with pytest.raises(module.CatalogueError, match='id sets differ'):
        module.build(census, coverage, providers)


@pytest.mark.parametrize('field,value,message', [
    ('mechanisms', 'M01 M99', 'invalid mechanisms'),
    ('mechanisms', '', 'invalid mechanisms'),
    ('class_1_3_0', 'X', 'invalid class'),
    ('ledger_class', 'unknown', 'invalid ledger class'),
    ('graph_node', '', 'no discharging node'),
    ('graph_node', 'nowhere.node', 'no applicability rule'),
])
def test_p02_builder_refuses_rows_without_mechanism_class_or_node(tmp_path, field, value, message):
    module = builder()
    coverage = [dict(r) for r in COVERAGE]
    coverage[1][field] = value
    with pytest.raises(module.CatalogueError, match=message):
        module.build(*write_inputs(tmp_path, coverage=coverage))


def test_p02_builder_binds_the_primary_node_of_a_two_node_row_and_places_engagement_rows(tmp_path):
    module = builder()
    coverage = [dict(r) for r in COVERAGE] + [
        coverage_row('EGX1', 'spec-obligation', 'delegation/independence', 'M01 M06', 'E',
                     'engagement.apply + ledger gate checkin1->execute', 'P18 (P02 gate)'),
        coverage_row('EGX2', 'spec-obligation', 'review/credit', 'M29 M20', 'E', 'engagement.envelope', 'P18'),
        coverage_row('EGX3', 'spec-obligation', 'budget/stop', 'M09 M17', 'E', 'step.observe', 'P04'),
    ]
    rows = {r['id']: r for r in module.build(*write_inputs(tmp_path, coverage=coverage))['rows']}
    assert rows['EGX1']['node'] == 'engagement.apply' and rows['EGX1']['package'] == 'P18 (P02 gate)'
    assert rows['EGX1']['applicability'] == {'stage': 'plan', 'scope': 'run'}
    assert rows['EGX2']['applicability'] == {'stage': 'deliver', 'scope': 'run'}
    assert rows['EGX3']['applicability'] == {'stage': 'seat', 'scope': 'seat'}


# ---- the installed catalogue ----------------------------------------------------------------------------

def installed():
    return catalogue_module.load()


def test_p02_catalogue_ids_equal_the_coverage_id_set():
    expected = json.loads(COVERAGE_IDS.read_text())
    catalogue = installed()
    assert len(expected['ids']) == expected['count']
    assert expected['count'] == sum(expected['by_kind'].values())
    assert sorted(catalogue.rows) == expected['ids']
    by_kind = {}
    for row in catalogue.rows.values():
        by_kind[row['kind']] = by_kind.get(row['kind'], 0) + 1
    assert by_kind == expected['by_kind']


def test_p02_catalogue_rows_have_mechanisms_class_node_waivability_and_applicability():
    catalogue = installed()
    for rid, row in catalogue.rows.items():
        assert row['mechanisms'] and all(re.fullmatch(r'M(0[1-9]|1[0-9]|2[0-9])', m) for m in row['mechanisms']), rid
        assert row['class'] in ('E', 'L', 'R', 'I'), rid
        assert row['node'], rid
        assert row['package'].startswith('P'), rid
        assert row['waivability'] in ('authority', 'diagnostic', 'never'), rid
        assert row['applicability']['stage'] in catalogue_module.STAGES, rid
        assert row['source'], rid
    counts = {c: sum(r['class'] == c for r in catalogue.rows.values()) for c in ('E', 'R', 'L', 'I')}
    expected = json.loads(COVERAGE_IDS.read_text())
    assert counts == expected['by_class']
    assert sum(counts.values()) == expected['count']


def test_p02_catalogue_structural_rows_select_their_own_dimension():
    catalogue = installed()
    expected = {'TOOL': 'operation', 'EXEC': 'operation', 'MODE': 'mode', 'STEP': 'workflow_step',
                'STAGE': 'research_stage', 'ROUTE': 'task_mode', 'CHECKIN': 'checkin', 'GATE': 'gate'}
    for rid, row in catalogue.rows.items():
        prefix = rid.split('-', 1)[0]
        if prefix in expected:
            assert row['applicability']['select'][expected[prefix]] == rid.split('-', 1)[1], rid
        if prefix == 'ROLE':
            role = row['applicability']['select']['role']
            assert rid.startswith(f'ROLE-{role}-'), rid
            if row['node'].split('[', 1)[0] == 'step.escalation':
                # Instantiated by an escalation occurrence of a seat of this role, never at every seat.
                assert row['applicability'] == {'stage': 'event', 'scope': 'event',
                                                 'select': {'checkin': 'escalation', 'role': role}}, rid
            else:
                assert row['applicability']['stage'] in ('seat', 'plan'), rid
    gates = {rid.split('-', 1)[1] for rid in catalogue.rows if rid.startswith('GATE-')}
    assert gates == set(decision_gate.GATES)


def test_p02_catalogue_waivers_are_the_four_waivable_kinds_only():
    catalogue = installed()
    integrity = {'M06', 'M07', 'M08', 'M09', 'M14', 'M15', 'M16', 'M19', 'M22', 'M23', 'M24', 'M25', 'M26'}
    for rid, row in catalogue.rows.items():
        if row['waivability'] != 'authority':
            assert 'waiver' not in row, rid
            continue
        assert row['waiver'] in ('authority', 'scope', 'statistic', 'budget'), rid
        assert row['class'] != 'I', rid
        assert row['ledger_class'] not in ('delegation/independence', 'review/credit'), rid
        assert not {'M12', 'M13'} & set(row['mechanisms']), rid
        # Budget rows ride on the dispatch path; the requested statistic and fidelity are delivered by the sink.
        if row['waiver'] != 'budget' and rid not in ('D02', 'C26'):
            assert not integrity & set(row['mechanisms']), rid
    instruction = [r for r in catalogue.rows.values() if r['class'] == 'I']
    assert instruction and all(r['waivability'] == 'never' for r in instruction)
    for node in ('controller.deliver', 'confine.launch', 'review.credit', 'step.adopt'):
        rows = [r for r in catalogue.rows.values() if r['node'] == node]
        assert rows and all(r['waivability'] != 'authority' or r['id'] == 'D02' for r in rows), node


def test_p02_catalogue_pins_the_installed_provider_registry():
    catalogue = installed()
    registry = json.loads(decision_gate._registry_bytes())
    assert catalogue.gate_registry['sha256'] == decision_gate.registry_sha256(), (
        'providers.json changed without re-pinning the obligation catalogue: run '
        'scripts/maintenance/build_obligation_catalogue.py --refresh-pins')
    assert list(catalogue.gate_registry['providers']) == sorted(p['id'] for p in registry['providers'])


def test_p02_catalogue_is_read_from_the_installed_package_only(tmp_path, monkeypatch):
    digest = installed().sha256
    planted = {'schema': 'obligation-catalogue.v1', 'rows': [], 'gate_registry': {'sha256': '0' * 64}}
    for relative in ('catalogue.json', 'data/obligations/catalogue.json', 'src/ravel/data/obligations/catalogue.json',
                     '.ravel/obligations/catalogue.json'):
        target = tmp_path / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(planted))
    monkeypatch.chdir(tmp_path)
    for name in ('RAVEL_ROOT', 'RAVEL_STATE_DIR', 'RAVEL_WORK_ROOT', 'RAVEL_DATA_DIR'):
        monkeypatch.setenv(name, str(tmp_path))
    assert installed().sha256 == digest
    assert Path(str(catalogue_module._resource())).resolve() == (
        Path(catalogue_module.__file__).resolve().parents[2] / 'data' / 'obligations' / 'catalogue.json')


@pytest.mark.parametrize('mutation,message', [
    (lambda rows: rows.append(dict(rows[0])), 'repeats'),
    (lambda rows: rows[0]['applicability'].update(stage='seat', scope='run'), 'not allowed'),
    (lambda rows: rows[0]['applicability'].update(select={'colour': 'red'}), 'unknown selector'),
    (lambda rows: rows[0].update(waivability='authority', waiver=None), 'names no waiver kind'),
    (lambda rows: rows[0].update(mechanisms=['M30']), 'mechanisms'),
    (lambda rows: rows[0].update(mechanisms=['M00']), 'mechanisms'),
    (lambda rows: rows[0].update(mechanisms=['M01', 'M99']), 'mechanisms'),
    (lambda rows: rows[0].update(**{'class': 'Z'}), 'class'),
])
def test_p02_catalogue_parse_refuses_malformed_rows(mutation, message):
    rows = [{'id': 'X1', 'kind': 'census-decision', 'ledger_class': 'route', 'category': 'route', 'class': 'E',
             'mechanisms': ['M01'], 'node': 'controller.intake', 'package': 'P99', 'waivability': 'diagnostic',
             'applicability': {'stage': 'intake', 'scope': 'run'}, 'source': 'fixture:1', 'text': 'x'}]
    mutation(rows)
    data = json.dumps({'schema': 'obligation-catalogue.v1', 'rows': rows,
                       'gate_registry': {'sha256': 'b' * 64}}).encode()
    with pytest.raises(catalogue_module.CatalogueError, match=message):
        catalogue_module.parse(data)


def test_p02_catalogue_parse_accepts_the_engagement_mechanism_and_the_range_ends():
    for mechanisms in (['M01'], ['M28'], ['M29'], ['M29', 'M02']):
        rows = [{'id': 'X1', 'kind': 'census-decision', 'ledger_class': 'route', 'category': 'route', 'class': 'E',
                 'mechanisms': mechanisms, 'node': 'controller.intake', 'package': 'P99', 'waivability': 'diagnostic',
                 'applicability': {'stage': 'intake', 'scope': 'run'}, 'source': 'fixture:1', 'text': 'x'}]
        data = json.dumps({'schema': 'obligation-catalogue.v1', 'rows': rows,
                           'gate_registry': {'sha256': 'b' * 64}}).encode()
        assert catalogue_module.parse(data).rows['X1']['mechanisms'] == tuple(mechanisms)


def test_p02_builder_accepts_m29_and_refuses_m30(tmp_path):
    module = builder()
    assert module.MECHANISMS[0] == 'M01' and module.MECHANISMS[-1] == 'M29' and len(module.MECHANISMS) == 29
    for mechanisms, accepted in (('M29', True), ('M01 M29', True), ('M30', False)):
        coverage = [dict(r) for r in COVERAGE]
        coverage[1]['mechanisms'] = mechanisms
        if accepted:
            assert module.build(*write_inputs(tmp_path, coverage=coverage))['rows']
        else:
            with pytest.raises(module.CatalogueError, match='invalid mechanisms'):
                module.build(*write_inputs(tmp_path, coverage=coverage))


def test_p02_catalogue_has_no_named_study_or_person_shapes():
    text = (Path(catalogue_module.__file__).resolve().parents[2] / 'data' / 'obligations' / 'catalogue.json').read_text()
    assert not re.search(r'arXiv:\d{4}\.\d{4,5}|inspirehep\.net/\w+/\d{5,}|hepdata\.net/record/\w*\d{5,}', text)
    assert os.sep not in json.loads(text)['inputs']['census']['name']


def test_population_manifest_is_derived_from_supplied_source_rows(tmp_path):
    mod = builder()
    census, coverage, providers = write_inputs(tmp_path)
    mod.PROVIDERS = providers
    output, population = tmp_path / 'catalogue.json', tmp_path / 'population.json'
    args = ['--census', str(census), '--coverage', str(coverage), '--out', str(output),
            '--population-out', str(population)]
    assert mod.main(args) == 0
    document, manifest = json.loads(output.read_text()), json.loads(population.read_text())
    assert manifest['ids'] == sorted(row['row_id'] for row in COVERAGE)
    assert manifest['count'] == len(COVERAGE)
    assert manifest['by_class'] == document['counts']['by_class']
    assert manifest['inputs'] == document['inputs']
    assert mod.main([*args, '--check']) == 0
    manifest['ids'].pop()
    population.write_text(json.dumps(manifest))
    assert mod.main([*args, '--check']) == 1
