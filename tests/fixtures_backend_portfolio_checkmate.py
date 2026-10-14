"""Source/admission and substituted-boundary controls; no native worker/process.

Fixture executable files are never launched. Only existing plan preparation and
adapter Python methods run; execute_native is a recording table stand-in.
"""
from copy import deepcopy
import json
from pathlib import Path

import pytest

from ravel import cli
from ravel.physics import backend_provider as p, checkmate_events as m
from ravel.workflow import science
from ravel.workflow.state_io import atomic_json, read_json
from fixtures_backend_portfolio_provider import catalogue, put


def pin(path):
    return {'path':str(path.resolve()),'sha256':p._sha(path)}


def event_text(weights):
    # E: event/MPI/scale/couplings/process/vertices/beams/randomcount/weights.
    return 'HepMC::Version 2.06.09\nHepMC::IO_GenEvent-START_EVENT_LISTING\n'+''.join(
        f'E {i} -1 1 0 0 0 0 0 0 0 0 1 {w}\n' for i,w in enumerate(weights))+'HepMC::IO_GenEvent-END_EVENT_LISTING\n'


def review():
    return {'schema_version':1,'policy':{'schema_version':1,
        'actors':{'proposer':'p','executor':'e','physics_critic':'c','skeptical_verifier':'v','physics_decider':'d'},
        'max_redos':0,'allowed_changed_paths':[],'allowed_stages':['science'],
        'required_checks':[{'id':'integrity','kind':'integrity'},{'id':'scientific','kind':'scientific'}],
        'claim_scopes':{'diagnostic':{'checks':['integrity'],'actions':['delivery','reuse']}}},
        'correction_contract':{'task_fields':[],'input_slots':[]}}


@pytest.fixture
def contract(tmp_path,catalogue):
    root=Path(catalogue['root'])
    # Synthetic template exercises exact substitution and frozen runtime routing;
    # it is not an upstream installation or a claimed scientific control.
    template='import sys\nsys.path.append("@runpath@")\nconfig_paths = dict()\n'+''.join(
        f"config_paths['{k}']='@{v}@'\n" for k,v in [('install_dir','prefix'),('remote','remote'),('source','sourcedir'),('data_dir','datadir')])
    put(root,'tools/python/CheckMATE.in',template)
    catalogue=p.checkmate_catalog(root)
    catalog=tmp_path/'catalogue.json'; atomic_json(catalog,catalogue)
    values={'runpath':str(root/'tools/python'),'prefix':str(root),'remote':'no','sourcedir':str(root),'datadir':str(root)}
    script=put(root,'bin/CheckMATE',template)
    script.write_text(__import__('re').sub(r'@([A-Za-z0-9_]+)@',lambda match:values[match[1]],template))
    python=put(tmp_path,'fake-python','#!/bin/sh\n# NOT EXECUTED\n'); python.chmod(0o700)
    fritz=put(root,'tools/fritz/bin/fritz','#!/bin/sh\n# NOT EXECUTED\n'); fritz.chmod(0o700)
    manifest=tmp_path/'runtime.json'
    atomic_json(manifest,{'schema_version':1,'kind':'checkmate-declared-runtime','revision':p.CM_REVISION,
        'python_sha256':p._sha(python),'entry_sha256':p._sha(script),'fritz_sha256':p._sha(fritz),
        'configured_values':values,'files':[pin(v) for v in sorted((root/'tools/python').glob('*.py'))],
        'scope':'Synthetic source-boundary fixture only; no actual runtime consumption.'})
    event=put(tmp_path,'events.hepmc',event_text([1,-.25,0]))
    request={'routine':'checkmate:atlas_0000_00032','events':pin(event),'format':'hepmc2','max_events':3,
        'cross_section_fb':2.5,'cross_section_error_fb':.125,'random_seed':83091,'model':'simple','quantity':'region_table',
        'output_parent':str(tmp_path/'native'),'name':'fixture','weight_convention':'Exactly one finite signed nominal weight per event, no clipping.',
        'runtime':{'executable':pin(script),'fritz':pin(fritz),'manifest':pin(manifest)}}
    request_path=tmp_path/'request.json'; atomic_json(request_path,request)
    config=tmp_path/'config.json'
    c={'schema_version':1,'purpose':'configured-runtime-control','catalogue':pin(catalog),'request':pin(request_path),
       'python':pin(python),'runtime_manifest':pin(manifest),'prior_qualification':None,'max_seconds':60,
       'max_ram_mib':1024,'source':'Synthetic configured-backend contract; no processing or physics qualification.'}
    atomic_json(config,c)
    return {'task':{'config':str(config)},'config':c,'request':request,'catalogue':catalogue,
            'root':root,'base':tmp_path,'manifest':manifest,'script':script,'event':event}
