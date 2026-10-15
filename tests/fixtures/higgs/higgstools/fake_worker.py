"""Inert synthetic JSON child: no external library or native computation."""
import hashlib
import json
from pathlib import Path
import sys

request_path, response_path = map(Path, sys.argv[1:])
request = json.loads(request_path.read_text())
bundle = request['bundle']
fixtures = Path(__file__).parent
result = {'schema_version':1, 'operation':request['operation'],
          'request_sha256':hashlib.sha256(request_path.read_bytes()).hexdigest(),
          'datasets':{k:v['commit'] for k,v in bundle['datasets'].items()}}
if request['operation'] == 'higgs-bounds':
    data = json.loads((fixtures/'hbdataset/synthetic.json').read_text())
    selected = min(data['limits'], key=lambda row:row['expected_pb'])
    result['particles'] = [{'id':p['id'], 'allowed':True,
                           'obsratio':1/selected['observed_pb'],
                           'expected_ratio':1/selected['expected_pb'],
                           'selected_limit_id':selected['id']}
                          for p in bundle['neutral_scalars']+bundle['charged_scalars']]
else:
    data = json.loads((fixtures/'hsdataset/synthetic.json').read_text())
    total = sum(m['chi2'] for m in data['measurements'])
    result.update(chi2_total=total, measurements=data['measurements'], n_obs=3,
                  sm_reference={'chi2_total':data['sm_chi2_total'], 'n_obs':3, 'same_call':True,
                                'input_sha256':bundle['sm_reference']['sha256']},
                  delta_chi2=total-data['sm_chi2_total'])
response_path.write_text(json.dumps(result,allow_nan=False)+'\n')
