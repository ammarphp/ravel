from pathlib import Path
import json
from ravel.workflow import physics_review as review
from test_physics_review import run,make_attempt,check_packet

def test_absolute_located_evidence_normalizes_without_mutating_observed_document(run):
    root,_=run;record=make_attempt(root);check_packet(root,record)
    path=root/'inputs/checks.json';data=json.loads(path.read_text())
    for row in data['checks']:
        for ref in row['evidence']:ref['path']=str((root/ref['path']).resolve())
    path.write_text(json.dumps(data));before=path.read_bytes()
    event=review.open_cycle(root,effective_settings=['inputs/settings.cfg'],stage_receipts=[record['attempt_record']],check_results='inputs/checks.json')
    assert path.read_bytes()==before
    assert all(not Path(ref['path']).is_absolute() for row in event['checks'] for ref in row['evidence'])
