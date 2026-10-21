"""Synthetic role/host mutation controls, with no model or native calls."""
import copy
import importlib
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
HOSTS = ('claude', 'codex', 'gemini', 'antigravity', 'opencode', 'governed-node')


def registry():
    assert importlib.util.find_spec('ravel.workflow.role_registry'), 'role registry missing'
    return importlib.import_module('ravel.workflow.role_registry')


@pytest.mark.parametrize('field', ['sees', 'tools', 'must_check', 'knowledge', 'model', 'stop', 'escalation', 'operations'])
def test_card_missing_contract_field_refused(field):
    rr = registry()
    card = rr.load('physics-critic')
    del card[field]
    assert rr.validate_card(card)


@pytest.mark.parametrize('identity', ['hb:unknown', 'trap:T999', 'check:unknown'])
def test_unknown_knowledge_refused(identity):
    rr = registry()
    card = rr.load('physics-critic')
    card['knowledge']['must_read'].append(identity)
    assert any('unresolved' in e for e in rr.validate_card(card))


def test_reviewer_lessons_refused():
    rr = registry()
    card = rr.load('physics-critic')
    card['knowledge']['forbidden'].remove('lessons')
    assert rr.validate_card(card)


def test_scout_cheap_tier_refused():
    rr = registry()
    card = rr.load('literature-scout')
    card['model']['tier'] = 'cheap'
    assert rr.validate_card(card)


def test_omitted_role_refused(tmp_path):
    rr = registry()
    data = rr.registry_document()
    del data['roles']['physics-critic']
    assert any('physics-critic' in e for e in rr.validate_registry(data))


@pytest.mark.parametrize('host', HOSTS)
def test_rendered_hand_edit_or_omission_refused(host, tmp_path):
    rr = registry()
    files = rr.render(host)
    for rel, content in files.items():
        path = tmp_path / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)
    assert rr.check_rendered(tmp_path, surfaces=[host]) == []
    rel = next(iter(files))
    path = tmp_path / rel
    path.write_text(path.read_text() + '\nstale\n')
    assert rr.check_rendered(tmp_path, surfaces=[host])
    path.unlink()
    assert rr.check_rendered(tmp_path, surfaces=[host])


def test_registry_edit_changes_request_digest_and_every_host_file():
    rr = registry()
    data = rr.registry_document()
    card = rr.load('physics-critic')
    before = rr.card_sha256('physics-critic')
    data['roles']['physics-critic']['card']['purpose'] += ' Changed stance.'
    assert before != rr.card_sha256('physics-critic', document=data)
    for host in HOSTS:
        old, new = rr.render(host), rr.render(host, document=data)
        assert old.keys() == new.keys()
        # The site-tool declaration is host-only and independent of the role registry.
        site = {p for p in old if p.startswith('.ravel/site-tools/')}
        assert len(site) == 1 and all(old[p] == new[p] for p in site)
        # Hook adapters depend on the shared hook table, not individual role cards.
        from ravel.workflow.host_hooks import render as render_hooks
        hooks = set(render_hooks(host))
        assert all(old[p] == new[p] for p in hooks)
        assert all(old[p] != new[p] for p in old if p not in site | hooks)
    assert rr.request_digest({'role': 'physics-critic'}) != rr.request_digest({'role': 'physics-critic'}, document=data)


@pytest.mark.parametrize('evidence_class', [None, 'invented'])
def test_blocking_finding_without_valid_class_refused(evidence_class):
    rr = registry()
    item = finding()
    if evidence_class is None:
        del item['evidence_class']
    else:
        item['evidence_class'] = evidence_class
    assert rr.validate_output('findings.v1', {'schema_version': 1, 'kind': 'findings', 'items': [item]})


def finding():
    return {'id': 'F1', 'severity': 'A', 'location': {'path': 'outputs/value.json', 'pointer': '/value', 'line': None},
            'code': 'missing_evidence', 'statement': 'A required observation is absent.',
            'evidence': ['receipt:observation'], 'closes': [], 'evidence_class': 'code_check'}


def test_opinion_does_not_block_but_failed_requested_test_does():
    rr = registry()
    item = finding()
    item['evidence_class'] = 'opinion'
    assert rr.finding_effect(item) == 'advisory'
    item['request'] = {'id': 'Q1', 'operation': 'check run', 'inputs': ['receipt:observation'],
                       'expected': 'Required observation exists', 'result': 'pending'}
    assert rr.finding_effect(item) == 'wait_for_test'
    item['request']['result'] = 'fail'
    assert rr.finding_effect(item) == 'advisory'
    assert rr.finding_effect(item, resolve=lambda _: 'code_check') == 'blocking'


def test_unqualified_delegated_critic_is_labelled_without_demotion():
    rr = registry()
    result = rr.qualification_labels([{'role': 'physics-critic', 'model_id': 'synthetic-model',
        'transport': 'synthetic-cli', 'effort': 'high', 'mode': 'blocking',
        'qualification': {'status': 'unqualified'}}], delegated=True)
    assert result[0]['mode'] == 'blocking'
    assert result[0]['qualification']['status'] == 'unqualified'
    assert 'unqualified' in result[0]['label']


def test_delegated_checkin_shows_exact_cell():
    rr = registry()
    from ravel.workflow.science import make_checkin
    spec = {'mode': 'formula-grid', 'source': 'Synthetic scalar question', 'task': {},
            'max_seconds': 10, 'assumptions': [], 'autonomy': {'mode': 'delegated'}}
    assignment = {'role': 'physics-critic', 'model_id': 'synthetic-model', 'transport': 'synthetic-cli',
                  'effort': 'high', 'mode': 'blocking', 'qualification': {'status': 'unqualified'}}
    value = make_checkin(spec, '0' * 64, {'role_assignments': [assignment]})
    row = value['sections']['i-b']['role_qualifications'][0]
    assert row['mode'] == 'blocking' and row['qualification']['status'] == 'unqualified'
    assert 'CHECK-IN 1' in row['label']
    assert 'role_qualifications' not in make_checkin(spec, '0' * 64)['sections']['i-b']


def test_qualification_record_requires_complete_cell_and_battery():
    rr = registry()
    assert rr.validate_qualification({'schema_version': 1, 'kind': 'role-qualification', 'status': 'qualified'})


def test_knowledge_gate_called_exactly_once(monkeypatch):
    from ravel.validation import check_agent_surface as gate
    assert hasattr(gate, 'check_knowledge'), 'knowledge check seam missing'
    calls = []
    monkeypatch.setattr('ravel.validation.check_knowledge.validate', lambda *a, **k: calls.append((a, k)) or [])
    assert gate.check_knowledge(ROOT) == []
    assert len(calls) == 1


def test_installed_panel_resolves_profiles(tmp_path):
    rr = registry()
    from ravel.workflow import agent_surface
    agent_surface.install(tmp_path, skills_from=ROOT, include_software=False)
    for host in HOSTS:
        profiles = rr.resolve_panel(tmp_path, host)
        assert set(profiles) == {'physics-critic', 'skeptical-verifier', 'physics-decider', 'physics-improver'}
        assert all(Path(p).is_file() for p in profiles.values())


def test_installed_panel_rejects_stale_profile(tmp_path):
    rr = registry()
    from ravel.workflow import agent_surface
    agent_surface.install(tmp_path, skills_from=ROOT, include_software=False)
    profile = Path(rr.resolve_panel(tmp_path, 'codex')['physics-critic'])
    profile.write_text('stale')
    with pytest.raises(ValueError, match='stale'):
        rr.resolve_panel(tmp_path, 'codex')


def test_transport_qualification_is_not_a_role_battery():
    rr = registry()
    row = {'role': 'physics-critic', 'model_id': 'synthetic-model', 'transport': 'synthetic-cli',
           'effort': 'high', 'mode': 'blocking', 'qualification': {'status': 'qualified'}}
    assert rr.qualification_labels([row], delegated=True)[0]['qualification']['status'] == 'unqualified'


def test_qualified_cell_cannot_qualify_another_model_or_effort():
    rr = registry()
    record = {'schema_version': 1, 'kind': 'role-qualification', 'role_family': 'governance',
        'role': 'physics-critic', 'model_id': 'synthetic-model', 'transport': 'synthetic-cli',
        'effort': 'high', 'status': 'qualified', 'cli_version': 'synthetic-v1',
        'battery': [{'id': 'clean-control', 'result': 'pass', 'receipt': 'receipt:control'}],
        'cost_usd': None, 'recorded_utc': '2026-01-01T00:00:00Z'}
    assignment = {k: record[k] for k in ('role', 'model_id', 'transport', 'effort')}
    assignment['mode'] = 'blocking'
    assert rr.qualification_labels([assignment], records=[record])[0]['qualification']['status'] == 'qualified'
    for key, value in [('model_id', 'other-model'), ('effort', 'medium'), ('transport', 'other-cli')]:
        changed = {**assignment, key: value}
        assert rr.qualification_labels([changed], records=[record])[0]['qualification']['status'] == 'unqualified'


def test_generated_codex_profiles_are_valid_toml():
    import tomllib
    rr = registry()
    files = rr.render('codex')
    for path, content in files.items():
        if path.endswith('.toml'):
            assert tomllib.loads(content)


def test_all_roles_and_cards_validate():
    rr = registry()
    assert rr.validate_registry() == []
    cards = rr.all_cards()
    assert len(cards) == len({c['id'] for c in cards})
    assert all(not rr.validate_card(c) for c in cards)


CHEAP_OK = ('consult-latex', 'sf-convention-translator', 'sf-id-encoder', 'sf-modifier-namer', 'sf-scan-sanitizer')


def test_only_the_mechanical_cards_are_cheap_ok_and_they_validate():
    rr = registry()
    cards = {c['id']: c for c in rr.all_cards()}
    marked = sorted(i for i, c in cards.items() if 'cheap_ok' in c['model'])
    assert marked == list(CHEAP_OK)
    for identity in CHEAP_OK:
        card = cards[identity]
        assert card['model']['cheap_ok'] is True and card['model']['tier'] != 'cheap'
        assert rr.validate_card(card) == []


def test_cheap_ok_must_be_a_boolean():
    rr = registry()
    card = rr.load(CHEAP_OK[0])
    card['model']['cheap_ok'] = 'yes'
    assert rr.validate_card(card)

def test_producer_self_checks_are_reviewer_union():
    rr = registry()
    card = rr.load('generator')
    union = {identity for reviewer in card['reviewed_by'] for identity in rr.load(reviewer)['must_check']}
    expected = {i for i in union if not i.startswith('trap:')}
    if any(i.startswith('trap:') for i in union):
        expected.add('check:validation.validate_run_state.check_trap_sweep')
    assert rr.self_checks('generator') == sorted(expected)
    assert not any(i.startswith('trap:') for i in rr.self_checks('generator'))


@pytest.mark.parametrize('host', HOSTS)
def test_every_voting_role_has_profile(host):
    rr = registry()
    profiles = rr.profile_paths(host)
    assert {c['id'] for c in rr.all_cards() if c['independence']['kind'] == 'voting'} <= set(profiles)


def test_owned_card_override_is_single_and_changes_digest(tmp_path):
    rr = registry()
    data = rr.registry_document()
    card = rr.load('plan-critic')
    card['purpose'] += ' Author revision.'
    target = tmp_path / 'cards/plan-critic.json'
    target.parent.mkdir()
    target.write_text(json.dumps(card))
    assert rr.card_sha256('plan-critic', roles_root=tmp_path) != rr.card_sha256('plan-critic')
    assert rr.load('plan-critic', roles_root=tmp_path)['purpose'] == card['purpose']


@pytest.mark.parametrize('host', HOSTS)
def test_rendered_surfaces_carry_no_internal_package_labels(host):
    import re
    rr = registry()
    for rel, content in rr.render(host).items():
        if rel != 'AGENTS.md':  # canonical instructions have their own public transform
            assert not re.search(r'\bM-[0-9]+', content), rel


def test_source_checkout_surfaces_are_registered_and_rendered():
    """Omission and drift fail plain pytest CI, not only the pre-commit surface gate."""
    from ravel import evidence_layout
    if evidence_layout.is_public_tree(ROOT):
        pytest.skip('public trees ship a curated subset of host surfaces')
    rr = registry()
    assert rr.validate_registry(root=ROOT) == []
    assert rr.check_rendered(ROOT) == []


@pytest.mark.parametrize('host', HOSTS)
def test_n1_native_binding_or_contract_free_redirect(host):
    import tomllib
    import yaml
    rr = registry()
    files = rr.render(host)
    for card in rr.all_cards():
        text = files[rr.profile_paths(host)[card['id']]]
        if host == 'governed-node':
            assert json.loads(text)['card'] == card
            continue
        if host == 'codex':
            fields = tomllib.loads(text)
            body = fields['developer_instructions']
        else:
            _, front, body = text.split('---', 2)
            fields = yaml.safe_load(front)
        if host == 'claude':
            assert 'tools' in fields
        binding = rr.native_binding(card, host)
        if binding is None:
            import shlex
            from ravel.workflow.transports.host_subagent import dispatch_parser
            command = body.split('Run `', 1)[1].split('`', 1)[0]
            argv = shlex.split(command)
            assert argv[:3] == ['python', '-m', 'ravel.workflow.transports.host_subagent']
            parsed = dispatch_parser().parse_args(argv[3:])
            assert parsed.role == card['id'] and parsed.node == 'NODE'
            assert str(parsed.rundir) == 'RUN'
            assert str(parsed.spec) == 'SPEC.json' and str(parsed.subject) == 'SUBJECT.json'
            assert 'Contract:' not in text and '"requires"' not in text
        else:
            assert all(fields[k] == v for k, v in binding.items())


@pytest.mark.parametrize('host', ['claude', 'codex', 'gemini', 'opencode'])
def test_n2_transport_voters_redirect(host):
    rr = registry()
    for card in rr.all_cards():
        if card['independence']['kind'] == 'voting':
            assert card['requires']['attestation_min'] == 'transport'
            assert rr.native_binding(card, host) is None


@pytest.mark.parametrize('relative', ['.claude/agents/ravel-extra.md', '.codex/agents/x.toml'])
def test_n3_orphan_detected(tmp_path, relative):
    rr = registry()
    for host in HOSTS:
        for rel, content in rr.render(host).items():
            path = tmp_path / rel
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content)
    path = tmp_path / relative
    path.write_text('unregistered profile')
    assert 'generated surface orphan: ' + relative in rr.check_rendered(tmp_path)


def test_claude_empty_tools_list_is_not_a_confirmed_deny():
    # Claude Code lists a profile with `tools: []` as having all tools, so an empty
    # list cannot bind `requires.tools: none`; such a card must render a redirect.
    rr = registry()
    card = rr.load('generator')
    card['requires'].update({'attestation_min': 'self', 'tools': 'none'})
    caps = rr.host_capabilities()
    assert caps['surfaces']['claude']['mappings']['requires.tools']['status'] != 'confirmed'
    assert rr.native_binding(card, 'claude', capabilities=caps) is None


def test_n4_no_legacy_registered_twin():
    rr = registry()
    data = rr.registry_document()
    names = set(data['roles']) | set(data['aliases'])
    assert not [p for p in (ROOT / '.claude/agents').glob('*') if p.stem in names]


def test_n5_no_pseudo_hook_tables():
    rr = registry()
    forbidden = ['.claude/settings.ravel-gates.json', '.ravel/gate-surface.json']
    for host in HOSTS:
        assert not set(forbidden) & rr.render(host).keys()
    assert not [p for p in forbidden if (ROOT / p).exists()]


def test_n6_v2_requirements():
    rr = registry()
    card = rr.load('generator')
    card['requires']['parallel_safe'] = True
    assert rr.validate_card(card)
    del card['requires']['parallel_safe']
    card['stop']['evidence_budget'] = 1
    card['requires']['tools'] = 'none'
    assert any('tool-capable' in e for e in rr.validate_card(card))


def test_n7_p3_finding_class_is_resolved():
    rr = registry()
    item = finding()
    item['evidence_class'] = 'new_receipt'
    item['evidence'] = ['my opinion']
    item['request'] = None
    assert rr.finding_effect(item) == 'advisory'
    assert rr.finding_effect(item, resolve=lambda _: 'code_check') == 'blocking'


def test_n10_and_m15_role_names():
    rr = registry()
    names = ['spec-author', 'card-author', 'model-author', 'statistical-model-author', 'refutation-verifier']
    assert set(rr.resolve_names(names)) == set(names)
    with pytest.raises(ValueError, match='unregistered'):
        rr.resolve_names(['unregistered-role'])


def test_request_tools_come_from_card():
    rr = registry()
    for card in rr.all_cards():
        assert rr.request_requires(card['id']) == {'tools': card['requires']['tools']}


def test_v2_output_handoff_and_budget_default():
    rr = registry()
    card = rr.load('generator')
    del card['stop']['evidence_budget']
    assert not rr.validate_card(card)
    value = {'schema_version': 1, 'kind': 'findings', 'items': []}
    assert rr.validate_output('findings.v1', value)
    assert not rr.validate_output('findings.v1', {**value, 'handoff': None})
    assert not rr.validate_output('findings.v1', {**value, 'handoff': {'role': 'model-author', 'reason': 'Requires model input'}})
    assert rr.validate_output('findings.v1', {**value, 'handoff': {'role': 'model-author'}})


def test_unverified_field_forces_redirect_even_with_self_attestation():
    rr = registry()
    card = rr.load('generator')
    card['requires']['attestation_min'] = 'self'
    for host in ('claude', 'codex', 'gemini', 'opencode'):
        assert rr.native_binding(card, host) is None


def test_surface_extension_project_and_metadata(monkeypatch, tmp_path):
    import sys
    from types import ModuleType
    rr = registry()
    gov = ModuleType('ravel.workflow.host_governance')
    gov.SURFACE_EXTENSIONS = ()
    monkeypatch.setitem(sys.modules, gov.__name__, gov)
    assert rr.register_surface_extension()
    assert rr.register_surface_extension()
    assert gov.SURFACE_EXTENSIONS == (rr.owned_paths,)
    paths = gov.SURFACE_EXTENSIONS[0](tmp_path)
    assert paths and all(Path(p).is_relative_to(tmp_path) for p in paths.values())
    assert gov.SURFACE_EXTENSIONS[0].metadata(tmp_path) == {'role_registry_sha256': rr.registry_sha256()}


def test_owned_paths_include_orphan_card_files(tmp_path):
    rr = registry()
    orphan = tmp_path / 'src/ravel/data/roles/cards/generator.json'
    orphan.parent.mkdir(parents=True)
    orphan.write_text('{}')
    assert orphan in {Path(p) for p in rr.owned_paths(tmp_path).values()}


def test_owned_paths_outside_a_checkout_uses_the_package(monkeypatch):
    rr = registry()
    monkeypatch.setattr(rr, 'repository_root', lambda: None)
    paths = rr.owned_paths(None)
    package = Path(rr.__file__).resolve().parents[1]
    assert paths['src/ravel/__init__.py'] == package / '__init__.py'
    assert all(not str(label).startswith('.') for label in paths)


def test_host_passes_project_and_records_extension_metadata(tmp_path):
    from ravel.workflow import host_governance as gov
    rr = registry()
    project = tmp_path / 'project'
    roles = project / 'src/ravel/data/roles'
    roles.mkdir(parents=True)
    (roles / 'registry.json').write_text(json.dumps(rr.registry_document()))
    files = gov.surface_files(project)
    assert files['src/ravel/data/roles/registry.json'] == roles / 'registry.json'
    rundir = tmp_path / 'run'
    rundir.mkdir()
    row = gov.record_checkin1_surface(rundir, project=project)
    assert row['role_registry_sha256'] == rr.registry_sha256(roles_root=roles)


def test_installed_surface_refuses_profile_orphan(tmp_path):
    from ravel.workflow import agent_surface
    agent_surface.install(tmp_path, skills_from=ROOT, include_software=False)
    extra = tmp_path / '.claude/agents/ravel-extra.md'
    extra.write_text('Unregistered worker')
    assert 'generated surface orphan: .claude/agents/ravel-extra.md' in agent_surface.check(tmp_path)
