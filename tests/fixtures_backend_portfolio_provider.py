"""Portable source controls; no upstream imports or scientific execution."""
import ast
import base64
import configparser
from copy import deepcopy
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace
import zlib

import pytest

from ravel.physics import backend_provider as m


def put(root, path, text):
    p = root / path; p.parent.mkdir(parents=True, exist_ok=True); p.write_text(text); return p


@pytest.fixture
def catalogue(tmp_path):
    root = tmp_path / 'source'
    for path in m.CM_ENGINE:
        put(root, path, '# engineering fixture\n')
    put(root, 'tools/python/info.py', 'class Info:\n    @classmethod\n    def init(cls):\n        cls.analysis_groups = {"ATLAS_13TeV"}\n')
    put(root, 'data/analysis_info/ATLAS_13TeV_analyses.txt', '#disabled 8\natlas_0000_00032 2 fixture\n')
    meta = {'analysis': 'atlas_0000_00032', 'experiment': 'atlas13tev', 'ecm': '13',
            'lumi': '139', 'signal_regions': ['SR1', 'SR2'], 'expectation_known': 'y',
            'likelihoods': 'y', 'mb_signal_regions': {'pair': ['SR1', 'SR2']}}
    put(root, 'data/analysis_info/ATLAS_13TeV/atlas_0000_00032_var.j', json.dumps(meta))
    for path in ['data/analysis_info/ATLAS_13TeV/atlas_0000_00032_ref.dat',
                 'tools/analysis/src/analyses/ATLAS_13TeV/atlas_0000_00032.cc',
                 'tools/analysis/include/analyses/ATLAS_13TeV/atlas_0000_00032.h',
                 'data/cards/delphes_skimmed_ATLAS_13TeV.tcl']:
        put(root, path, 'fixture source\n')
    put(root, 'data/atlas_0000_00032/pyhf_conf.json', json.dumps({'analysis': [
        {'name': 'pair', 'bkgonly': 'background.json', 'patchset': 'patch.json'}]}))
    put(root, 'data/atlas_0000_00032/Likelihoods/background.json', '{}')
    put(root, 'data/atlas_0000_00032/Likelihoods/patch.json', '{}')
    return m.checkmate_catalog(root)
