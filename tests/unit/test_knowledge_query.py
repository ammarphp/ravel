"""Deterministic retrieval and CLI projections from the generated atlas."""
import json
from ravel.workflow.knowledge import query, main
from ravel.workflow.knowledge_atlas import encode, digest


def test_generation_knowledge():
    result=query('for_node', operation='model-events')
    ids=set(result['served_ids'])
    assert {'hb:madgraph-launch','hb:madgraph-model-import','hb:pythia-shower-cards',
            'hb:lhapdf-pdf-sets','trap:T6','trap:T11','trap:T12',
            'check:physics.model_events.check_cards','role:consult-madgraph'} <= ids
    role=next(r for r in result['results'] if r['id']=='role:consult-madgraph')
    assert role['status']=='registered'
    assert role['catalogue']['kind'] == 'role-card'
    assert role['catalogue']['knowledge']['must_read']
    assert role['catalogue']['requires']['attestation_min'] == 'transport'


def test_find_generic_recasting(tmp_path):
    from ravel.workflow.knowledge import load_atlas
    atlas=load_atlas()
    # A generic lexical-retrieval fixture; operation curation is a separate stream.
    ids={'op:analyze','op:ma5-pad','op:model-portfolio'}
    atlas['entries']=[r for r in atlas['entries'] if r['id'] in ids or r['id']=='op:formula-grid']
    for row in atlas['entries']:
        row['op']['use_when']=['Recast a search for a new model from supplied inputs.'] if row['id'] in ids else ['Evaluate a declared formula.']
    path=tmp_path/'atlas.json';path.write_bytes(encode(atlas))
    result=query('find', text='recast a stop search for a new model', kinds=['op'], limit=5,atlas_path=path,floor=0)
    assert ids <= set(result['served_ids'])
    assert result==query('find', text='recast a stop search for a new model', kinds=['op'], limit=5,atlas_path=path,floor=0)


def test_result_hash_and_schema():
    result=query('show', id='op:model-events')
    sha=result.pop('result_sha256')
    assert sha==digest(encode(result))
    assert result['results'][0]['why']


def test_modes_is_projection(capsys):
    assert main(['list','--json'])==0
    result=json.loads(capsys.readouterr().out)
    from ravel.workflow.science import MODES
    from ravel.setup import manifest as mf
    assert len(result['modes']) == len(set(MODES) - mf.unreleased_operations(mf.load()[0]))
    assert all(row['kind']=='op' for row in result['modes'])
    assert main(['show','model-events','--json'])==0
    result=json.loads(capsys.readouterr().out)
    assert result['results'][0]['id']=='op:model-events'


def test_unknown_node_and_failure_hold():
    result=query('for_node',operation='unregistered-operation')
    assert not result['results'] and result['missing']
    result=query('for_failure',failure_class='unknown',tool='unknown')
    assert result['missing']


def test_plan_check_reports_gaps():
    result=query('plan_check',plan={'nodes':[{'id':'a','operation':'model-events','validation_tier':'native_smoke'}, {'id':'b','operation':'unknown'}]})
    assert result['nodes'][0]['missing']
    assert result['nodes'][1]['missing']


def test_limit_has_omission_census():
    result=query('find',text='recast a search for a new model',limit=1)
    assert result['omitted']['count']>0


def test_packaged_example(capsys):
    assert main(['example','formula-grid','--json'])==0
    result=json.loads(capsys.readouterr().out)
    assert result['status']=='available'
    from ravel.physics.inference.formula_grid import validate
    validate(result['examples'][0]['spec']['task'])


def test_missing_example_is_explicit(capsys):
    assert main(['example','stage/generation','--json'])==1
    result=json.loads(capsys.readouterr().out)
    assert result['status']=='held:curation_missing'


def test_lifecycle_and_scoped_queries():
    assert 'op:stage/generation' in query('for_node',operation='generation')['served_ids']
    assert 'op:generate' in query('for_node',operation='generate')['served_ids']


def test_exact_serialized_budget():
    for budget in (1024, 2048, 4096, 8192, 16384):
        result=query('find',text='model',max_bytes=budget)
        assert len(encode(result))<=budget
        sha=result.pop('result_sha256')
        assert sha==digest(encode(result))


def test_user_facing_text_has_no_internal_labels(capsys):
    import re
    from pathlib import Path
    from ravel.validation.check_knowledge import main as check_main
    internal = re.compile(r'\bKM-\d|\bstreams?\b')
    texts = []
    main(['example', 'model-events', '--json']); texts.append(capsys.readouterr().out)
    texts.append(json.dumps(query('for_failure', tool='generic', failure_class='generic')['missing']))
    texts.append(json.dumps(query('coverage')['missing']))
    try:
        check_main(['--help'])
    except SystemExit:
        pass
    texts.append(capsys.readouterr().out)
    root = Path(__file__).resolve().parents[2]
    texts.append((root / 'docs/reference/knowledge.md').read_text())
    qualification = json.loads((root / 'src/ravel/data/knowledge/qualification.json').read_text())
    texts.append(json.dumps(qualification['routing']))
    for text in texts:
        assert not internal.search(text), internal.search(text).group(0)
