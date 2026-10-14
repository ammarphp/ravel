"""Byte-bound literal Athena corrections and supplied joint categorical weights.

Runtime is standard-library only. No ROOT execution or efficiency inference.
"""
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
import hashlib, json, math, re
from ._scalar import (load_compiled_payload, evaluate_marginal_sf, _freeze,
                      _object, _coordinate, KNOWN_TRUTH)
from .kernels import joint_selection_scale_factor

ATHENA_COMMIT = '0c2e91577f7832d6dc527b00f61f7e03db46064b'
SHARED_FILES_VERSION = '00-03-16'
EMPTY_WP_CONFIGURATION_SHA256 = '945943d81806b4fb45128917d6f19eb6dcf96aae857f8408ffcb5883bafe3b65'
_SHA = re.compile(r'[0-9a-f]{64}')

def _json(raw):
    def unique(pairs):
        out={}
        for key,value in pairs:
            if key in out: raise ValueError('Duplicate JSON field/outcome')
            out[key]=value
        return out
    def invalid_constant(value): raise ValueError('Nonfinite JSON number: '+value)
    return json.loads(raw,object_pairs_hook=unique,parse_constant=invalid_constant)

def _sha(value):
    if type(value) is not str or not _SHA.fullmatch(value):
        raise ValueError('Exact lowercase SHA256 required')
    return value

def _text(value):
    if type(value) is not str or not value.strip():
        raise ValueError('Explicit nonempty namespace required')
    return value

@dataclass(frozen=True)
class ArtifactPin:
    path: str
    sha256: str
    def __post_init__(self):
        _text(self.path); _sha(self.sha256)
    def read(self):
        raw = Path(self.path).read_bytes()
        if hashlib.sha256(raw).hexdigest() != self.sha256:
            raise ValueError('Artifact bytes differ: ' + self.path)
        return raw

@dataclass(frozen=True)
class SourceDomain:
    """Exact declared context; matching it does not establish analysis calibration.

    Unknown analysis release/AFII/era must be named explicitly as unqualified.
    No inference from file names or code recommendations fills those inputs.
    """
    athena_commit: str
    shared_files_version: str
    configuration_namespace: str
    simulation_namespace: str
    era_namespace: str
    working_point: str
    empty_wp_tool: str | None = None
    def __post_init__(self):
        for name, value in self.__dict__.items():
            if name not in ('working_point', 'empty_wp_tool'): _text(value)
        if self.working_point == '':
            if self.empty_wp_tool not in ('RecoHadTauTool', 'EleOLRHadTauTool'):
                raise ValueError('Empty WP requires an explicit released native tool')
        else:
            _text(self.working_point)
            if self.empty_wp_tool is not None:
                raise ValueError('Empty-WP tool is not a nonempty-WP wildcard')
        if self.athena_commit != ATHENA_COMMIT or self.shared_files_version != SHARED_FILES_VERSION:
            raise ValueError('This implementation supports only the pinned source semantics')

@dataclass(frozen=True, init=False)
class CalibrationProvider:
    """Construct with load(); checked once, immutable indexed numerical content."""
    domain: SourceDomain
    binding_id: str
    binding_sha256: str
    _payload: object
    _binding: object

    @classmethod
    def load(cls, *, decoded: ArtifactPin, original_root: ArtifactPin,
             binding: ArtifactPin):
        spec = _json(binding.read())
        domain = SourceDomain(**spec['domain'])
        b = spec['correction']
        if type(b) is not dict or b.get('quantity') != 'marginal_data_over_mc_sf':
            raise ValueError('Marginal SF binding required')
        _text(b.get('binding_id')); _sha(b.get('payload_sha256')); _sha(b.get('decoded_payload_sha256'))
        if b['payload_sha256'] != original_root.sha256:
            raise ValueError('Binding and original ROOT pins differ')
        if type(b.get('three_prong_unity')) is not bool or b.get('expected_truth') not in KNOWN_TRUTH:
            raise ValueError('Strict source truth/prong policy required')
        payload = load_compiled_payload(decoded.path, decoded.sha256, original_root.path,
                                        original_root.sha256, b['decoded_payload_sha256'])
        names=[obj['name'] for obj in payload['objects']]
        if len(names)!=len(set(names)):
            raise ValueError('Ambiguous multiple ROOT cycles for one source object name')
        routing = payload['literal_coordinates']
        if b.get('x_coordinate') != routing['x'] or b.get('y_coordinate') != routing['y']:
            raise ValueError('Binding axes differ from literal source metadata routing')
        # File truth namespace must agree with the explicitly configured source tool.
        name = Path(original_root.path).name
        tags = {'TrueHadTau': 'had_tau', 'TrueElectron': 'electron', 'TrueMuon': 'muon', 'TrueJet': 'jet'}
        matched = [truth for tag, truth in tags.items() if tag in name]
        if len(matched) != 1 or matched[0] != b['expected_truth']:
            raise ValueError('Primary filename truth namespace differs from binding')
        if domain.working_point == '':
            config = spec.get('native_configuration')
            if (type(config) is not dict or set(config) != {'tool', 'working_point', 'source'}
                    or config['tool'] != domain.empty_wp_tool or config['working_point'] != ''):
                raise ValueError('Exact native empty-WP configuration required')
            source = config['source']
            if type(source) is not dict or set(source) != {'path', 'sha256'} or source['sha256'] != EMPTY_WP_CONFIGURATION_SHA256:
                raise ValueError('Released native empty-WP configuration source required')
            ArtifactPin(**source).read()
            component = {'RecoHadTauTool': 'Reco', 'EleOLRHadTauTool': 'EleOLR'}[domain.empty_wp_tool]
            if not name.startswith(component + '_TrueHadTau_') or b['three_prong_unity'] != (component == 'EleOLR'):
                raise ValueError('Empty WP tool/file/truth/prong policy differs')
        keys = b.get('keys_by_prong'); nuisances = b.get('nuisances')
        if type(keys) is not dict or not keys or set(keys) - {'1', '3'} or type(nuisances) is not dict:
            raise ValueError('Explicit one/three-prong unsplit source mapping required')
        aliases = payload['source_efficiency_aliases']
        for prong, row in keys.items():
            if type(row) is not dict or set(row) != {'nominal'}:
                raise ValueError('Nominal key required without unhandled source modes')
            obj = _object(payload, row['nominal'])
            prefix = 'sf_' + domain.working_point if domain.working_point else 'sf'
            if obj['name'] != f'{prefix}_{prong}p':
                raise ValueError('Nominal source WP/prong differs from binding')
        for nuisance, prongs in nuisances.items():
            _text(nuisance)
            if type(prongs) is not dict or set(prongs) != set(keys):
                raise ValueError('Each admitted nuisance requires every admitted prong')
            for prong, entries in prongs.items():
                if type(entries) is not list or not entries:
                    raise ValueError('Explicit coherent nuisance entries required')
                for entry in entries:
                    if type(entry) is not dict or set(entry) != {'up_key','down_key','up_alias','down_alias','parameter'}:
                        raise ValueError('Exact asymmetric keys and source aliases required')
                    if type(entry['parameter']) not in (int,float) or not math.isfinite(entry['parameter']) or entry['parameter'] < 0:
                        raise ValueError('Finite nonnegative sigma magnitude required')
                    for direction in ('up','down'):
                        alias = entry[direction+'_alias']; key = entry[direction+'_key']
                        suffix = f'_{direction}' + (f'_{domain.working_point}' if domain.working_point else '') + f'_{prong}p'
                        if not isinstance(alias,str) or not alias.endswith(suffix):
                            raise ValueError('Source alias direction/WP/prong mismatch')
                        if alias not in aliases or aliases[alias]['key'] != key:
                            raise ValueError('Asymmetric source alias/key mapping differs')
                        _object(payload, key)
        self = object.__new__(cls)
        for key, value in dict(domain=domain,binding_id=b['binding_id'],binding_sha256=binding.sha256,
                               _payload=payload,_binding=_freeze(b)).items():
            object.__setattr__(self,key,value)
        return self

    def evaluate(self, event, *, context: SourceDomain, nuisance=None, direction=None):
        if type(context) is not SourceDomain or context != self.domain:
            raise ValueError('Exact source configuration/simulation/era/WP context required')
        result = evaluate_marginal_sf(self._binding,self._payload,event,nuisance,direction)
        result['binding_sha256'] = self.binding_sha256
        result['scope'] = 'literal marginal data/MC correction; no absolute efficiency or analysis-match admission'
        return MappingProxyType(result)

@dataclass(frozen=True, init=False)
class JointCategoricalResponse:
    """Declared absolute joint probabilities, never synthesized from marginal SFs.

    Input must include all mutually exclusive exhaustive outcomes at the same
    conditioning state in MC and data. Calibration evidence is retained, not
    independently certified by construction. Accepted category weights and
    selection ratios are alternatives; multiplying both double counts.
    """
    input_sha256: str
    evidence: ArtifactPin
    _contexts: object
    _cells: object

    @classmethod
    def load(cls, table: ArtifactPin, *, evidence: ArtifactPin):
        evidence.read()
        spec=_json(table.read())
        if spec.get('quantity') != 'absolute_joint_data_and_mc_probabilities' or spec.get('calibration_evidence_sha256') != evidence.sha256:
            raise ValueError('Explicit absolute joint calibration/evidence binding required')
        if spec.get('exhaustive_mutually_exclusive') is not True:
            raise ValueError('Exhaustive mutually exclusive outcomes must be explicitly declared')
        contexts=spec.get('conditioning_fields'); cells=spec.get('cells')
        if type(contexts) is not list or not contexts or any(type(x) is not str or not x for x in contexts) or len(set(contexts)) != len(contexts):
            raise ValueError('Unique explicit conditioning fields required')
        if type(cells) is not list or not cells: raise ValueError('Calibrated cells required')
        index={}
        for cell in cells:
            context=cell.get('context'); mc=cell.get('mc'); data=cell.get('data')
            if type(context) is not dict or set(context) != set(contexts) or any(type(x) is not str or not x for x in context.values()):
                raise ValueError('Every calibrated conditioning state must be explicit strings')
            if type(mc) is not dict or type(data) is not dict or not mc or any(type(x) is not str or not x for x in mc):
                raise ValueError('Nonempty labeled joint outcomes required')
            joint_selection_scale_factor(mc,data,tuple(mc))
            if any(mc[k] == 0 and data[k] > 0 for k in mc):
                raise ValueError('Data response has support absent from reference MC')
            key=tuple(context[x] for x in contexts)
            if key in index: raise ValueError('Duplicate conditioning cell')
            index[key]=_freeze(cell)
        self=object.__new__(cls)
        for key,value in dict(input_sha256=table.sha256,evidence=evidence,
                              _contexts=tuple(contexts),_cells=MappingProxyType(index)).items():
            object.__setattr__(self,key,value)
        return self

    def _cell(self,context):
        if type(context) is not dict or set(context) != set(self._contexts):
            raise ValueError('Exact joint conditioning fields required')
        if any(type(x) is not str or not x for x in context.values()):
            raise ValueError('Exact string conditioning state required')
        key=tuple(context[x] for x in self._contexts)
        if key not in self._cells: raise ValueError('Missing calibrated cell; no interpolation/independence fallback')
        return self._cells[key]

    def absolute_probabilities(self, context, *, population):
        """Copy the supplied absolute joint table, never interpret an SF as efficiency.

        Exact context and MC/data population must be explicit. Evidence bytes
        are rechecked; loading a table still does not certify calibration.
        """
        if population not in ("mc", "data"):
            raise ValueError("Explicit mc or data joint probability population required")
        self.evidence.read()
        return dict(self._cell(context)[population])

    def selection_sf(self,context,accepted_categories):
        cell=self._cell(context)
        return joint_selection_scale_factor(cell['mc'],cell['data'],accepted_categories)

    def category_sf(self,context,category):
        cell=self._cell(context)
        if type(category) is not str or category not in cell['mc'] or cell['mc'][category] <= 0:
            raise ValueError('Observed exclusive category requires positive reference MC support')
        ratio=cell['data'][category]/cell['mc'][category]
        if not math.isfinite(ratio): raise ValueError('Nonfinite category response ratio')
        return ratio

    def weight_category(self,generator_weight,context,category):
        if type(generator_weight) not in (int,float) or not math.isfinite(generator_weight):
            raise ValueError('Finite signed generator weight required')
        out=generator_weight*self.category_sf(context,category)
        if not math.isfinite(out): raise ValueError('Nonfinite corrected event weight')
        return out
