"""Execute the handbook example against fictional project policies."""
import json
from ravel.validation import tool_handbooks


def test_workflow_route_check(tmp_path):
    skill = tool_handbooks.handbook_root() / 'snakemake-workflows'
    block = tool_handbooks.blocks(skill)['workflow-route-check']
    namespace = {}
    exec(block['code'], namespace)
    check = namespace['direct_launch_refusal']
    assert check(tmp_path, 'ravel run --rundir ANA-0001') is None
    (tmp_path / 'workflow').mkdir()
    (tmp_path / 'workflow/policy.json').write_text(json.dumps(
        {'schema_version': 1, 'wms_required': True, 'engine': 'snakemake'}))
    assert check(tmp_path, 'ravel run --rundir ANA-0001')
    assert check(tmp_path, 'ravel wms launch --project . --task ANA-0001') is None
