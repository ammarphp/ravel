"""Synthetic released-tool API controls; no native engines or framework code."""
import builtins
import hashlib
import json
import os
from pathlib import Path
import sys

import pytest

from ravel.physics import diagram_analysis_worker as worker


FILES = (
    'nda/topology', 'nda/particle_database', 'nda/quantum_validation',
    'nda/simple_diagram', 'nda/phase_space', 'nda/matrix_element',
    'nda/summary_formatting', 'logging/findings', 'nda/nda_tool',
)


def fixture_request(tmp_path):
    root = tmp_path/'upstream'; root.mkdir()
    for name in FILES:
        p = root/'tools'/(name+'.py'); p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text('# Authored inert dependency fixture.\n')
    for name in ('', 'nda', 'logging'):
        (root/'tools'/name/'__init__.py').write_text('raise AssertionError("package initializer executed")\n')
    (root/'tools/nda/nda_tool.py').write_text('''from orchestral.tools.base.tool import BaseTool
from orchestral.tools.base.field_utils import RuntimeField, StateField
import json
class EstimateDecayWidthNDATool(BaseTool):
    diagram: dict = RuntimeField(description="Supplied diagram")
    include_summary: bool = RuntimeField(default=True, description="Summary")
    process_label: str = RuntimeField(default=None, description="Label")
    base_directory: str = StateField(description="Output")
    def _run(self):
        assert self.include_summary is False and self.process_label is None
        if self.diagram.get('fail'):
            return self.format_error(error="Synthetic failure", reason="Requested failure")
        return json.dumps({'status': 'ok', 'width_gev': self.diagram['value']})
''')
    out = tmp_path/'out'; out.mkdir()
    paths = [p for p in root.rglob('*') if p.is_file()]
    paths.append(Path(sys.executable).resolve())
    return {'source_root': str(root), 'sites': [],
        'assets': {str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in paths},
        'driver_sha256': hashlib.sha256(Path(worker.__file__).read_bytes()).hexdigest(),
        'diagrams': [{'id': 'first', 'diagram': {'value': 2}},
                     {'id': 'second', 'diagram': {'value': 0}},
                     {'id': 'third', 'diagram': {'fail': True}}], 'output': str(out)}


@pytest.fixture
def no_framework(monkeypatch):
    original = builtins.__import__
    attempts = []
    def guard(name, *args, **kwargs):
        if name == 'orchestral' or name.startswith('orchestral.'):
            attempts.append(name)
            raise AssertionError('orchestral import attempted')
        return original(name, *args, **kwargs)
    monkeypatch.setattr(builtins, '__import__', guard)
    yield attempts
    assert attempts == []
    assert not any(n == 'orchestral' or n.startswith('orchestral.') for n in sys.modules)


def run_worker(request, tmp_path, monkeypatch):
    path = tmp_path/'request.json'; path.write_text(json.dumps(request))
    monkeypatch.setattr(sys, 'argv', ['worker', str(path)])
    worker.main()
    return json.loads((Path(request['output'])/'nda-result.json').read_text())


def test_whole_population_preserves_synthetic_api_rows(tmp_path, monkeypatch, no_framework):
    request = fixture_request(tmp_path)
    before = {n: m for n, m in sys.modules.items() if n == 'tools' or n.startswith('tools.')}
    result = run_worker(request, tmp_path, monkeypatch)
    # Authored expected rows; not recorded orchestral outputs or physics references.
    assert [(r['id'], r['status'], r['result']) for r in result['rows']] == [
        ('first', 'delivered', {'status': 'ok', 'width_gev': 2}),
        ('second', 'delivered', {'status': 'ok', 'width_gev': 0}),
        ('third', 'failed', {'status': 'error', 'error': 'Synthetic failure', 'reason': 'Requested failure'}),
    ]
    assert {n: m for n, m in sys.modules.items() if n == 'tools' or n.startswith('tools.')} == before


@pytest.mark.parametrize('mutation', ['unadmitted', 'framework', 'hidden', 'dynamic'])
def test_unavailable_closure_preserves_every_row(tmp_path, monkeypatch, no_framework, mutation):
    request = fixture_request(tmp_path)
    source = Path(request['source_root'])/'tools/nda/nda_tool.py'
    if mutation == 'unadmitted': request['assets'].pop(str(source))
    if mutation in ('framework', 'hidden'):
        source.write_text(('from orchestral.agent import Agent\n' if mutation == 'framework'
                           else 'import tools.agent_loop\n')+source.read_text())
        request['assets'][str(source)] = hashlib.sha256(source.read_bytes()).hexdigest()
    if mutation == 'dynamic':
        source.write_text("import importlib\nimportlib.import_module('orchestral.runtime')\n"+source.read_text())
        request['assets'][str(source)] = hashlib.sha256(source.read_bytes()).hexdigest()
    result = run_worker(request, tmp_path, monkeypatch)
    assert [r['id'] for r in result['rows']] == ['first', 'second', 'third']
    assert all(r['status'] == 'unavailable' and r['reason'] and r['requires'] for r in result['rows'])
    assert not any((Path(request['output'])/r['id']).exists() for r in result['rows'])


@pytest.mark.parametrize('mutation', ['missing', 'changed'])
def test_preexisting_source_mutation_refuses_delivery(tmp_path, monkeypatch, no_framework, mutation):
    request = fixture_request(tmp_path)
    source = Path(request['source_root'])/'tools/nda/nda_tool.py'
    if mutation == 'missing': source.unlink()
    else: source.write_text('raise AssertionError("changed")\n')
    with pytest.raises(ValueError, match='input changed'):
        run_worker(request, tmp_path, monkeypatch)
    assert not (Path(request['output'])/'nda-result.json').exists()


def test_runtime_framework_demand_is_unavailable(tmp_path, monkeypatch, no_framework):
    request = fixture_request(tmp_path)
    source = Path(request['source_root'])/'tools/nda/nda_tool.py'
    source.write_text(source.read_text().replace(
        'assert self.include_summary',
        "import importlib\n        importlib.import_module('orchestral.runtime')\n        assert self.include_summary"))
    request['assets'][str(source)] = hashlib.sha256(source.read_bytes()).hexdigest()
    result = run_worker(request, tmp_path, monkeypatch)
    assert all(r['status'] == 'unavailable' and r['reason'] and r['requires'] for r in result['rows'])


def test_source_mutation_during_execution_is_refused(tmp_path, monkeypatch, no_framework):
    request = fixture_request(tmp_path)
    source = Path(request['source_root'])/'tools/nda/nda_tool.py'
    source.write_text(source.read_text().replace("assert self.include_summary", "from pathlib import Path\n        Path(__file__).write_text('changed')\n        assert self.include_summary"))
    request['assets'][str(source)] = hashlib.sha256(source.read_bytes()).hexdigest()
    with pytest.raises(ValueError, match='input changed'):
        run_worker(request, tmp_path, monkeypatch)
    assert not (Path(request['output'])/'nda-result.json').exists()


def test_eda_and_symbolic_selected_loaders_need_no_framework(tmp_path, monkeypatch, no_framework):
    from ravel.physics import diagrammatica_code as eda, symbolic_evaluation as symbolic
    sources = {rel: b'# Inert pure API fixture.\n' for rel in eda.BACKEND}
    monkeypatch.setattr(eda, 'BACKEND', {rel: hashlib.sha256(raw).hexdigest() for rel, raw in sources.items()})
    with eda._backend(sources) as (diagram, code):
        assert diagram.__name__ == 'tools.nda.simple_diagram'
        assert code.__name__ == 'tools.eda.feyncalc_codegen'
    # The selected parser/converter loader executes captured bytes directly.
    for name in ('wolfram_runner', 'symbolic_to_python'):
        path = tmp_path/(name+'.py'); path.write_text('def convert(value):\n    return value\n')
        mod = symbolic._external_module(path, '_synthetic_'+name, hashlib.sha256(path.read_bytes()).hexdigest())
        assert mod.convert('x') == 'x'
        assert mod.__name__ not in sys.modules


def test_external_pinned_deterministic_closure(tmp_path, monkeypatch, no_framework):
    """Opt-in external GPL files, never copied into the repository.

    This tests API compatibility, not equivalence to an orchestral execution or
    independent numerical physics. No kernel, subprocess or site tools run.
    """
    from ravel.physics.feyn_graph import API
    source = os.environ.get('RAVEL_HEPTAPOD_TEST_SOURCE')
    if not source:
        pytest.skip('external pinned HEPTAPOD fixture not supplied')
    root = Path(source).resolve()
    required = json.loads(API.read_text())['heptapod']['required_sources']
    for rel, digest in required.items():
        assert hashlib.sha256((root/rel).read_bytes()).hexdigest() == digest
    request = fixture_request(tmp_path)
    request['source_root'] = str(root)
    paths = [root/(name.replace('.', '/')+'.py') for name in worker.MODULES]
    paths.append(Path(sys.executable).resolve())
    request['assets'] = {str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}
    request['diagrams'] = [{'id': 'scalar', 'diagram': {
        'topology': 'tree_2body', 'initial': [{'label': 'X', 'spin': 0, 'mass': 30}],
        'final': [{'label': 's1', 'spin': 0, 'mass': 1}, {'label': 's2', 'spin': 0, 'mass': 2}],
        'vertices': [{'type': 'scalar-3pt', 'coupling': 'g'}], 'couplings': {'g': 0.1},
        'color_factor': 1}}, {'id': 'invalid', 'diagram': {}}]
    result = run_worker(request, tmp_path, monkeypatch)
    assert [(r['id'], r['status']) for r in result['rows']] == [('scalar', 'delivered'), ('invalid', 'failed')]
    assert result['rows'][0]['result']['width_gev'] > 0


def test_external_parser_and_converter_without_kernel(tmp_path, no_framework):
    from ravel.physics import symbolic_evaluation as symbolic
    source = os.environ.get('RAVEL_HEPTAPOD_TEST_SOURCE')
    if not source:
        pytest.skip('external pinned HEPTAPOD fixture not supplied')
    root = Path(source)
    parser = symbolic._external_module(root/'tools/eda/wolfram_runner.py',
                                       '_pinned_parser_control', symbolic.BACKEND['wolfram_runner.py'])
    converter = symbolic._external_module(root/'tools/eda/symbolic_to_python.py',
                                          '_pinned_converter_control', symbolic.BACKEND['symbolic_to_python.py'])
    parsed = parser._parse_structured_output('SYMBOLIC_RESULT[value]: x^2\nSTATUS: complete\n')
    assert parsed['symbolic']['value'] == 'x^2'
    assert converter.mathematica_to_callable('x^2', ['x'])(3) == 9
    code = converter.mathematica_to_python_source('x^2', ['x'], function_name='square')
    assert 'def square(' in code


def test_external_eda_generation_without_framework(no_framework):
    from ravel.physics import diagrammatica_code as eda
    source = os.environ.get('RAVEL_HEPTAPOD_TEST_SOURCE')
    if not source:
        pytest.skip('external pinned HEPTAPOD fixture not supplied')
    sources = {rel: (Path(source)/rel).read_bytes() for rel in eda.BACKEND}
    diagram = {'topology': 'tree_2body', 'initial': [{'label': 'X', 'spin': 0, 'mass': 30}],
               'final': [{'label': 's1', 'spin': 0, 'mass': 1}, {'label': 's2', 'spin': 0, 'mass': 2}],
               'vertices': [{'type': 'scalar-3pt', 'coupling': 'g'}], 'couplings': {'g': 0.1}}
    with eda._backend(sources) as (parser, generator):
        result = generator.SymbolicFeynCalcCodeGenerator(assume_real_couplings=False).generate(parser.parse_diagram(diagram))
        assert result.process_type.name == 'DECAY_1TO2' and result.code
        assert not result.warnings
