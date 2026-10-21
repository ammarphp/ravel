"""Source-derived atlas completeness and mutation controls; no native execution."""
import copy
import hashlib
import json
from pathlib import Path

import pytest
from ravel.setup import manifest as mf
from ravel.workflow import knowledge_atlas as ka
from ravel.validation.check_knowledge import validate as _validate

def validate(root=None, atlas=None):
    return _validate(root, atlas, require_curation=False)

ROOT = Path(__file__).resolve().parents[2]

@pytest.fixture(scope='module')
def atlas():
    return ka.generate(ROOT)

def test_deterministic_committed_bytes(atlas):
    assert ka.encode(atlas) == ka.encode(ka.generate(ROOT))
    assert ka.encode(atlas) == (ROOT / ka.ATLAS).read_bytes()
    assert validate(ROOT, atlas) == []

def test_current_catalogue_coverage(atlas):
    from ravel.workflow.science import MODES
    from ravel.cli import released_commands
    ids = {r['id'] for r in atlas['entries']}
    assert {f'op:{m}' for m in MODES if m not in mf.unreleased_operations(mf.load(ROOT)[0])} <= ids
    assert {f'cmd:{c}' for c in released_commands()} <= ids
    for row in atlas['entries']:
        if row['kind'] == 'op' and row.get('catalogue',{}).get('kind') == 'science-mode':
            assert row['catalogue']['adapter_exists']
            assert row['catalogue']['worker_destination']
            assert row['links']['docs']
        for key, values in row['links'].items():
            for identity in values if isinstance(values, list) else [values]:
                assert identity in ids, (row['id'], key, identity)

@pytest.mark.parametrize('kind',['op','cmd','tool','check','hb','trap','proto','doc','rule','checklist','skill','role'])
def test_omission_fails(atlas, kind, monkeypatch):
    monkeypatch.setattr("ravel.validation.check_knowledge.generate", lambda root: atlas)
    broken=copy.deepcopy(atlas)
    victim=next(r for r in broken['entries'] if r['kind']==kind)
    broken['entries'].remove(victim)
    assert validate(ROOT, broken)

def test_duplicate_and_broken_link_fail(atlas, monkeypatch):
    monkeypatch.setattr("ravel.validation.check_knowledge.generate", lambda root: atlas)
    broken=copy.deepcopy(atlas); broken['entries'].append(broken['entries'][0])
    assert validate(ROOT, broken)
    broken=copy.deepcopy(atlas); broken['entries'][0]['links']['docs']=['doc:absent']
    assert validate(ROOT, broken)

def test_handbook_maps_inverse(atlas):
    rows={r['id']:r for r in atlas['entries']}
    for row in rows.values():
        if row['kind']=='hb' and '#' not in row['id']:
            for identity in row['links'].get('operations',[]):
                assert row['id'] in rows[identity]['links']['handbooks']
        if row['kind']=='op':
            for identity in row['links'].get('handbooks', []):
                assert row['id'] in rows[identity]['links']['operations']

def test_descriptor_byte_identity():
    data = (ROOT/'src/ravel/data/mode_descriptors.json').read_bytes()
    manifest = mf.load(ROOT)[0]
    # A tree that carries the withheld list carries the protected source catalogue.
    if 'unreleased' in manifest:
        assert hashlib.sha256(data).hexdigest() == 'e90d530f67170bcb03622e13ba168f894051a59247c5176f788db4b574e16f0d'
    # Every tree ships that catalogue without the operations its release withholds.
    document = json.loads(data)
    held = mf.unreleased_operations(manifest)
    released = {**document, 'modes': {k: v for k, v in document['modes'].items() if k not in held}}
    encoded = (json.dumps(released, indent=1, ensure_ascii=False) + '\n').encode()
    assert held or encoded == data
    assert hashlib.sha256(encoded).hexdigest() == 'f83bc30ef033dcb1cb6f55fab98e480ab3bace1a1f98738b2a45e6cff8890ccf'


def test_default_gate_requires_operation_curation(atlas, monkeypatch):
    monkeypatch.setattr("ravel.validation.check_knowledge.generate", lambda root: atlas)
    assert _validate(ROOT,atlas)==[]
    broken=copy.deepcopy(atlas)
    victim=next(r for r in broken['entries'] if r['kind']=='op' and r['catalogue']['kind']=='science-mode')
    victim['op']['examples']=[]
    errors=_validate(ROOT,broken)
    assert any('curation requires use_when and examples' in error for error in errors)


def test_source_addition_and_deletion_fail(atlas, tmp_path):
    import shutil
    # Copy only the source inventory consumed by this generator; no run data.
    for pin in atlas['generator']['sources']:
        target=tmp_path/pin['path'];target.parent.mkdir(parents=True,exist_ok=True)
        shutil.copyfile(ROOT/pin['path'],target)
    assert validate(tmp_path, atlas)==[]
    extra=tmp_path/'src/ravel/validation/generic_extra_check.py'
    extra.write_text('"""A synthetic validator declaration."""\ndef validate(value): return []\n')
    assert validate(tmp_path,atlas)
    extra.unlink()
    victim=tmp_path/'src/ravel/validation/analysis_witness.py'
    victim.unlink()
    assert validate(tmp_path,atlas)


def test_new_mode_without_card_fails(atlas,tmp_path):
    import shutil
    for pin in atlas['generator']['sources']:
        target=tmp_path/pin['path'];target.parent.mkdir(parents=True,exist_ok=True)
        shutil.copyfile(ROOT/pin['path'],target)
    assert validate(tmp_path, atlas)==[]
    source=tmp_path/'src/ravel/workflow/science.py'
    text=source.read_text().replace('MODES = (', "MODES = ('generic-new-mode', ",1)
    source.write_text(text)
    assert validate(tmp_path,atlas)


def test_curation_unknown_fields_refused(atlas,tmp_path):
    import shutil
    for pin in atlas['generator']['sources']:
        target=tmp_path/pin['path'];target.parent.mkdir(parents=True,exist_ok=True)
        shutil.copyfile(ROOT/pin['path'],target)
    assert validate(tmp_path, atlas)==[]
    path=tmp_path/'src/ravel/data/knowledge/curation/model-events.json'
    path.parent.mkdir(exist_ok=True);path.write_text(json.dumps({'invented_efficiency':1}))
    errors=validate(tmp_path,atlas)
    assert any('unknown curation operation or fields' in error for error in errors)


def test_tool_installation_and_census_qualification(atlas):
    rows={r['id']:r for r in atlas['entries']}
    manifest=mf.view(ROOT)
    assert all('tool:'+g['id'] in rows for g in manifest['groups'] if g['id'] not in mf.unreleased_groups(manifest))
    qualifications=json.loads((ROOT/ka.QUALIFICATION).read_text())
    # The historical census holds 85 rows; a row added later names the registration fragment it came from.
    historical=[r for r in qualifications['tools'] if 'parent_census_row' not in r
                and r['source_locator'].startswith('tools-and-validation-census.md:')]
    assert len(historical)==85
    for item in qualifications['tools']:
        if 'parent_census_row' not in item and item not in historical:
            assert (ROOT/item['source_locator'].split('#')[0]).is_file() and '/registration/' in item['source_locator']
    for item in qualifications['tools']:
        if mf.withheld_tool(manifest, item):
            continue
        assert rows['tool:'+item['id']]['qualification_status']==item['status']
        assert item['status'] in ('qualified','built_but_unqualified','not_installed','excluded')
    for term in ('coffea','cabinetry','vector','boost-histogram','pyarrow'):
        assert any(r['kind']=='tool' and r['title']==term for r in rows.values())
    for row in rows.values():
        if row['kind']=='op' and row['catalogue']['kind']=='science-mode':
            for tool in row['links']['tools']:
                t=rows[tool]
                assert t.get('installer_group') or t.get('links',{}).get('installer_groups') or t['qualification_status']=='not_installed'


def test_symbolic_and_eft_routing(atlas):
    rows={r['id']:r for r in atlas['entries']}
    for name in ('FeynRules','SARAH','FeynCalc','FeynArts','FeynGraph','HEPTAPOD','Diagrammatica','pySecDec','FORM'):
        candidates=[r for r in rows.values() if r['kind']=='tool' and name.lower() in r['title'].lower() and r['links'].get('operations')]
        assert candidates, name
    assert any(r['kind']=='op' and 'SMEFT' in r.get('tags',[]) for r in rows.values())


def test_optional_signature_is_consumed(atlas,tmp_path):
    import shutil
    for pin in atlas['generator']['sources']:
        target=tmp_path/pin['path'];target.parent.mkdir(parents=True,exist_ok=True)
        shutil.copyfile(ROOT/pin['path'],target)
    path=tmp_path/'src/ravel/data/operation_signatures.json'
    path.write_text(json.dumps({'formula-grid':{'implementation':{'kind':'science-mode'},'consumes':[{'kind':'scalar','slot':'value'}], 'produces':[{'kind':'grid_values','slot':'grid'}], 'basis':{'adds':[]},'effects':[]}}))
    new=ka.generate(tmp_path)
    row=next(r for r in new['entries'] if r['id']=='op:formula-grid')
    assert row['op']['vocabulary_status']=='typed_signature'
    assert row['op']['inputs']==[{'kind':'scalar','slot':'value'}]


def test_missing_command_and_open_bundle_refused(atlas,tmp_path):
    import shutil
    for pin in atlas['generator']['sources']:
        target=tmp_path/pin['path'];target.parent.mkdir(parents=True,exist_ok=True)
        shutil.copyfile(ROOT/pin['path'],target)
    assert validate(tmp_path,atlas)==[]
    source=tmp_path/'src/ravel/cli.py';original=source.read_text()
    source.write_text(original.replace('"workflow.knowledge"','"workflow.generic_absent_module"',1))
    assert any('focused command module absent' in e for e in validate(tmp_path,atlas))
    source.write_text(original)
    extra=tmp_path/'src/ravel/data/workflow/generic-extra.md';extra.write_text('Synthetic extra instruction.')
    assert any('bundle is not closed' in e for e in validate(tmp_path,atlas))


def test_withheld_sources_are_not_indexed(atlas):
    from ravel import evidence_layout
    withheld = [p['path'] for p in atlas['generator']['sources']
                if evidence_layout.declared_internal(p['path'], ROOT)]
    withheld += [r['id'] for r in atlas['entries']
                 if evidence_layout.declared_internal(r['source']['path'], ROOT)]
    assert withheld == []


def _signatures():
    return json.loads((ROOT / 'src/ravel/data/operation_signatures.json').read_text())['operations']


def test_signature_declared_operations_and_review_terms_resolve(atlas):
    rows = {r['id']: r for r in atlas['entries']}
    for name, signature in _signatures().items():
        if 'implementation' not in signature or name in mf.unreleased_operations(mf.load(ROOT)[0]):
            continue
        assert 'op:' + name in rows, name
        row = rows['op:' + name]
        if row['catalogue']['kind'] in ('scoped-adapter', 'scoped-mode'):
            continue
        assert row['links']['docs'], name
        for term in signature.get('review', {}).get('checks', []):
            term = str(term).removeprefix('check:').removeprefix('ravel.')
            target = ka.REVIEW_TERM_CHECKS.get(term, term)
            linked = ('check:' + target in row['links']['checks']) or ('check:review/' + term in row['links']['checks'])
            assert linked, (name, term)
            assert ('check:' + target in rows) or ('check:review/' + term in rows), (name, term)


def test_mapped_review_terms_resolve_to_implementing_checks(atlas):
    rows = {r['id']: r for r in atlas['entries']}
    assert len(ka.REVIEW_TERM_CHECKS) >= 13
    for term, target in ka.REVIEW_TERM_CHECKS.items():
        assert 'check:' + target in rows, (term, target)
        assert 'check:review/' + term not in rows, term
        assert rows['check:' + target]['status'] == 'registered'


UNRESOLVED_TERM_CEILING = 10


def test_unresolved_review_terms_are_declared_not_registered(atlas):
    placeholders = [r for r in atlas['entries'] if r['id'].startswith('check:review/')]
    for row in placeholders:
        assert row['status'] == 'declared_term', row['id']
        assert row['summary'] == 'no implementing check linked', row['id']
    assert len(placeholders) <= UNRESOLVED_TERM_CEILING


def test_generated_indexes_are_registered_but_never_operation_knowledge(atlas):
    """A generated index mentions every declaration it maps. Linking it as operation knowledge would
    present the whole index at every operation and exceed the bounded instruction read, so the atlas
    registers it as a document and links operations only to documents that reader admits."""
    from ravel.controller.instructions import compiler
    rows = {r['id']: r for r in atlas['entries']}
    indexes = {r['id'] for r in atlas['entries'] if r['kind'] == 'doc'
               and ka.GENERATED_INDEX_MARKER in (ROOT / r['source']['path']).read_text()}
    assert indexes
    for row in atlas['entries']:
        if row['kind'] != 'op':
            continue
        for identity in row['links']['docs']:
            assert identity not in indexes, (row['id'], identity)
            size = (ROOT / rows[identity]['source']['path']).stat().st_size
            assert size <= compiler.MAX_SOURCE_BYTES, (row['id'], identity, size)
