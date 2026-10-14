"""Tiny synthetic inputs for the production stage: LHE files, Delphes cards and stub programs.

The stub shower, Delphes and hadd programs are small Python scripts with the same command
lines as the real ones. They read the LHE events they are given and write HepMC3 and
Delphes-shaped ROOT files, so the whole chain runs in a test without native tools.
"""
import json
import os
from pathlib import Path
import stat
import sys

HERE = Path(__file__).resolve().parent

SYNTHETIC_CARD = """\
# synthetic detector card for tests
set ExecutionPath {
  ParticlePropagator
  ECal
  HCal
  EFlowMerger
  PhotonEfficiency
  MissingET
  NeutrinoFilter
  GenJetFinder
  GenMissingET
  FastJetFinder
  TreeWriter
}

module ParticlePropagator ParticlePropagator {
  set InputArray Delphes/stableParticles
  set OutputArray stableParticles
}

module SimpleCalorimeter ECal {
  set ParticleInputArray ParticlePropagator/stableParticles
  add EnergyFraction {0} {0.0}
  add EnergyFraction {11} {1.0}
  add EnergyFraction {22} {1.0}
  add EnergyFraction {12} {0.0}
  add EnergyFraction {1000022} {0.0}
}

module SimpleCalorimeter HCal {
  set ParticleInputArray ParticlePropagator/stableParticles
  add EnergyFraction {0} {1.0}
  add EnergyFraction {11} {0.0}
  add EnergyFraction {22} {0.0}
  add EnergyFraction {12} {0.0}
  add EnergyFraction {1000022} {0.0}
}

module Merger EFlowMerger {
  add InputArray ECal/eflowPhotons
  add InputArray HCal/eflowNeutralHadrons
  set OutputArray eflow
}

module Efficiency PhotonEfficiency {
  set InputArray ECal/eflowPhotons
  set EfficiencyFormula {0.95}
}

module Merger MissingET {
  add InputArray EFlowMerger/eflow
  set MomentumOutputArray momentum
}

module PdgCodeFilter NeutrinoFilter {
  set InputArray Delphes/stableParticles
  set OutputArray filteredParticles
  add PdgCode {12}
  add PdgCode {-12}
  add PdgCode {1000022}
  add PdgCode {-1000022}
}

module FastJetFinder GenJetFinder {
  set InputArray NeutrinoFilter/filteredParticles
  set OutputArray jets
}

module Merger GenMissingET {
  add InputArray NeutrinoFilter/filteredParticles
  set MomentumOutputArray momentum
}

module FastJetFinder FastJetFinder {
  set InputArray EFlowMerger/eflow
  set OutputArray jets
}

module TreeWriter TreeWriter {
  add Branch Delphes/allParticles Particle GenParticle
  add Branch FastJetFinder/jets Jet Jet
  add Branch GenJetFinder/jets GenJet Jet
  add Branch MissingET/momentum MissingET MissingET
  add Branch PhotonEfficiency/photons Photon Photon
}
"""

BANNER = """<LesHouchesEvents version="3.0">
<header>
<MGVersion>
#2.9.27
</MGVersion>
<MGProcCard>
import model {model}
{process}
output synthetic
</MGProcCard>
<MGRunCard>
  {ickkw} = ickkw
  {xqcut} = xqcut
  247000 = lhaid
  lhapdf = pdlabel
  -1 = dynamical_scale_choice
  6500.0 = ebeam1
  6500.0 = ebeam2
  {nevents} = nevents
</MGRunCard>
</header>
<init>
2212 2212 6.500000e+03 6.500000e+03 0 0 247000 247000 -4 1
{sigma:.6e} 1.000000e-03 {sigma:.6e} 1
<generator name='MadGraph5_aMC@NLO' version='2.9.27'>please cite 1405.0301 </generator>
</init>
"""


def write_lhe(path, *, n=12, sigma=0.25, model='MSSM_SLHA2', process='generate p p > n2 x1+', ickkw=0,
              xqcut=0.0, extra_partons=None, weights=None, nevents=None):
    """An LHE file with ``n`` events; ``extra_partons(i)`` gives the outgoing gluons of event i."""
    lines = [BANNER.format(model=model, process=process, ickkw=ickkw, xqcut=xqcut, sigma=sigma,
                           nevents=n if nevents is None else nevents)]
    for i in range(n):
        gluons = extra_partons(i) if extra_partons else 0
        w = weights[i] if weights else sigma
        rows = [' 2 -1 0 0 501 0 +0.0 +0.0 +100.0 100.0 0.0 0.0 9.0',
                ' -2 -1 0 0 0 501 -0.0 -0.0 -100.0 100.0 0.0 0.0 9.0',
                ' 1000023 1 1 2 0 0 +10.0 +5.0 +20.0 300.0 250.0 0.0 9.0',
                ' 1000024 1 1 2 0 0 -10.0 -5.0 -20.0 300.0 250.0 0.0 9.0']
        rows += [' 21 1 1 2 502 503 +5.0 +1.0 +3.0 6.0 0.0 0.0 9.0'] * gluons
        lines.append('<event>\n')
        lines.append(f' {len(rows)} 1 {w:+.7e} 1.0e+02 7.5e-03 1.1e-01\n')
        lines += [r + '\n' for r in rows]
        lines.append('</event>\n')
    lines.append('</LesHouchesEvents>\n')
    Path(path).write_text(''.join(lines))
    return Path(path)


SHOWER = r'''#!{python}
import json, os, sys, time
time.sleep(float(os.environ.get('RAVEL_TEST_STUB_SLEEP', '0')))
args = sys.argv[1:]
cfg, out, n = args[0], args[1], int(args[2])
acc = args[args.index('--accounting') + 1] if '--accounting' in args else None
djr = args[args.index('--djr') + 1] if '--djr' in args else None
settings = {{}}
for line in open(cfg):
    if '=' in line:
        k, v = line.split('=', 1)
        settings[k.strip()] = v.strip()
lhe, skip = settings['Beams:LHEF'], int(settings['Beams:nSkipLHEFatInit'])
events, current, init = [], None, []
in_init = False
for raw in open(lhe):
    line = raw.strip()
    if line == '<init>': in_init = True; continue
    if line == '</init>': in_init = False; continue
    if in_init: init.append(line); continue
    if line.startswith('<event'): current = []; continue
    if line.startswith('</event'):
        head = current[0].split()
        gluons = sum(1 for r in current[1:] if r.split()[0] == '21' and r.split()[1] == '1')
        events.append((float(head[2]), gluons)); current = None; continue
    if current is not None and line: current.append(line)
sigma_pb = float(init[1].split()[0])
chosen = events[skip:skip + n]
bsm = int(os.environ.get('RAVEL_TEST_STUB_BSM', '1000022'))
print(' |  |   P  P   Y Y     T    H   H   I    A A     This is PYTHIA version 8.312      |  | ')
accepted = []
for i, (w, g) in enumerate(chosen):
    if acc is not None and (skip + i) % 3 == 2:
        continue
    accepted.append((skip + i, w, g))
with open(out, 'w') as f:
    f.write('HepMC::Version 3.02.06\nHepMC::Asciiv3-START_EVENT_LISTING\nW Weight\n')
    for k, (number, w, g) in enumerate(accepted):
        f.write(f'E {{number}} 1 3\nU GEV MM\nW {{w:.10e}}\n')
        f.write('P 1 0 2212 0 0 6500 6500 0.938 4\n')
        f.write(f'P 2 1 {{bsm}} 1 2 30 300 250 1\n')
        f.write('P 3 1 11 5 5 5 9 0.000511 1\n')
    f.write('HepMC::Asciiv3-END_EVENT_LISTING\n')
fraction = len(accepted) / len(chosen)
if acc is not None:
    json.dump({{'schema_version': 1, 'program': 'stub', 'pythia_version': 8.312, 'attempted': len(chosen),
               'accepted': len(accepted), 'not_accepted': len(chosen) - len(accepted), 'end_of_file': False,
               'n_tried': len(chosen), 'n_selected': len(chosen), 'n_accepted': len(accepted),
               'sigma_gen_mb': sigma_pb * fraction * 1e-9, 'sigma_err_mb': 0.0}}, open(acc, 'w'))
    with open(djr, 'w') as f:
        f.write('# n_me_partons djr...\n')
        for number, w, g in accepted:
            f.write(f'{{g}} {{10 + number}} {{2 + number}}\n')
    print(f'pythia_shower_merged: attempted {{len(chosen)}}, accepted {{len(accepted)}}', file=sys.stderr)
else:
    print(f'pythia_shower: wrote {{len(accepted)}} events; sigma = {{sigma_pb * 1e-9:.6e}} mb', file=sys.stderr)
'''

DELPHES = r'''#!{python}
import os, sys
sys.path.insert(0, {tests!r})
from columnar_fixtures import random_events, write_delphes
from production_fixtures import write_empty_delphes
card, out, source = sys.argv[1:4]
assert open(card).read().count('ExecutionPath') >= 1
weights, numbers = [], []
for line in open(source):
    if line.startswith('E '):
        numbers.append(int(line.split()[1]))
    elif line.startswith('W ') and numbers:
        weights.append(float(line.split()[1]))
if os.environ.get('RAVEL_TEST_STUB_EMPTY'):
    write_empty_delphes(out)
    sys.exit(0)
events = random_events(len(weights), seed=sum(numbers) + len(weights))
for ev, w in zip(events, weights):
    ev['Weight'] = w
write_delphes(out, events)
print('** Delphes stub wrote', len(events), 'events')
'''

HADD = r'''#!{python}
import sys
sys.path.insert(0, {tests!r})
import awkward as ak
import numpy as np
import uproot
from columnar_fixtures import DELPHES_FIELDS
args = [a for a in sys.argv[1:] if a not in ('-f', '-k')]
target, sources = args[0], args[1:]
parts = []
for s in sources:
    t = uproot.open(s)['Delphes']
    data = {{name: ak.zip({{f: t[f'{{name}}.{{f}}'].array() for f in fields}}) for name, fields in DELPHES_FIELDS.items()}}
    data['MissingET'] = ak.zip({{'MET': t['MissingET.MET'].array(), 'Phi': t['MissingET.Phi'].array()}})
    data['Event'] = ak.zip({{'Weight': t['Event.Weight'].array(), 'Number': t['Event.Number'].array()}})
    parts.append(data)
merged = {{k: ak.concatenate([p[k] for p in parts]) for k in parts[0]}}
with uproot.recreate(target) as f:
    f.mktree('Delphes', {{k: v.type for k, v in merged.items()}},
             counter_name=lambda c: c + '_size', field_name=lambda o, i: o + '.' + i)
    f['Delphes'].extend(merged)
'''


def write_empty_delphes(path):
    """A Delphes-shaped file whose tree has every branch and no entries."""
    import awkward as ak
    import numpy as np
    import uproot
    from columnar_fixtures import DELPHES_FIELDS

    def empty(fields):
        return ak.zip({f: ak.unflatten(np.zeros(0, dtype=dt), np.zeros(0, dtype='i8')) for f, dt in fields.items()})
    data = {name: empty(fields) for name, fields in DELPHES_FIELDS.items()}
    data['MissingET'] = empty({'MET': 'f4', 'Phi': 'f4'})
    data['Event'] = empty({'Weight': 'f4', 'Number': 'i8'})
    with uproot.recreate(path) as f:
        f.mktree('Delphes', {k: v.type for k, v in data.items()},
                 counter_name=lambda c: c + '_size', field_name=lambda o, i: o + '.' + i)
    return Path(path)


def _script(path, text):
    path = Path(path)
    path.write_text(text.format(python=sys.executable, tests=str(HERE)))
    path.chmod(path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    return path


def stub_tools(directory):
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    return {'shower': {'path': str(_script(directory / 'pythia_shower', SHOWER)), 'version': '8.312'},
            'shower_merged': {'path': str(_script(directory / 'pythia_shower_merged', SHOWER)), 'version': '8.312'},
            'delphes': {'path': str(_script(directory / 'DelphesHepMC3', DELPHES)), 'version': '3.5.1'},
            'hadd': {'path': str(_script(directory / 'hadd', HADD)), 'version': '6.40.00'}}


def production_task(base, *, n=12, chunks=3, merged=False, cards=None, **lhe):
    base = Path(base)
    if merged:
        lhe.setdefault('ickkw', 1)
        lhe.setdefault('xqcut', 20.0)
        lhe.setdefault('extra_partons', lambda i: i % 3)
    write_lhe(base / 'events.lhe', n=n, **lhe)
    (base / 'card.tcl').write_text(SYNTHETIC_CARD)
    task = {'events': {'lhe': 'events.lhe'},
            'model': {'name': 'MSSM_SLHA2', 'invisible': [1000022]},
            'shower': {'seed': 101, 'commands': ['Tune:pp = 14', 'PartonLevel:MPI = on']},
            'detector': {'cards': cards or [{'name': 'synthetic', 'card': 'card.tcl', 'required_branches': ['Event.Weight', 'Jet.PT']}]},
            'normalization': {'sigma': 'lhe-init'},
            'chunks': chunks, 'tools': stub_tools(base / 'bin'),
            'resources': {'cpus_per_chunk': 1, 'memory_mib': 256, 'wall_seconds_per_chunk': 120}}
    if merged:
        task['shower']['merging'] = {'scheme': 'MLM', 'base_partons': 0, 'settings': {
            'JetMatching:merge': 'on', 'JetMatching:scheme': 1, 'JetMatching:setMad': 'off',
            'JetMatching:qCut': 30, 'JetMatching:nJetMax': 2, 'JetMatching:nQmatch': 5}}
    return task


def write_task(base, task):
    path = Path(base) / 'task.json'
    path.write_text(json.dumps(task, indent=2))
    return path
