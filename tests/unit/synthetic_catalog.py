"""A synthetic upstream Rivet and SimpleAnalysis checkout and the catalogue built from it.

Every routine, code and reference is fictional (years 9xxx, arXiv-shaped ids 0000.nnnnn).
"""
import synthetic_identifiers as syn
import json
import os
from pathlib import Path
import subprocess

from ravel.workflow import analysis_catalog_build

RIVET = {
    'analyses/pluginATLAS/ATLAS_9001_I0001.info': (
        ('Name: ATLAS_9001_I0001\nYear: 9001\nSummary: Search for a fictional heavy partner in jets\n' + 'Experiment: ATLAS\nCollider: LHC\nInspireID: 0001\nStatus: VALIDATED\n' + ('References:\n - arXiv:' + syn.arxiv(1) + '\n - ATLAS-FAKE-9001-01\nKeywords:\n - search\nBeams: [p+, p+]\n'))),
    'analyses/pluginATLAS/ATLAS_9001_I0001.cc': 'class X { void init() { declare(SmearedJets()); } };\n',
    'analyses/pluginATLAS/ATLAS_9001_I0001.yoda': 'BEGIN YODA\nEND YODA\n',
    'analyses/pluginATLAS/ATLAS_9001_I0001.plot': '# plot\n',
    'analyses/pluginATLAS/ATLAS_9002_I0002.info': (
        'Name: ATLAS_9002_I0002\nSummary: Fictional jet shapes in lead-lead collisions\nExperiment: ATLAS\n'
        'Collider: LHC\nInspireID: 0002\nStatus: UNVALIDATED\nBeams: [Pb, Pb]\n'),
    'analyses/pluginATLAS/ATLAS_9002_I0002.cc': 'class Y { CentralityProjection c; };\n',
    'analyses/pluginCMS/CMS_9003_I0003.info': (
        ('Name: CMS_9003_I0003\nSummary: Fictional inclusive spectrum\nExperiment: ATLAS\nCollider: LHC\n' + ('InspireID: 0003\nStatus: VALIDATED\nReferences:\n - arXiv:' + syn.arxiv(3) + '\n'))),
    'analyses/pluginCMS/CMS_9003_I0003.cc': 'class Z {};\n',
    'analyses/pluginCMS/CMS_9004_I0004.info': (
        'Name: CMS_9004_I0004\nSummary: Fictional displaced vertex search\nExperiment: CMS\nCollider: LHC\n'
        'InspireID: 0004\nStatus: VALIDATED\n'),
    'analyses/pluginMC/MC_FAKE.info': 'Name: MC_FAKE\nSummary: generic validation\n',
    'analyses/pluginMC/MC_FAKE.cc': 'class M {};\n',
}
SIMPLEANALYSIS = {
    'SimpleAnalysisCodes/src/ANA-FAKE-9005-01.cxx': (
        '#include "RestFrames/RestFrames.hh"\nDefineAnalysis(FakeSearchA)\n'
        'void FakeSearchA::Init() { LabRecoFrame* LAB; addONNX("m", "model.onnx"); }\n'),
    'SimpleAnalysisCodes/src/ANA-FAKE-9006-01.cxx': 'DefineAnalysis(FakeSearchB)\nDefineAnalysis(FakeSearchBTight)\n',
    'SimpleAnalysisCodes/data/model.onnx': 'onnx bytes\n',
}


def _git(root, *args):
    env = {**os.environ, 'GIT_CONFIG_NOSYSTEM': '1', 'GIT_CONFIG_GLOBAL': os.devnull,
           'GIT_AUTHOR_NAME': 't', 'GIT_AUTHOR_EMAIL': 't@example.invalid',
           'GIT_COMMITTER_NAME': 't', 'GIT_COMMITTER_EMAIL': 't@example.invalid'}
    return subprocess.run(['git', '-C', str(root), *args], env=env, check=True, capture_output=True,
                           text=True).stdout.strip()


def checkout(root, files):
    root = Path(root)
    root.mkdir(parents=True)
    _git(root, 'init', '-q')
    for relative, text in files.items():
        (root / relative).parent.mkdir(parents=True, exist_ok=True)
        (root / relative).write_text(text)
    _git(root, 'add', '-A')
    _git(root, 'commit', '-qm', 'synthetic upstream')
    return root


def build(tmp_path, models=True):
    """(catalogue path, catalogue) for the synthetic checkouts under ``tmp_path``."""
    rivet = checkout(tmp_path / 'rivet', RIVET)
    sa = checkout(tmp_path / 'simpleanalysis', SIMPLEANALYSIS)
    model_path = None
    if models:
        model_path = tmp_path / 'models.json'
        model_path.write_text(json.dumps([{'link': 'https://example.invalid/FAKE-9005-01',
                                           'hepdata': 'https://www.hepdata.net/record/ins9?'}]))
    out = tmp_path / 'catalogue' / 'analysis-catalog.json'
    assert analysis_catalog_build.main(['--rivet', str(rivet), '--simpleanalysis', str(sa), '--out', str(out),
                                        '--retrieved-at', '9001-01-01']
                                       + (['--models', str(model_path)] if model_path else [])) == 0
    return out, json.loads(out.read_text())
