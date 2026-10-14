"""Local candidate for literal Athena histogram SF semantics, not detector efficiency.

Consumes an explicitly bound, decoded primary object. It never opens ROOT, installs
software, guesses a release, converts an SF into efficiency or composes event weights.
Production admission requires external validation of the binding and native parity.
"""
import math
import hashlib,json,re
from pathlib import Path
from dataclasses import dataclass
from types import MappingProxyType
from .kernels import th2_value, relative_variation
from .formulas import evaluate_tf1

def _strict_json(raw):
    def unique(pairs):
        out={}
        for key,value in pairs:
            if key in out:raise ValueError('Duplicate decoded JSON field')
            out[key]=value
        return out
    def invalid_constant(value):raise ValueError('Nonfinite decoded JSON number: '+value)
    return json.loads(raw,object_pairs_hook=unique,parse_constant=invalid_constant)

def decoded_payload_digest(payload):
    return hashlib.sha256(json.dumps(payload,sort_keys=True,separators=(',',':'),allow_nan=False).encode()).hexdigest()

def load_verified_payload(decoded_path,decoded_file_sha256,root_path,root_sha256):
    """Byte-bound decoded artifact and independent original ROOT custody."""
    path=Path(decoded_path);raw=path.read_bytes()
    if hashlib.sha256(raw).hexdigest()!=decoded_file_sha256:raise ValueError('Decoded artifact byte digest differs')
    root=Path(root_path).resolve()
    if hashlib.sha256(root.read_bytes()).hexdigest()!=root_sha256:raise ValueError('Original ROOT custody differs')
    rows=[p for p in _strict_json(raw)['payloads'] if p['path']==str(root) and p['sha256']==root_sha256]
    if len(rows)!=1:raise ValueError('Exact primary payload must resolve once in decoded artifact')
    return rows[0]

def _freeze(value):
    if isinstance(value,dict):return MappingProxyType({k:_freeze(v) for k,v in value.items()})
    if isinstance(value,list):return tuple(_freeze(v) for v in value)
    return value

@dataclass(frozen=True)
class CompiledPayload:
    """Immutable indexed tables, checked once against reviewed content digest.

    No object-identity cache. Nested maps are read-only and arrays are tuples.
    Use load_compiled_payload to establish both original and decoded byte custody.
    """
    decoded_digest:str
    source_root_sha256:str
    _data:object
    object_index:object
    def __getitem__(self,key):return self._data[key]

    @classmethod
    def compile(cls,payload,expected_root_sha256,expected_decoded_digest):
        actual=decoded_payload_digest(payload)
        if actual!=expected_decoded_digest or payload['sha256']!=expected_root_sha256:
            raise ValueError('Immutable table construction custody differs')
        frozen=_freeze(payload);index={obj['key']:obj for obj in frozen['objects']}
        if len(index)!=len(frozen['objects']):raise ValueError('Duplicate exact object key/cycle')
        return cls(actual,expected_root_sha256,frozen,MappingProxyType(index))

def load_compiled_payload(decoded_path,decoded_file_sha256,root_path,root_sha256,expected_decoded_digest):
    raw=load_verified_payload(decoded_path,decoded_file_sha256,root_path,root_sha256)
    return CompiledPayload.compile(raw,root_sha256,expected_decoded_digest)

KNOWN_TRUTH={'had_tau','electron','muon','jet'}

def _coordinate(label,event):
    # Literal HelperFunctions and CommonEfficiencyTool routing at pinned commit.
    route={'final_pt':'pt_final_calib_gev','final_eta':'eta_final_calib',
           'final_abs_eta':'eta_final_calib','final_p':'p_final_calib_gev',
           'track_eta':'lead_track_eta','mu':'average_interactions',
           'truth_pt':'truth_pt_gev','truth_abs_eta_literal':'truth_eta',
           'truth_decay_mode':'truth_decay_mode'}
    if label not in route or route[label] not in event:
        raise ValueError('Missing literal source coordinate: '+label)
    value=event[route[label]]
    if type(value) not in (int,float) or not math.isfinite(value):
        raise ValueError('Finite source coordinate required')
    return abs(value) if label=='final_abs_eta' else value

def _object(payload,key):
    objects=([payload.object_index[key]] if key in payload.object_index else []) if isinstance(payload,CompiledPayload) else [x for x in payload['objects'] if x['key']==key]
    if len(objects)!=1:raise ValueError('Exact ROOT key and cycle must resolve once')
    obj=objects[0]
    if obj['class']=='TF1' and 'function' in obj:return obj
    if obj['class'] not in ('TH2F','TH2D'):
        raise ValueError('Unsupported ROOT function/class; no SF fallback')
    if len(obj['edges'])!=2:raise ValueError('Expected literal two-axis object')
    return obj

def _value(payload,key,binding,event):
    obj=_object(payload,key)
    if obj['class']=='TF1':return evaluate_tf1(obj['function'],_coordinate(binding['x_coordinate'],event))
    return th2_value(_coordinate(binding['x_coordinate'],event),
                     _coordinate(binding['y_coordinate'],event),
                     obj['edges'][0],obj['edges'][1],obj['values_without_flow'])

def evaluate_marginal_sf(binding,payload,event,nuisance=None,direction=None):
    """Return one marginal correction and declared provenance, never event response.

    Explicit configuration must bind truth category, nested WP, prong keys, exact
    ROOT cycles, source coordinate routing and nuisance-to-object mapping. Histogram
    key presence is not an analysis-match certificate. Unknown truth is an error.
    """
    if binding.get('quantity')!='marginal_data_over_mc_sf':
        raise ValueError('This candidate only evaluates marginal SF quantities')
    if type(binding.get('three_prong_unity')) is not bool:raise ValueError('Explicit boolean source prong policy required')
    if not all(isinstance(binding.get(k),str) and re.fullmatch('[0-9a-f]{64}',binding[k]) for k in ['payload_sha256','decoded_payload_sha256']):
        raise ValueError('Explicit ROOT and decoded-content SHA256 bindings required')
    actual_content_digest=payload.decoded_digest if isinstance(payload,CompiledPayload) else decoded_payload_digest(payload)
    if actual_content_digest!=binding['decoded_payload_sha256']:
        raise ValueError('Decoded numerical content differs despite possible unchanged ROOT hash label')
    if payload['sha256']!=binding['payload_sha256']:
        raise ValueError('Decoded payload custody differs from explicit binding')
    truth=event.get('truth_category')
    if truth not in KNOWN_TRUTH or binding['expected_truth'] not in KNOWN_TRUTH:
        raise ValueError('Missing or unsupported truth match; never unity by ignorance')
    if nuisance is None and direction is not None or nuisance is not None and (type(direction) is not int or direction not in (-1,1)):
        raise ValueError('Variation requires exact nuisance and coherent direction')
    if nuisance is not None and nuisance not in binding['nuisances']:
        raise ValueError('Unmapped required source nuisance; never silent nominal')
    if type(event.get('prongs')) is not int or event.get('prongs') not in (1,3):raise ValueError('Source one/three-prong identity required')
    # Source-defined category mismatch is distinct from an unknown truth record.
    if truth!=binding['expected_truth'] or (event['prongs']==3 and binding['three_prong_unity']):
        value=1.
        reason='known truth mismatch' if truth!=binding['expected_truth'] else 'source three-prong unity'
    else:
        prong=str(event['prongs']);keys=binding['keys_by_prong'].get(prong)
        if not keys:raise ValueError('Missing source prong calibration')
        value=_value(payload,keys['nominal'],binding,event)
        if nuisance is not None:
            entries=binding['nuisances'][nuisance].get(prong)
            if not entries:raise ValueError('Missing nuisance response for admitted prong')
            magnitudes=[]
            for entry in entries:
                parameter=entry['parameter']
                if type(parameter) not in (int,float) or not math.isfinite(parameter) or parameter<0:
                    raise ValueError('Coherent finite nonnegative source sigma magnitude required')
                key=entry['up_key' if direction>0 else 'down_key']
                magnitudes.append(_value(payload,key,binding,event)*parameter)
            value=relative_variation(value,magnitudes,direction)
        reason='literal histogram correction'
    if not math.isfinite(value) or value<0:raise ValueError('Invalid calibrated correction')
    return {'value':value,'quantity':'marginal_data_over_mc_sf','reason':reason,
            'payload_sha256':payload['sha256'],'decoded_payload_sha256':binding['decoded_payload_sha256'],'binding_id':binding['binding_id'],
            'nuisance':nuisance,'direction':direction,
            'claim':'candidate scalar evaluation only; analysis match and joint event response unvalidated'}
