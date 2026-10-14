"""Prospective read-only Delphes Event/GenParticle exposure check.

ROOT is imported only by main at an independently admitted future native call.
validate is portable and compares supplied observations, not a runtime claim.
"""
from __future__ import annotations
import json
import math
from pathlib import Path
import struct
import sys

def f32(value):
    try:x=struct.unpack('f',struct.pack('f',float(value)))[0]
    except (OverflowError,ValueError) as error:raise ValueError('nonfinite Float_t projection') from error
    if not math.isfinite(x):raise ValueError('nonfinite Float_t projection')
    return x

def expected(legacy_events):
    rows=[]
    for e in legacy_events:
        particles=[]
        # read_legacy retains wire insertion order; ROOT's allParticles branch
        # preserves that reader order. This is not the skimmed Particle branch.
        for p in e['particles'].values():
            pos=e['vertices'][p['production']]['position'] if p['production'] else ['0']*4
            particles.append({'pdg':p['pdg'],'status':p['status'],'p4':[f32(x) for x in p['p4']],
                'mass':f32(p['mass']),'position':[f32(x) for x in pos[:3]]+[f32(float(pos[3])*1e-3/2.99792458e8)]})
        rows.append({'event':e['event'],'weight':f32(e['weights'][0]),'particles':particles})
    return rows

def validate(observation,legacy_events):
    if not isinstance(observation,dict) or set(observation)!={'kind','rows','root_version','library_load_request','dictionary_types'}:
        raise ValueError('complete bound reader observation required')
    required={'GenParticle.PID':'Int_t','GenParticle.Status':'Int_t',
              **{'GenParticle.'+k:'Float_t' for k in ('Px','Py','Pz','E','Mass','X','Y','Z','T')},
              'HepMCEvent.Weight':'Float_t','Event.Number':'Long64_t'}
    if observation['dictionary_types']!=required:raise ValueError('loaded Delphes dictionary differs from declared source types')
    if not isinstance(observation['rows'],list):raise ValueError('complete observation rows required')
    for row in observation['rows']:
        if not isinstance(row,dict) or set(row)!={'event','weight','particles'} or type(row['event']) is not int or type(row['weight']) is not float or not math.isfinite(row['weight']) or not isinstance(row['particles'],list):
            raise ValueError('typed finite complete event row required')
        for p in row['particles']:
            if (not isinstance(p,dict) or set(p)!={'pdg','status','p4','mass','position'} or
                type(p['pdg']) is not int or type(p['status']) is not int or
                not isinstance(p['p4'],list) or len(p['p4'])!=4 or not isinstance(p['position'],list) or len(p['position'])!=4 or
                not all(type(x) is float and math.isfinite(x) for x in p['p4']+p['position']+[p['mass']])):
                raise ValueError('typed finite full particle row required')
    if observation['kind']!='delphes-persisted-original-event-census' or observation['rows']!=expected(legacy_events):
        raise ValueError('complete native event/particle/weight/geometry census differs from source Float_t projection')
    return {'events':len(observation['rows']),'particles':sum(len(x['particles']) for x in observation['rows']),
        'persisted_float32_weight_sum':math.fsum(x['weight'] for x in observation['rows']),
        'persisted_float32_weight_squared_sum':math.fsum(x['weight']**2 for x in observation['rows']),
        'comparison':'Exact IEEE Float_t projection, not a fitted tolerance or physics calibration',
        'scope':'Persisted Event and full GenParticle branches only; native selection/analysis weight use, mother interval approximation and detector fidelity unqualified.'}

def observe(rootfile,library):
    # This method is NOT run by portable source controls. It is the entire
    # prospective SDK operation and stays behind ordinary native admission.
    import ROOT
    if ROOT.gSystem.Load(str(library))<0:raise ValueError('bound Delphes library load refused')
    required={'GenParticle.PID':'Int_t','GenParticle.Status':'Int_t',
              **{'GenParticle.'+k:'Float_t' for k in ('Px','Py','Pz','E','Mass','X','Y','Z','T')},
              'HepMCEvent.Weight':'Float_t','Event.Number':'Long64_t'}
    types={}
    for key in required:
        cls,member=key.split('.'); c=ROOT.TClass.GetClass(cls)
        if not c:raise ValueError('required loaded Delphes class missing')
        m=c.GetDataMember(member)
        if not m:raise ValueError('required loaded Delphes field missing')
        raw=str(m.GetTypeName())
        types[key]={'float':'Float_t','int':'Int_t','long long':'Long64_t','long long int':'Long64_t'}.get(raw,raw)
    f=ROOT.TFile.Open(str(rootfile),'READ')
    if not f or f.IsZombie():raise ValueError('native Delphes ROOT output unavailable')
    try:
        tree=f.Get('Delphes')
        if not tree or not tree.GetBranch('Event') or not tree.GetBranch('GenParticle'):
            raise ValueError('complete Event/GenParticle branches missing; skimmed Particle is insufficient')
        rows=[]
        for i in range(int(tree.GetEntries())):
            if i>=1000:raise ValueError('native exposure exceeds first-route ceiling')
            if tree.GetEntry(i)<=0 or tree.Event.GetEntries()!=1:raise ValueError('incomplete native event readback')
            event=tree.Event.At(0);ps=[]
            for p in tree.GenParticle:
                ps.append({'pdg':int(p.PID),'status':int(p.Status),
                  'p4':[float(p.Px),float(p.Py),float(p.Pz),float(p.E)],'mass':float(p.Mass),
                  'position':[float(p.X),float(p.Y),float(p.Z),float(p.T)]})
            rows.append({'event':int(event.Number),'weight':float(event.Weight),'particles':ps})
        return {'kind':'delphes-persisted-original-event-census','rows':rows,'root_version':str(ROOT.gROOT.GetVersion()),
            'library_load_request':str(Path(library).resolve()),'dictionary_types':types}
    finally:f.Close()

def main(argv=None):
    import argparse
    # Direct bound file invocation uses this exact package source, not an
    # accidentally installed ravel package under the native interpreter.
    sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
    from ravel.physics import hepmc_legacy_conversion as conversion
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--conversion',required=True);p.add_argument('--directory',required=True)
    p.add_argument('--library',required=True);p.add_argument('--library-sha256',required=True);p.add_argument('--out',required=True)
    a=p.parse_args(argv);contract=conversion.verify_manifest(a.conversion)
    if conversion.sha(a.library)!=a.library_sha256:raise ValueError('declared Delphes library changed')
    files=sorted(Path(a.directory).glob('*.root'))
    if len(files)!=1 or files[0].is_symlink():raise ValueError('exactly one regular supplied-event Delphes file required')
    observation=observe(files[0],a.library)
    result={'status':'passed','comparison':validate(observation,conversion.read_legacy(contract['event_output']['path'])),
      'observation':observation,'rootfile':{'path':str(files[0].resolve()),'sha256':conversion.sha(files[0])},
      'library':{'path':str(Path(a.library).resolve()),'sha256':a.library_sha256},
      'conversion':{'path':str(Path(a.conversion).resolve()),'sha256':conversion.sha(a.conversion)},
      'physics_validated':False,'complete_loaded_closure_verified':False}
    if conversion.sha(a.library)!=a.library_sha256:raise ValueError('Delphes library changed during readback')
    out=Path(a.out)
    if out.exists():raise FileExistsError(out)
    out.write_text(json.dumps(result,indent=2,allow_nan=False)+'\n');return 0

if __name__=='__main__':raise SystemExit(main())
