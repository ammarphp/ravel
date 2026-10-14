"""Explicit synthetic slim-object fixtures for the native upstream ROOT ABI.

Preparation rounds supplied values to their native storage widths and writes a
reviewable PyROOT job. It never simulates detector response or runs ROOT itself.
"""
from __future__ import annotations

import math
from pathlib import Path
import struct

from ravel.physics.simpleanalysis_adapter import native_slim_schema,weight_selection
from ravel.workflow.state_io import atomic_json

PREFIXES=('el','mu','tau','ph','jet','fatjet','trackjet','bhadron','HSTruth')


def _int32(value):
    if type(value) is not int or not -(2**31) <= value < 2**31:
        raise ValueError('exact signed32bit synthetic input integer required')
    return value


def _float32(value):
    if isinstance(value,bool) or not isinstance(value,(int,float)):
        raise ValueError('finite synthetic input scalar required')
    try:
        if not math.isfinite(value):
            raise ValueError('finite synthetic input scalar required')
        stored=struct.unpack('<f',struct.pack('<f',value))[0]
    except (OverflowError,struct.error) as exc:
        raise ValueError('synthetic input overflows native Float_t') from exc
    if not math.isfinite(stored):
        raise ValueError('synthetic input overflows native Float_t')
    return stored


def structural_events(events, *, weight_names=None):
    """Bind every scalar/vector explicitly before any ROOT job is approved."""
    schema=native_slim_schema()
    if not isinstance(events,list) or not 1 <= len(events) <= 64:
        raise ValueError('one to64 explicitly supplied structural object events required')
    result=[];seen=set()
    multiple=weight_names is not None
    names=weight_selection({'weight_names':weight_names if multiple else ['nominal']},'nominal')['names']
    for event in events:
        if not isinstance(event,dict) or set(event)!=({'scalars','weights','objects'} if multiple else {'scalars','weight','objects'}):
            raise ValueError('structural event needs explicit scalars, weight and objects')
        scalars=event['scalars']
        expected={name for name,kind in schema.items() if 'vector' not in kind}
        if not isinstance(scalars,dict) or set(scalars)!=expected:
            raise ValueError('complete native scalar input denominator required')
        row={name:(_int32(scalars[name]) if schema[name]=='int32_t' else _float32(scalars[name])) for name in expected}
        if row['Event'] in seen:
            raise ValueError('duplicate independent synthetic event identifier')
        seen.add(row['Event'])
        weights=event['weights'] if multiple else [event['weight']]
        if not isinstance(weights,list) or len(weights)!=len(names):
            raise ValueError('complete explicit named MC-weight vector required')
        row['mcWeights']=[_float32(weight) for weight in weights]
        if any(weight==0 for weight in row['mcWeights']):
            raise ValueError('weight is zero after native Float_t serialization')
        objects=event['objects']
        if not isinstance(objects,dict) or set(objects)!=set(PREFIXES):
            raise ValueError('all nine native object collections must be supplied explicitly')
        for prefix in PREFIXES:
            fields={name[len(prefix)+1:]:kind for name,kind in schema.items() if name.startswith(prefix+'_')}
            if not isinstance(objects[prefix],list):
                raise ValueError('object collection must be a list')
            for field in fields:row[prefix+'_'+field]=[]
            for obj in objects[prefix]:
                if not isinstance(obj,dict) or set(obj)!=set(fields):
                    raise ValueError('complete native object field denominator required: '+prefix)
                for field,kind in fields.items():
                    value=_int32(obj[field]) if kind=='std::vector<int>' else _float32(obj[field])
                    if field in ('pt','m') and value<0:
                        raise ValueError('native structural momentum/mass must be nonnegative')
                    row[prefix+'_'+field].append(value)
        if row['met_pt']<0 or row['sumet']<0:
            raise ValueError('native structural MET/sumet must be nonnegative')
        result.append(row)
    if any(math.fsum(row['mcWeights'][index] for row in result)<=0 for index in range(len(names))):
        raise ValueError('native structural witness needs positive signed all-event normalization')
    return result


# Python2.7 compatible for the qualified AnalysisBase21.2 image. Keeping live
# references to every vector is required by old PyROOT's branch ownership ABI.
PYROOT_WRITER = '''import array,json,sys
import ROOT
document=json.load(open(sys.argv[1]));schema=document['schema'];events=document['events']
output=ROOT.TFile(sys.argv[2],'RECREATE')
if output.IsZombie():raise RuntimeError('cannot create slim ROOT')
tree=ROOT.TTree('ntuple','explicit synthetic structural slim objects')
buffers={}
for name,kind in sorted(schema.items()):
 if kind in ('int32_t','float'):
  buffer=array.array('i' if kind=='int32_t' else 'f',[0])
  if buffer.itemsize!=4:raise RuntimeError('native scalar storage width differs')
  tree.Branch(name,buffer,name+('/I' if kind=='int32_t' else '/F'))
 else:
  buffer=ROOT.std.vector('int' if kind=='std::vector<int>' else 'float')()
  tree.Branch(name,buffer)
 buffers[name]=buffer
for event in events:
 for name,kind in sorted(schema.items()):
  buffer=buffers[name]
  if kind in ('int32_t','float'):buffer[0]=event[name]
  else:
   buffer.clear()
   for value in event[name]:buffer.push_back(value)
 tree.Fill()
tree.Write();output.Close()
print('STRUCTURAL_SLIM_ROOT_WRITTEN events='+str(len(events))+' branches='+str(len(schema)))
'''


def prepare_writer(events, directory, *, weight_names=None):
    """Create a source-bound writer job, without importing or executing ROOT."""
    rows=structural_events(events,weight_names=weight_names)
    directory=Path(directory)
    if directory.exists():
        raise ValueError('preserve previous structural input preparation')
    directory.mkdir(parents=True)
    atomic_json(directory/'events.json',{'schema_version':1,'level':'synthetic_structural','schema':native_slim_schema(),
        'events':rows,'weight_names':weight_names if weight_names is not None else ['nominal'],
        'physics_validated':False,'generator_validated':False,'detector_validated':False,
        'serialization':'Explicit supplied values rounded prospectively to native Int_t/Float_t/std::vector widths'})
    (directory/'write_slim.py').write_text(PYROOT_WRITER)
    return {'events':len(rows),'branches':len(native_slim_schema()),'sumw':math.fsum(row['mcWeights'][0] for row in rows),
            'native_execution':False,'physics_validated':False}
