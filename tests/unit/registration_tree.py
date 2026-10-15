"""A disposable copy of the shared registries and a loader for the registration merger.

The copy holds the real registries and toolchain manifest, so the merger's validators run against
the actual repository state; fragments written into it are synthetic.
"""
import importlib.util
import json
from pathlib import Path
import shutil

ROOT = Path(__file__).resolve().parents[2]
REGISTRIES = ('src/ravel/data/operation_signatures.json', 'src/ravel/data/mode_descriptors.json',
              'src/ravel/data/backends/census.json', 'src/ravel/data/knowledge/qualification.json')


def merger():
    spec = importlib.util.spec_from_file_location('merge_registration',
                                                  ROOT / 'scripts/maintenance/merge_registration.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def tree(tmp_path):
    root = tmp_path / 'tree'
    shutil.copytree(ROOT / 'native/setup', root / 'native/setup')
    for relative in REGISTRIES:
        (root / relative).parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / relative, root / relative)
    (root / 'src/ravel/data/knowledge/curation').mkdir(parents=True, exist_ok=True)
    (root / 'docs').mkdir()
    return root


def fragment(root, domain, name, document):
    path = root / 'src/ravel/data' / domain / 'registration' / (name + '.json')
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(document, indent=1) + '\n')
    return path


def snapshot(root):
    return {p.relative_to(root).as_posix(): p.read_bytes() for p in sorted(root.rglob('*.json'))
            if 'registration' not in p.parts}


def command_operation(mode, module='ravel.cli'):
    """A conforming command-kind signature and a general descriptor for a fictional operation."""
    signature = {'summary': 'Fictional supplied-table transform.',
                 'implementation': {'kind': 'command', 'module': module},
                 'consumes': [{'slot': 'table', 'kind': 'table', 'task_pointer': '/task/input'}],
                 'produces': [{'slot': 'result', 'kind': 'table'}],
                 'effects': [], 'cost': {'unit': 'task', 'forecast': None, 'ceiling_pointer': None},
                 'critical_fields': ['/task/input'], 'basis': {'adds': [], 'passes': ['table']},
                 'tools': ['numpy'], 'stages': ['statistic'], 'review': {'checks': ['io_contract']},
                 'fidelity_rank': 1}
    descriptor = {'summary': 'Fictional supplied-table transform.', 'operations': [], 'tools': ['numpy'],
                  'inputs': ['supplied table'], 'observables': ['fictional quantity'], 'outputs': ['table'],
                  'context': ['fictional context'], 'applicability': {'scope': 'general'}}
    return signature, descriptor


def census_row(identity, qualification='not-built', **extra):
    return {'id': identity, 'title': 'Fictional ' + identity, 'installer_groups': ['python-host'],
            'doctor_checks': [{'kind': 'manifest', 'group': 'python-host', 'check': 'host-python'}],
            'qualification': qualification, 'notes': 'Fictional installation pending.', **extra}
