"""Own role fixtures for construction checks: a tag-like loop and a compile-gated loop.

No upstream GPL body, SDK, compiler or scientific job: the "rivet-build" and
"rivet" executables are small shell scripts written by the test.
"""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import stat
import pytest
from ravel.workflow import agentrivet_pins, agentrivet_runtime, research_cycle
from agentrivet_construction_fixture import CORE, MEMORY, MODELS, schema, host, REVIEW, PHYSICS
from test_agentrivet_candidate import pin
from test_agentrivet_source import review_wrapper
from test_research_cycle import contract
from test_task_completion import goal

ROUTINE = 'OWN_2026_I1'
MODEL = {'beam_energy': '13 TeV', 'process': 'own synthetic process', 'object_construction': 'own particles',
         'cuts': ['own cut'], 'hepdata_url': None, 'fiducial_definition': 'own synthetic fiducial volume',
         'histograms': [{'name': 'pt', 'observable_definition': 'own pT', 'binning_source': 'HEPDATA',
                         'hepdata_id': 'd01-x01-y01', 'bin_edges': None, 'description': None}]}

GATED_CORE = '''from . import utils
from .build import build_routine
def make_llm(provider,model):
    raise RuntimeError("No fixture SDK dispatch")
class Agent:
    def __init__(self,llm,system_prompt=None,output_model=None):
        self.llm=llm;self.system_prompt=system_prompt;self.output_model=output_model
        assert llm.valid()
    def run(self,prompt):
        return self.llm.generate([{"role":"system","content":self.system_prompt},{"role":"user","content":prompt}],self.output_model)
class ReviewLoop:
    def __init__(self,analyst,coder,code_reviewer,physics_reviewer,max_iterations=3):
        self.analyst=analyst;self.coder=coder;self.code_reviewer=code_reviewer;self.physics_reviewer=physics_reviewer;self.max_iterations=max_iterations
        self.compiler=utils.detect_rivet()
    def _build_analyst_prompt(self,memory): return memory.get("paper_text")
    def _build_coder_prompt(self,memory):
        builds=memory.get("build_result",[None])
        if memory.item_length("code_draft") and builds and builds[-1] is not None and not builds[-1].success:
            return "Own compile-fix prompt for "+memory.rivetName()+": "+builds[-1].output
        return "Own code prompt for "+memory.rivetName()
    def _build_code_reviewer_prompt(self,memory): return memory.get("code_draft")[-1]
    def _build_physics_reviewer_prompt(self,memory): return memory.get("code_draft")[-1]
    def run(self,memory):
        memory.set("analysis_model",self.analyst.run(self._build_analyst_prompt(memory)))
        for i in range(self.max_iterations):
            memory.set("iteration",i+1)
            memory.append("code_draft",self.coder.run(self._build_coder_prompt(memory)).strip())
            if self.compiler:
                build=build_routine(memory.get("code_draft")[-1]);memory.append("build_result",build)
                if not build.success:
                    memory.append("code_review",None);memory.append("physics_review",None);continue
            memory.append("code_review",self.code_reviewer.run(self._build_code_reviewer_prompt(memory)))
            memory.append("physics_review",self.physics_reviewer.run(self._build_physics_reviewer_prompt(memory)))
            if memory.get("code_review")[-1].approved:
                memory.set("accepted_code",memory.get("code_draft")[-1]);break
        return memory
'''
GATED_BUILD = '''import subprocess
from .fixture_models import OwnModel
class BuildResult(OwnModel):
    schema={}
    def __init__(self,value=None,**fields):
        super().__init__(value if value is not None else fields)
    @property
    def success(self): return self.value["returncode"]==0
def build_routine(code):
    subprocess.run(["false"])
    raise RuntimeError("unaccounted upstream compile")
'''
GATED_UTILS = 'import own_absent_network_client\ndef detect_rivet():\n    return True\n'
GATED_MEMORY = MEMORY.replace('from .physics_reviewer_agent import PhysicsReviewModel\n',
    'from .physics_reviewer_agent import PhysicsReviewModel\nfrom .build import BuildResult\n').replace(
    'isinstance(v,(AnalysisModel,CodeReviewModel,PhysicsReviewModel))', 'isinstance(v,(AnalysisModel,CodeReviewModel,PhysicsReviewModel,BuildResult))').replace(
    '"PhysicsReviewModel":PhysicsReviewModel}', '"PhysicsReviewModel":PhysicsReviewModel,"BuildResult":BuildResult}').replace(
    'def rivetName(self): return "TEST"', 'def rivetName(self): return self.data.get("collaboration","X")+"_"+self.data.get("preprint_year","0")+"_I"+self.data.get("inspire_id","")')
TAG_MEMORY = MEMORY.replace('def rivetName(self): return "TEST"',
    'def rivetName(self): return self.data.get("collaboration","X")+"_"+self.data.get("preprint_year","0")+"_I"+self.data.get("inspire_id","")')


def files(gated):
    result = {'agentrivet/__init__.py': '# Own isolated source fixture\n',
              'agentrivet/core.py': GATED_CORE if gated else CORE,
              'agentrivet/memory.py': GATED_MEMORY if gated else TAG_MEMORY,
              'agentrivet/fixture_models.py': MODELS,
              'pyproject.toml': '[project]\nname="own-role-fixture"\nversion="1.0"\n',
              'COPYING': 'Own test source; no third-party GPL body.\n'}
    if gated:
        result.update({'agentrivet/build.py': GATED_BUILD, 'agentrivet/utils.py': GATED_UTILS})
    values = {'analyst': MODEL, 'code_reviewer': REVIEW, 'physics_reviewer': PHYSICS}
    for role, (filename, factory, prompt, model) in agentrivet_runtime.ROLES.items():
        definition = '' if model is None else f'class {model}(OwnModel):\n    schema={schema(values[role])!r}\n'
        result['agentrivet/' + filename] = (f'from .core import Agent,make_llm\nfrom .fixture_models import OwnModel\n'
            f'{prompt}="Own {role} instruction"\n{definition}def {factory}(provider,model):\n'
            f'    return Agent(make_llm(provider,model),{prompt},{model or "None"})\n')
    return result


@pytest.fixture(autouse=True)
def allow_own_censuses(monkeypatch):
    for gated in (False, True):
        census = {n: hashlib.sha256(t.encode()).hexdigest() for n, t in files(gated).items()}
        monkeypatch.setitem(agentrivet_pins.ALLOWED, 'own-gated' if gated else 'own-tag',
                            {'label': 'own fixture', 'compile_gate': gated, 'analysis_id_in_prompts': gated, 'files': census})


def executable(path, text):
    path.write_text(text)
    path.chmod(path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    return path


RIVET_BUILD = '''#!/bin/sh
if grep -q BROKEN "$2"; then echo "$2:3:5: error: unknown type name 'BROKEN'" >&2; exit 1; fi
printf 'own stub plugin\\n' > "$1"; echo "built $1"
'''


def rivet_stub(base, yoda_text):
    canned = base / 'canned.yoda'
    canned.write_text(yoda_text)
    return executable(base / 'rivet', f'''#!/bin/sh
out=""
while [ $# -gt 0 ]; do if [ "$1" = "-o" ]; then out="$2"; shift; fi; shift; done
cat "{canned}" > "$out"
echo "own stub rivet run"
''')


RECORD = {'schema_version': 1, 'kind': 'hepdata-record', 'record': 'own-synthetic-record',
          'tables': [{'name': 'Table 1', 'description': 'Own pT table',
                      'independent_variables': [{'header': {'name': 'pT', 'units': 'GeV'},
                                                 'values': [{'low': 0, 'high': 10}, {'low': 10, 'high': 20}, {'low': 20, 'high': 50}]}],
                      'dependent_variables': [{'header': {'name': 'dsig/dpT', 'units': 'pb/GeV'},
                                               'values': [{'value': 1.0, 'errors': [{'label': 'stat', 'symerror': 0.1}]},
                                                          {'value': 0.5}, {'value': 0.1}]}]},
                     {'name': 'Table 2', 'description': 'Own mass table', 'headers': [{'name': 'm'}, {'name': 'N'}],
                      'values': [{'x': [{'low': 1, 'high': 2}], 'y': [{'value': 3}]}, {'x': [{'low': 2, 'high': 4}], 'y': [{'value': 4}]}]}]}


def write(path, value):
    path.write_text(json.dumps(value))
    return pin(path)


def request(base, *, gated=False, initial=1, repairs=1, checks=True, sample=None, record=True,
            normalization=None, metadata=None, probes=4):
    root = base / 'source'
    (root / 'agentrivet').mkdir(parents=True)
    for name, text in files(gated).items():
        (root / name).parent.mkdir(parents=True, exist_ok=True)
        (root / name).write_text(text)
    census = [{'path': n, 'sha256': pin(root / n)['sha256']} for n in sorted(files(gated))]
    _, cp = goal(base)
    c = contract(base)
    c['goal_binding'] = {'contract': cp, 'assignment_id': 'summary-child'}
    c['budget'].update(calls=20, output_tokens=20 * 2048, wall_seconds=1800)
    campaign = base / 'campaign'
    research_cycle.create(campaign, c, base_dir=base, evaluation_harness=True)
    paper = base / 'paper.txt'
    paper.write_text('Complete own synthetic paper text; no physical benchmark.\n')
    tools = base / 'tools'
    tools.mkdir()
    rivet_build = executable(tools / 'rivet-build', RIVET_BUILD)
    construction = {'analysis_spec': None, 'hepdata_record': write(base / 'record.json', RECORD) if record else None,
                    'normalization': normalization, 'checks': None}
    if checks:
        construction['checks'] = {'schema_version': 1,
            'runtime': {'rivet_build': str(rivet_build), 'rivet': None if sample is None else str(sample['rivet']),
                        'python': None, 'environment': {}},
            'compile': {'max_probes': probes, 'timeout_seconds': 10},
            'sample': None if sample is None else {'events': sample['events'], 'max_events': 10,
                                                   'timeout_seconds': 10, 'tolerance': 0.02}}
    calls = 1 + 3 * (initial + repairs)
    return {'schema_version': 1, 'campaign': str(campaign), 'upstream': {'root': str(root), 'files': census},
            'paper': pin(paper), 'hepdata': {'context': None, 'assets': []},
            'metadata': metadata or {'arxiv_id': 'own.0001', 'inspire_id': '1', 'collaboration': 'OWN', 'preprint_year': '2026'},
            'provider': {'model': 'fixture-model', 'reasoning_effort': 'high', 'max_calls': calls,
                         'max_output_tokens': 2048, 'max_wall_seconds': 1600},
            'initial_rounds': initial, 'max_native_repairs': repairs, 'review_policy': review_wrapper(),
            'approval_mode': 'scripted_yes', 'construction': construction}


def draft(*, broken=False, extra=''):
    body = 'BROKEN x;' if broken else ''
    return (f'#include "Rivet/Analysis.hh"\nnamespace Rivet {{ class {ROUTINE} : public Analysis {{ {body}\n'
            f'void init() {{ book(_h["pt"], 1, 1, 1); {extra} }} }}; RIVET_DECLARE_PLUGIN({ROUTINE}); }}\n')


def review(approved=True, focus=None):
    value = deepcopy(REVIEW)
    value['approved'] = approved
    physics = deepcopy(PHYSICS)
    physics['revision_focus'] = focus
    return value, physics
