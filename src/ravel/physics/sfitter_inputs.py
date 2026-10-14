"""Private source-only native SFitter contract preflight. No solver imports or dispatch.

Preserve native likelihood semantics. Do not translate RFit into covariance or
claim that a well-formed input has converged, been calibrated or been reviewed.
"""
import ast
from copy import deepcopy
import hashlib
import json
import math
from pathlib import Path
import re

MAX_INPUT_BYTES = 16 * 1024 * 1024
def _finite(value):
    if type(value) not in (int, float) or not math.isfinite(value):
        raise ValueError('nonfinite or nonnumeric native card value')
    return value
def _vector(value, count, label):
    if not isinstance(value, list) or len(value) != count:
        raise ValueError(label + ' must cover exactly every native bin')
    return [_finite(x) for x in value]
def _pin(path):
    path = Path(path).absolute()
    if any(p.is_symlink() for p in (path, *path.parents)) or not path.is_file():
        raise ValueError('native input must be an ordinary source-bound file')
    raw = path.read_bytes()
    if len(raw) > MAX_INPUT_BYTES:
        raise ValueError('native input byte bound')
    return {'path': str(path), 'sha256': hashlib.sha256(raw).hexdigest(), 'bytes': len(raw),
            'mode': path.stat().st_mode & 0o777}
def _load(path):
    _pin(path)
    from ravel.workflow.state_io import read_json
    return read_json(path)
def native_basis(source_root):
    path = Path(source_root) / 'sfitter/sfitter/likelihood/full_likelihood.py'
    module = ast.parse(path.read_text())
    cls = next(node for node in module.body if isinstance(node, ast.ClassDef) and node.name == 'ProfileLikelihood')
    item = next(node for node in cls.body if isinstance(node, ast.Assign)
                and any(isinstance(n, ast.Name) and n.id == '_TOP_PARAMETER_NAMES' for n in node.targets))
    basis = ast.literal_eval(item.value)
    if len(basis) != 22 or len(set(basis)) != 22:
        raise ValueError('unexpected native top-sector basis')
    return basis
def inspect_datacard(card, basis):
    if not isinstance(card, dict) or set(card) != {'observations', 'predictions'}:
        raise ValueError('known-card contract requires exact native observations/predictions fields')
    observations, predictions = card['observations'], card['predictions']
    if not isinstance(observations, list) or not observations or not isinstance(predictions, list) or len(observations) != len(predictions):
        raise ValueError('native positional pairing requires equal nonempty populations')
    seen, rows, nuisance = set(), [], set()
    for observation, prediction in zip(observations, predictions):
        identity = observation['ID']
        if not isinstance(identity, str) or identity in seen or prediction['ID'] != identity or prediction['name'] != observation['name']:
            raise ValueError('native positional observation/prediction ID/name pairing or duplicate')
        seen.add(identity)
        count = len(observation['Meas']['data'])
        if not count:
            raise ValueError('empty native observation')
        for values, label in ((observation['Meas']['data'], 'measurements'),
                              (observation['Bkg']['data'], 'backgrounds'),
                              (prediction['data'], 'predictions'), (observation['bin_widths'], 'widths')):
            _vector(values, count, label)
        if any(v <= 0 for v in observation['bin_widths']):
            raise ValueError('native widths must be positive')
        types = set()
        for location, modifiers in (('Meas', observation['Meas']['modifiers']),
                                    ('Bkg', observation['Bkg']['modifiers']), ('theory', observation['modifiers'])):
            if not isinstance(modifiers, list):
                raise ValueError('native modifiers must be an explicit list')
            keys = set()
            for modifier in modifiers:
                kind = modifier['type']
                if kind not in ({'theo'} if location == 'theory' else {'pois', 'stat', 'syst'}):
                    raise ValueError('native uncertainty modifier placement/type')
                key = ''.join(str(modifier.get(k, '')) for k in ('type', 'label', 'energy', 'name'))
                if key in keys:
                    raise ValueError('duplicate native uncertainty nuisance key')
                keys.add(key); nuisance.add(key); types.add(kind)
                values = _vector(modifier['data'], count, 'uncertainty source')
                if any(v < 0 for v in values) or 'bin' in modifier:
                    raise ValueError('known-card dialect requires nonnegative complete source arrays')
        if not {'pois', 'stat'} <= types:
            raise ValueError('native card requires explicit Poisson/stat source slots')
        # Native coefficient assignment overwrites; reversed cross names are
        # not a second independent contribution to the same monomial.
        terms, monomials = set(), set()
        for modifier in prediction['modifiers']:
            name = modifier['name']
            parts = name.split('x')
            if len(parts) not in (1, 2) or any(p not in basis for p in parts) or name in terms:
                raise ValueError('unknown, omitted or duplicate native Wilson term; explicit projected card needed')
            canonical = tuple(sorted(parts))
            if canonical in monomials:
                raise ValueError('duplicate native monomial, including reversed mixed terms')
            monomials.add(canonical)
            if modifier.get('type', 'WC') != 'WC':
                raise ValueError('known top card contains non-WC prediction dialect')
            _vector(modifier['data'], count, 'absolute D6 contribution')
            terms.add(name)
        block = observation.get('bin_correlation')
        if block is not None:
            if not isinstance(block, list) or len(block) != count:
                raise ValueError('native published correlation block population')
            for row in block:
                _vector(row, count, 'published correlation block')
            for i, row in enumerate(block):
                if not math.isclose(row[i], 1, rel_tol=0, abs_tol=1e-6):
                    raise ValueError('native correlation must have unit diagonal')
                if any(not math.isclose(row[j], block[j][i], rel_tol=0, abs_tol=1e-12) for j in range(count)):
                    raise ValueError('published correlation block must be explicitly symmetric')
        rows.append({'ID': identity, 'name': observation['name'], 'bins': count,
                     'prediction_terms': sorted(terms), 'published_block': block is not None,
                     'native_normalizes_by_prediction_integral': count > 1})
    return {'observations': len(rows), 'bins': sum(row['bins'] for row in rows),
            'native_nuisance_keys': sorted(nuisance), 'population': rows}
def compile_known_card(source_root, datacard, run_card, *, input_scope='upstream_known_card'):
    """Validate and declare a future unchanged native call; grants no execution."""
    source_root, datacard, run_card = Path(source_root).absolute(), Path(datacard).absolute(), Path(run_card).absolute()
    if input_scope not in ('upstream_known_card', 'engineering_control'):
        raise ValueError('unknown native input scope')
    basis = native_basis(source_root)
    card = _load(datacard)
    census = inspect_datacard(card, basis)
    _pin(run_card)
    raw = run_card.read_text()
    # This boundary only admits the exact shipped top numerical settings, not arbitrary YAML.
    singleton = {name: re.findall(r'^' + name + r':\s*([^\n#]+)\s*$', raw, re.M) for name in
                 ('run_name', 'sector', 'likelihood', 'precision', 'fitter', 'datacard')}
    if any(len(values) != 1 for values in singleton.values()) or any('parameter_names:' in line for line in raw.splitlines()):
        raise ValueError('known run-card singleton fields/full active basis required')
    fields = {name: values[0].strip() for name, values in singleton.items()}
    if fields['sector'] != 'top' or fields['likelihood'] != 'profile' or fields['precision'] != 'double' or fields['fitter'] != 'flow':
        raise ValueError('known full top/native profile/double/flow settings required')
    if not re.fullmatch(r'[A-Za-z0-9_]{1,64}', fields['run_name']):
        raise ValueError('safe literal run name required for native Documenter shell-close behavior')
    if (run_card.parent.parent / fields['datacard']).resolve() != datacard.resolve():
        raise ValueError('native run card points at a different datacard')
    # Do not pretend a regex implements the native YAML loader. This deliberately
    # finite boundary only supports the shipped full run card, with two literal
    # path/run-name substitutions. Every numerical setting remains upstream.
    def numerical_body(value):
        return re.sub(r'^(run_name|datacard):[^\n]*$', r'\1: <literal>', value, flags=re.M)
    template = source_root / 'sfitter/params/top_fit.yaml'
    if numerical_body(raw) != numerical_body(template.read_text()):
        raise ValueError('known run card must retain exact upstream numerical settings')
    core = source_root / 'sfitter'
    files = [_pin(p) for p in sorted(core.rglob('*.py')) if not p.name.endswith('.bak')]
    return {'schema_version': 1, 'kind': 'sfitter_known_card_prospective_contract',
            'upstream_commit': '6072a79e0f132d61a927f11ed482a401b34f6e3f',
            'source_root': str(source_root), 'input_scope': input_scope,
            'source_files': files, 'datacard': _pin(datacard), 'run_card': _pin(run_card),
            'run_card_template': _pin(template),
            'active_parameter_names': basis, 'census': census,
            'numeric_api': {'likelihood': 'sfitter.likelihood.full_likelihood.ProfileLikelihood(params, device)',
                            'fitter': 'sfitter.fit.flow_fitter.FlowFitter(params, verbose, device, model_file, likelihood)',
                            'calls': ['train()', 'save()', 'fit()'],
                            'cli': ['<exact-admitted-python>', '-B', '-m', 'sfitter', 'run', '<copied-pinned-run-card>'],
                            'working_directory': '<private-copied-sfitter-package-with-output-directory>'},
            'native_semantics': {'raw_score': '-chi2', 'profile_array': 'exp(raw_score)',
                                 'marginal_target': 'exp(raw_score)',
                                 'group_normalization': 'every multi-bin observation normalized using prediction and bin_widths',
                                 'experimental_correlation': 'native nuisance keys; rho=.99 unless explicitly changed',
                                 'published_blocks': 'replace within-observation correlation; capped native shrinkage',
                                 'native_corr_eigenvalue_floor': .001, 'native_corr_max_shrinkage': .10,
                                 'theory': 'per-bin sum of theory magnitudes; independent RFit clamp before correlated contraction',
                                 'interval_acceptance': 'unresolved until explicit score/method/threshold and independent checks',
                                 'globality_or_stationarity_proof': False},
            'raw_outputs_required': ['native stdout/stderr and exit status', 'params.yaml', 'model.pth',
                                     'results.pkl retained as opaque bytes', 'all native plots',
                                     'separate source-bound bounded JSON of raw score/profile/marginal arrays'],
            'runtime': {'core_has_CPU_fallback': True, 'SLURM_required_by_core': False,
                        'agent_launcher': 'Linux/Apptainer/Claude; heavy-job skills use SLURM and GPU',
                        'exact_dependency_lock_and_device_admission': 'pending',
                        'known_card_sampling_draws': '100 batches x 100000; additional training/profile cost not estimated'},
            'preflight_only': True, 'ordinary_science_mode_registered': True,
            'native_dispatch': False, 'fit_completed': False, 'physics_acceptance': False,
            'scientific_input_fidelity': 'unqualified; source preflight does not establish paper reconstruction or intended uncertainty model',
            'next_ordinary_boundary': 'reviewed optional scientific mode validate/inputs/run using existing execute_native, input custody, partial-output retention, resource admission and physics_review; no new runner'}
def verify_contract(contract):
    for item in [*contract['source_files'], contract['datacard'], contract['run_card'], contract['run_card_template']]:
        if _pin(item['path']) != item:
            raise ValueError('source/card/run-card changed')
    return compile_known_card(contract['source_root'], contract['datacard']['path'],
                              contract['run_card']['path'], input_scope=contract['input_scope']) == contract

def inspect_profile_datacard(card, source_root, profile, *, _observation_only=False, source_review=None):
    """Complete native physical card census, including Higgs mixture channels.

    Source quirks are retained only for the literal released JSON population.
    They never authorize repairing measurements or accepting unknown supplied
    operators. The existing strict top compiler above remains unchanged.
    """
    from . import sfitter_profiles
    if type(_observation_only) is not bool:raise ValueError('explicit observation-only validation scope required')
    basis=sfitter_profiles.basis(source_root,profile)
    if type(card) is not dict or set(card)!=({'observations','predictions','version'} if profile=='higgs' and 'version' in card else {'observations','predictions'}):raise ValueError('closed paired native card required')
    if 'version' in card and card['version']!='0.1.0':raise ValueError('exact released Higgs card metadata version required')
    observations,predictions=card['observations'],card['predictions']
    if type(observations) is not list or not observations or type(predictions) is not list or len(observations)!=len(predictions):raise ValueError('complete paired native card required')
    support={}
    if profile in ('top','higgs') and not _observation_only:
        from . import sfitter_higgs_support
        support=sfitter_higgs_support.require_supported(source_root,card,source_review)
    original=False
    higgs_tree=ast.parse((Path(source_root)/'sfitter/sfitter/likelihood/datacard.py').read_text())
    function=next(n for n in ast.walk(higgs_tree) if isinstance(n,ast.FunctionDef) and n.name=='higgs_names')
    names=next(n.value for n in function.body if isinstance(n,ast.Assign) and isinstance(n.value,ast.List))
    production_names=ast.literal_eval(names)
    # Global native Higgs names sort into five-production blocks before split(5).
    suffixes=('gf','tth','vbf','wh','zh')
    prefixes={name[:-len(suffix)] for name in production_names for suffix in suffixes if name.endswith(suffix)}
    production_blocks=[{prefix+suffix for suffix in suffixes} for prefix in sorted(prefixes)
                       if all(prefix+suffix in production_names for suffix in suffixes)]
    decays={'brw','brz','brb','brtau','brg','brga','brzga','brmu','bri'}
    seen=set();rows=[];nuisance=set();quirks=[]
    for observation_index,(o,p) in enumerate(zip(observations,predictions)):
        identity=o['ID'];count=len(o['Meas']['data'])
        if type(identity) is not str or not identity or identity in seen or p['ID']!=identity or p['name']!=o['name'] or not count:raise ValueError('complete unique positional native identity required')
        seen.add(identity)
        for v,label in ((o['Meas']['data'],'measurement'),(o['Bkg']['data'],'background'),(p['data'],'prediction'),(o.get('bin_widths',[1.]),'width')):_vector(v,count,label)
        if any(x<=0 for x in o.get('bin_widths',[1.])):raise ValueError('positive complete native bin widths required')
        decay=o.get('Decay',[1.]);lum=o.get('Luminosity',[1.])
        if type(decay) is not list or not decay or (decay!=[1.] and any(d not in decays for d in decay)):raise ValueError('known explicit native decay population required')
        if profile=='top' and decay!=[1.]:raise ValueError('top cannot adopt a Higgs mixture')
        _vector(lum,1,'native luminosity')
        if lum[0]<=0:raise ValueError('positive supplied native luminosity required')
        pois=[]
        for loc,mods in (('Meas',o['Meas']['modifiers']),('Bkg',o['Bkg']['modifiers']),('theory',o['modifiers'])):
            if type(mods) is not list:raise ValueError('full native nuisance list required')
            keys=set()
            for modifier_index,m in enumerate(mods):
                kind=m['type'];key=''.join(str(m.get(k,'')) for k in ('type','label','energy','name'))
                allowed=kind in ({'theo'} if loc=='theory' else {'pois','stat','syst'})
                if not allowed and source_review is not None:
                    placement = f"/observations/{observation_index}/" + (f"{loc}/modifiers/{modifier_index}" if loc != 'theory' else f"modifiers/{modifier_index}")
                    entries = support.get('scientific_input_support',{}).get('nuisance_placements',[])
                    matching = [entry for entry in entries if entry.get('path') == placement
                                and json.dumps(entry.get('expected'),sort_keys=True,separators=(',',':'),allow_nan=False) == json.dumps(m,sort_keys=True,separators=(',',':'),allow_nan=False) and entry.get('native_disposition') == 'retained_unused']
                    if len(matching) == 1 and matching[0].get('evidence'):
                        allowed=True;quirks.append(deepcopy(matching[0]))
                if not allowed or key in keys:raise ValueError('native nuisance type/order/identity required')
                keys.add(key);nuisance.add(key)
                if 'bin' in m:
                    index=m['bin']
                    if type(index) is not int or not 0<=index<count:raise ValueError('valid literal native bin modifier required')
                    value=m['data'];values=[value] if type(value) in (int,float) else _vector(value,1,'native bin modifier')
                else:values=_vector(m['data'],count,'complete native nuisance')
                if any(_finite(v)<0 for v in values):raise ValueError('nonnegative native uncertainty magnitudes required')
                if kind=='pois':pois.append(loc)
        if len(pois) not in (1,2):raise ValueError('native two-slot Poisson geometry requires one broadcast or two source modifiers')
        terms=[];monomials=set()
        for m in p['modifiers']:
            name=m['name'];kind=m.get('type','WC');parts=name.split('x')
            if kind=='WC':
                if len(parts) not in (1,2) or any(v not in basis for v in parts):
                    raise ValueError('unknown native Wilson coordinate; literal source defects require explicit justified derived-card provenance')
                key=tuple(sorted(parts))
                if key in monomials:raise ValueError('native term overwrite including reversed monomial refused')
                monomials.add(key);_vector(m['data'],count,'signed complete Wilson term')
            elif kind=='Higgs' and profile=='higgs' and decay!=[1.] and name in production_names:
                _vector(m['data'],len(decay) if len(decay)>1 else count,'complete native production/decay mixture')
                if name in terms:raise ValueError('duplicate native Higgs production mixture')
            else:raise ValueError('source-defined physical prediction type required')
            terms.append(name)
        if decay!=[1.]:
            if count!=1:raise ValueError('released native mixture expects one measured scalar per decay-channel combination')
            if not _observation_only:
                supplied={m['name'] for m in p['modifiers'] if m.get('type')=='Higgs'}
                weights=support['scientific_input_support']['native_production_scaling']['weights']
                # Native first-active-block selection follows SM scaling, not
                # raw coefficient activity (the TEV ttH source scale is zero).
                active={m['name'] for m in p['modifiers'] if m.get('type')=='Higgs'
                        and any((float(weights[m['name']])*float(v))*float(lum[0])!=0 for v in m['data'])}
                complete=[block for block in production_blocks if block<=supplied]
                if supplied!=set().union(*complete) or len([block for block in complete if active&block])!=1:
                    raise ValueError('exactly one active complete native five-production energy block required; partial/first-block truncation is not admission')
            if any(m.get('type','WC')=='WC' for m in p['modifiers']):raise ValueError('Higgs mixture cannot silently discard a supplied WC prediction branch')
        block=o.get('bin_correlation')
        if block is not None:
            if type(block) is not list or len(block)!=count:raise ValueError('complete source correlation block required')
            for row in block:_vector(row,count,'correlation row')
            for i in range(count):
                if not math.isclose(block[i][i],1,abs_tol=1e-6,rel_tol=0) or any(not math.isclose(block[i][j],block[j][i],abs_tol=1e-12,rel_tol=0) for j in range(count)):raise ValueError('unit symmetric published correlation required')
        rows.append({'ID':identity,'name':o['name'],'bins':count,'prediction_terms':terms,
                     'decay':decay,'luminosity':lum,'poisson_sources':pois,'published_block':block is not None,
                     'native_normalizes_by_prediction_integral':profile=='top' and count>1})
    return {'observations':len(rows),'bins':sum(r['bins'] for r in rows),'population':rows,
            'native_nuisance_keys':sorted(nuisance),'literal_released_card':original,'source_card_quirks':quirks,'observation_only':_observation_only,**support}
