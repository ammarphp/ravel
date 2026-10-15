"""Inert synthetic likelihood file worker; imports no scientific engine."""
import hashlib
import json
from pathlib import Path
import sys

raw = Path(sys.argv[1]).read_bytes()
request = json.loads(raw)
result = {'schema_version': 1, 'operation': request['operation'],
          'request_sha256': hashlib.sha256(raw).hexdigest(),
          'comparison_input_sha256': request['comparison_input_sha256'],
          'database': request['database'], 'minus2_log_likelihood': 8., 'n_obs': 3,
          'sm_reference': {'same_call': True, 'minus2_log_likelihood': 5., 'n_obs': 3,
                           'input_sha256': hashlib.sha256(request['sm_xml'].encode()).hexdigest()}}
if 'runtime_version' in request:
    result['runtime_version'] = request['runtime_version']
if request.get('delegation'):
    result['imported_sources'] = [
        {'path': path, 'sha256': sha}
        for path, sha in request['delegation']['input_hashes'].items() if path.endswith('.py')]
Path(sys.argv[2]).write_text(json.dumps(result, allow_nan=False))
