"""Verify native conversion using real tiny ROOT TTrees and a valid pyhf workspace.

Requires uproot, numpy, pyhf and jsonpatch in the current Python environment.
All ROOT inputs and generated patches live in a fresh temporary directory.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def verify():
    import jsonpatch
    import numpy as np
    import pyhf
    import uproot

    repository = Path(__file__).resolve().parents[3]
    engine = repository / 'src/ravel/physics/sa2json_native.py'
    require(engine.is_file(), 'Run this script from its audit directory in a Ravel checkout')
    engine_hash = hashlib.sha256(engine.read_bytes()).hexdigest()
    workspace = {
        'version': '1.0.0',
        'channels': [{'name': name, 'samples': [
            {'name': 'background', 'data': [10.], 'modifiers': [
                {'name': 'background_scale', 'type': 'normfactor', 'data': None}]}]}
            for name in ['Z_cuts', 'A_cuts']],
        'observations': [{'name': name, 'data': [10.]} for name in ['Z_cuts', 'A_cuts']],
        'measurements': [{'name': 'Measurement', 'config': {
            'poi': 'signal_strength', 'parameters': []}}],
    }
    # Validate the background model separately. The declared signal POI becomes
    # a model parameter only when the converter inserts the signal sample.
    pyhf.Workspace(workspace).model(poi_name='background_scale')
    reports = []

    with tempfile.TemporaryDirectory(prefix='ravel-root-io-') as temporary:
        directory = Path(temporary)
        background = directory / 'declared-background.json'
        background.write_text(json.dumps(workspace, indent=2) + '\n')
        before = background.read_bytes()

        def run_case(name, branches, *, lumi=3, flavour=None, background_owned_poi=False, expected_error=None):
            ntuple = directory / (name + '.root')
            with uproot.recreate(ntuple) as root:
                root.mktree('ntuple', {key: 'float64' for key in branches})
                root['ntuple'].extend({key: np.array(values, dtype=np.float64)
                                      for key, values in branches.items()})
            input_hash=hashlib.sha256(ntuple.read_bytes()).hexdigest()
            selected_workspace=json.loads(json.dumps(workspace))
            selected_background=background
            if background_owned_poi:
                selected_workspace['measurements'][0]['config']['poi']='background_scale'
                selected_background=directory/(name+'.background.json')
                selected_background.write_text(json.dumps(selected_workspace,indent=2)+'\n')
            selected_before=selected_background.read_bytes()
            mapping={name+'_cuts':{'region':name,**({'flavour':flavour} if flavour else {})} for name in ('Z','A')}
            channel_map=directory/(name+'.channel-map.json')
            channel_map.write_text(json.dumps(mapping,indent=2)+'\n')
            mapping_before=channel_map.read_bytes()
            output = directory / (name + '.patch.json')
            command = [sys.executable, str(engine), '-i', str(ntuple), '-b', str(selected_background),
                       '-o', str(output), '-n', 'signal', '-l', str(lumi),'--channel-map',str(channel_map)]
            result = subprocess.run(command, capture_output=True, text=True, timeout=60,
                                    env={**os.environ, 'PYTHONDONTWRITEBYTECODE': '1'})
            record = {'name': name, 'exit_code': result.returncode, 'patch_exists': output.exists(),
                      'input_root_sha256':input_hash,'adapter':'explicit-channel-map',
                      'declared_poi':selected_workspace['measurements'][0]['config']['poi']}
            if expected_error is not None:
                require(result.returncode != 0 and not output.exists(), f'{name}: invalid input created a patch')
                require(expected_error in result.stderr, f'{name}: failed for an unexpected reason')
                # Store the checked diagnostic, not tracebacks containing temporary/machine paths.
                record['checked_error'] = expected_error
            else:
                require(result.returncode == 0 and output.exists(),
                        f'{name}: converter did not produce a patch: {result.stderr.strip()}')
                patched = jsonpatch.apply_patch(selected_workspace, json.loads(output.read_text()), in_place=False)
                model = pyhf.Workspace(patched).model()
                require(model.config.poi_name=='signal_strength',f'{name}: declared signal POI was not preserved')
                record['model_poi']=model.config.poi_name
                record['named_signal_data'] = {
                    channel['name']: next(sample['data'] for sample in channel['samples']
                                          if sample['name'] == 'signal')
                    for channel in patched['channels']}
                record['workspace_order'] = [channel['name'] for channel in patched['channels']]
                record['model_order'] = model.config.channels
                record['expected_data_initial'] = model.expected_data(model.config.suggested_init()).tolist()
            require(background.read_bytes() == before, f'{name}: input workspace changed')
            require(selected_background.read_bytes()==selected_before,f'{name}: selected input workspace changed')
            require(channel_map.read_bytes()==mapping_before,f'{name}: explicit channel map changed')
            require(hashlib.sha256(ntuple.read_bytes()).hexdigest()==input_hash,f'{name}: input ROOT file changed')
            record['background_unchanged'] = True
            record['channel_map_unchanged']=True
            record['input_root_unchanged']=True
            reports.append(record)
            return record

        positive = run_case('signed-unsorted', {'Z': [2., -1., 2.], 'A': [1., 1., 2.]})
        require(positive['named_signal_data'] == {'Z_cuts': [9.], 'A_cuts': [12.]}, 'Named channel mapping is incorrect')
        require(positive['workspace_order'] == ['Z_cuts', 'A_cuts'], 'Source workspace order changed')
        require(positive['model_order'] == ['A_cuts', 'Z_cuts'], 'The sorting test did not exercise different channel orders')
        require(positive['expected_data_initial'] == [22., 19.], 'pyhf expected data disagree with named signal yields')

        masked = run_case('signed-masked', {'Z': [2., -.5, 9.], 'A': [3., -1., 8.],
                                           'ismm': [1., 1., 0.]}, lumi=1, flavour='ismm')
        require(masked['named_signal_data'] == {'Z_cuts': [1.5], 'A_cuts': [2.]}, 'Flavour mask lost signed weights')
        run_case('negative-net', {'Z': [1., -2.], 'A': [1., 1.]}, expected_error='negative net signal yield')
        zero = run_case('zero-net', {'Z': [1., -1.], 'A': [1., 1.]})
        require(zero['named_signal_data'] == {'Z_cuts': [0.], 'A_cuts': [6.]}, 'A zero-net channel was not retained correctly')
        allzero = run_case('all-zero-net', {'Z': [1., -1.], 'A': [2., -2.]})
        require(allzero['named_signal_data'] == {'Z_cuts': [0.], 'A_cuts': [0.]}, 'All-zero template behavior changed')
        run_case('zero-luminosity', {'Z': [1.], 'A': [1.]}, lumi=0,
                 expected_error='--lumi must be finite and positive')
        run_case('missing-branch', {'A': [1.]}, expected_error='missing or invalid SR branch')
        run_case('nonfinite-weight', {'Z': [float('nan')], 'A': [1.]},
                 expected_error='must contain finite scalar weights')
        run_case('background-owned-poi',{'Z':[1.],'A':[1.]},background_owned_poi=True,
                 expected_error='signal POI already modifies a background sample')

    require(hashlib.sha256(engine.read_bytes()).hexdigest() == engine_hash, 'Converter changed during verification')
    return {
        'schema_version': 1, 'passed_cases': len(reports),
        'engine': 'src/ravel/physics/sa2json_native.py', 'engine_sha256': engine_hash,
        'script_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        'versions': {name: importlib.metadata.version(name) for name in ['uproot', 'numpy', 'pyhf', 'jsonpatch']},
        'background_unchanged': True, 'input_roots_unchanged':True,'channel_maps_unchanged':True,'cases': reports,
        'scope': 'Actual tiny ROOT TTree integration, including real Awkward-array reads and pyhf/JSON Patch validation. '
                 'Uses explicit channel maps and the declared signal-only POI without a model POI override. '
                 'Zero-net channels and all-zero templates are accepted. Zero luminosity and negative-net templates '
                 'are rejected, as is a POI already applied to background. This is input/output correctness, '
                 'not statistical coverage or a finite-limit claim.',
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, help='Write verification JSON to a new path; otherwise print it')
    args = parser.parse_args()
    if args.out is not None and args.out.exists():
        parser.error('--out must be a new path; preserve existing evidence')
    try:
        report = verify()
    except (ImportError, OSError, RuntimeError, subprocess.TimeoutExpired) as exc:
        parser.exit(1, f'ROOT integration check failed: {exc}\n')
    rendered = json.dumps(report, indent=2, allow_nan=False) + '\n'
    if args.out is None:
        print(rendered, end='')
    else:
        with args.out.open('x') as stream:
            stream.write(rendered)
        print(f"Verified {report['passed_cases']} real ROOT cases; background unchanged.")


if __name__ == '__main__':
    main()
