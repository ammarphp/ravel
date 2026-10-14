"""Complete supplied MSSM spectrum/decay populations, not a spectrum solver.

Preserve SLHA eigenstate signs, complex rows, provider prescriptions and every
decay record. Lifetime comes from the supplied TOTAL width. Missing widths,
channels, production rates or detector responses never become physical zeroes.
"""
from copy import deepcopy
from fractions import Fraction
from itertools import product
import hashlib
import json
import math
from pathlib import Path
import re

from . import model_inputs, model_specific_spectrum as slha, model_tool_bridge as custody

SCOPE = 'supplied_mssm_spectrum_observable_delivery'
API = Path(__file__).parents[1] / 'data/spectrum/mssm-observable-conventions.json'
NEUTRALINOS = (1000022, 1000023, 1000025, 1000035)
CHARGINOS = (1000024, 1000037)
CHARGES = {**{p:Fraction() for p in (*NEUTRALINOS,1000021,1000012,1000014,1000016)},
           **{p:Fraction(1) for p in CHARGINOS},
           **{p:Fraction(-1) for p in (1000011,1000013,1000015,2000011,2000013,2000015)},
           **{p:Fraction(2,3) for p in (1000002,1000004,1000006,2000002,2000004,2000006)},
           **{p:Fraction(-1,3) for p in (1000001,1000003,1000005,2000001,2000003,2000005)}}
MAX_POINTS = 512
MAX_INPUT_BYTES = 64 * 1024**2
MAX_PROVENANCE_BYTES = 4 * 1024**3


def require(ok, message):
    slha.require(ok, message)


def keys(obj, fields, label):
    custody._keys(obj, fields, label)


def rational(token):
    # Reuse the existing bounded SLHA literal parser; no expression evaluation.
    require(type(token) is str, 'literal decimal string required')
    q = model_inputs._fraction(token, 'MSSM source scalar')
    finite(q)
    return q


def exact(q):
    return str(q.numerator) + '/' + str(q.denominator)


def finite(q):
    x = float(q)
    require(math.isfinite(x) and (q == 0 or x != 0), 'mapped physical value cannot overflow or underflow')
    return x


def loads(raw):
    from ravel.workflow.state_io import _unique
    def reject(x):
        raise ValueError('nonfinite JSON ' + x)
    return json.loads(raw, object_pairs_hook=_unique, parse_constant=reject)


def names(rows, maximum, label):
    require(type(rows) is list and 1 <= len(rows) <= maximum, 'bounded complete ' + label + ' required')
    ids = [r.get('id') for r in rows if type(r) is dict]
    require(len(ids) == len(rows) and all(type(x) is str and re.fullmatch(r'[A-Za-z][A-Za-z0-9_.-]{0,80}', x) for x in ids)
            and len(set(ids)) == len(ids), 'unique literal ' + label + ' identities required')
    return ids


def validate(task):
    from . import supplied_contracts as contracts
    contracts.fields(task, ('request',))
    keys(task, ('request', 'output') if 'output' in task else ('request',), 'MSSM map task')
    if 'output' in task: contracts.output_contract(task['output'])
    require(type(task['request']) is str and task['request'].strip(), 'explicit map request path required')
    return task


def binding(b):
    keys(b, ('origin', 'terms'), 'explicit coordinate/parameter binding')
    require(b['origin'] in ('input', 'spectrum') and type(b['terms']) is list and 1 <= len(b['terms']) <= 2,
            'one scalar or explicit two-scalar linear difference required')
    for t in b['terms']:
        keys(t, ('selector', 'factor'), 'source parameter term')
        s = t['selector']; keys(s, ('block', 'codes', 'scale'), 'exact SLHA occurrence selector')
        require(type(s['block']) is str and re.fullmatch(r'[A-Za-z][A-Za-z0-9_]*', s['block']) and
                type(s['codes']) is list and s['codes'] and all(type(i) is int for i in s['codes']), 'literal SLHA address required')
        require(s['scale'] is None or (type(s['scale']) is str and rational(s['scale']) > 0), 'explicit positive scale or source-unscaled null required')
        require(rational(t['factor']) in (-1, 1), 'unit signed coordinate term required')


def request_document(d):
    keys(d, ('schema_version', 'operation', 'source', 'population', 'axes', 'fixed_parameters', 'conventions',
             'species', 'components', 'energy_tev', 'points'), 'physical MSSM map request')
    require(type(d['schema_version']) is int and d['schema_version'] == 1 and d['operation'] == 'mssm_slha_observable_map',
            'MSSM supplied spectrum-map schema1 required')
    require(type(d['source']) is str and d['source'].strip(), 'literal source and intended task required')
    require(rational(d['energy_tev']) > 0, 'explicit positive collider energy in TeV required')
    names(d['axes'], 4, 'axes')
    expected = []
    for a in d['axes']:
        keys(a, ('id', 'unit', 'values', 'binding'), 'complete axis')
        require(a['unit'] == 'GeV' and type(a['values']) is list and 1 <= len(a['values']) <= MAX_POINTS, 'GeV axes require literal complete values')
        vals = [rational(x) for x in a['values']]
        require(len(set(vals)) == len(vals), 'duplicate physical axis node refused')
        expected.append(vals); binding(a['binding'])
    pop=d['population'];keys(pop,('kind','source','layout'),'original population law')
    if pop['kind']=='source-listed':
        from .supplied_contracts import fields
        fields(pop, ('source','layout'))
    require(pop['kind'] in ('cartesian','source-listed') and ((pop['source'] is None)==(pop['kind']=='cartesian')),
            'explicit Cartesian or complete source-listed population required')
    if pop['kind']=='source-listed' and pop['layout'] != 'point-list-v1':
        from .supplied_contracts import MissingInputError
        raise MissingInputError('population.layout', 'Normalize the supplied population to point-list-v1 before admission')
    require(pop['layout'] is None if pop['kind']=='cartesian' else pop['layout'] == 'point-list-v1',
            'explicit complete population reader required')
    ids = names(d['points'], MAX_POINTS, 'points')
    coordinates=[tuple(rational(x) for x in p['coordinate']) for p in d['points']]
    require(len(set(coordinates))==len(coordinates) and all(len(x)==len(expected) and all(v in expected[i] for i,v in enumerate(x)) for x in coordinates),
            'distinct declared points in the complete axis domains required')
    if pop['kind']=='cartesian':
        require(math.prod(map(len,expected))<=MAX_POINTS and coordinates==list(product(*expected)),
                'entire ordered Cartesian population required; no missing-node interpolation')
    require(type(d['fixed_parameters']) is list and len(d['fixed_parameters']) <= 64, 'bounded explicit fixed-parameter census required')
    if d['fixed_parameters']: names(d['fixed_parameters'], 64, 'fixed parameters')
    for row in d['fixed_parameters']:
        keys(row, ('id', 'unit', 'binding', 'value'), 'fixed physical parameter')
        require(row['unit'] in ('GeV', 'dimensionless'), 'explicit parameter units required')
        binding(row['binding']); rational(row['value'])
    c = d['conventions']
    keys(c, ('basis', 'cp', 'mixing_scale', 'mixing_prescription', 'orthogonality_absolute'), 'MSSM conventions')
    require(c['basis'] == 'SLHA-MSSM' and c['cp'] in ('real-signed', 'complex-positive'), 'explicit SLHA MSSM sign/phase convention required')
    require(c['mixing_scale'] is None or rational(c['mixing_scale']) > 0, 'explicit mixing occurrence scale required')
    require(type(c['mixing_prescription']) is str and c['mixing_prescription'].strip(), 'provider scale/scheme prescription cannot be inferred')
    require(0 <= rational(c['orthogonality_absolute']) <= Fraction(1,100), 'prospective finite mixing band from 0 to .01 required')
    species = names(d['species'], 64, 'observable species')
    pdgs = []
    for s in d['species']:
        keys(s, ('id', 'pdg', 'charge_e'), 'observable species')
        require(type(s['pdg']) is int and s['pdg'] in CHARGES, 'explicit standard MSSM sparticle PDG required')
        require(rational(s['charge_e'])==CHARGES[s['pdg']], 'declared charge differs from standard signed MSSM particle identity')
        pdgs.append(s['pdg'])
    require(len(set(pdgs)) == len(pdgs), 'duplicate species PDG refused')
    names(d['components'], 32, 'production components')
    for comp in d['components']:
        keys(comp, ('id', 'process', 'decay_channels', 'species'), 'production identity')
        require(all(type(comp[k]) is str and comp[k].strip() for k in ('process','decay_channels')) and
                type(comp['species']) is list and comp['species'] and len(set(comp['species'])) == len(comp['species']) and
                set(comp['species']) <= set(species), 'explicit process, decay and complete selected species required')
    for p in d['points']:
        keys(p, ('id', 'coordinate', 'spectrum', 'input_card', 'decay_manifest', 'provider', 'origin'), 'physical point')
        origin = p['origin']
        require(type(origin) is dict and origin.get('kind') in ('supplied_unqualified', 'accepted_cmssm_spectrum', 'accepted_lowmssm_spectrum', 'accepted_spheno_mssm_spectrum'), 'explicit supplied or accepted CMSSM/lowMSSM origin required')
        keys(origin, ('kind', 'run') if origin['kind'] != 'supplied_unqualified' else ('kind',), 'spectrum origin')
    return d


def _read_source(ref, base):
    # Parse this authenticated buffer, never a later path read without its pin.
    keys(ref, ('path','sha256'), 'scientific source pin')
    require(type(ref['sha256']) is str and re.fullmatch(r'[0-9a-f]{64}', ref['sha256']), 'literal source SHA256 required')
    path = custody._regular(ref['path'], base)
    raw = slha.raw_file(path, ref['sha256'])
    require(hashlib.sha256(raw).hexdigest() == ref['sha256'], 'consumed source buffer SHA differs')
    return path, raw


def _pin(ref, base):
    return _read_source(ref, base)[0]


def _provider(raw):
    p = loads(raw)
    keys(p, ('schema_version','name','version','model','spectrum_method','decay_method','mass_scheme','mixing_prescription','source_evidence'), 'provider prescription')
    require(type(p['schema_version']) is int and p['schema_version'] == 1 and p['model'] == 'MSSM' and p['mass_scheme'] == 'pole', 'explicit MSSM pole-mass provider contract required')
    require(all(type(p[k]) is str and p[k].strip() for k in ('name','version','spectrum_method','decay_method','mixing_prescription')) and
            type(p['source_evidence']) is list and 1 <= len(p['source_evidence']) <= 32, 'spectrum/decay prescription and pinned evidence required')
    return p


def _origin(p, base):
    """Reuse qualified transport only; never infer numerical/physics accuracy."""
    if p['origin']['kind'] == 'supplied_unqualified': return []
    from ravel.workflow import task_completion as tc, science, execution
    from . import generated_spectrum
    observed = tc._Inputs(base)
    try:
        rd, _ = tc._accepted_review(p['origin']['run'], slha.SCOPE, observed)
        spec = science.execution_spec(rd)
        require(spec['mode'] == 'generated-spectrum', 'accepted provider must be an actual generated-spectrum study')
        configpath, config = generated_spectrum._load(spec['task'], rd)
        if p['origin']['kind']=='accepted_cmssm_spectrum':
            require(config['schema_version']==1,'accepted CMSSM origin requires the genuine legacy CMSSM source')
            model='CMSSM'
        elif p['origin']['kind']=='accepted_lowmssm_spectrum':
            from . import weak_scale_mssm as weak
            require(config['schema_version']==2 and config['profile']==weak.NAME and config['operation']==weak.OPERATION,
                'accepted weak-scale origin requires the genuine released lowMSSM source, not CMSSM or NMSSM')
            model='lowMSSM'
        else:
            from . import spheno_mssm
            require(spheno_mssm.selected(config),'accepted SPheno origin requires exact released MSSM provider')
            model='MSSM'
        outputs = execution.load_execution(rd)['stages']['science']['outputs']
        require(len(outputs) == 1, 'one complete accepted generated-spectrum output required')
        out = custody._regular(outputs[0], rd, directory=True)
        resultpath = out / 'generated-spectrum.json'
        result = observed.document(observed.capture(resultpath))
        if model=='MSSM':
            providerpath=_pin(p['provider'],base)
            providerpin=observed.capture(providerpath)
            provider=_provider(observed.file(providerpin)[0])
            require(result['model_profile']==spheno_mssm.NAME and
                    result['configuration']=={'path':str(configpath),'sha256':custody._hash(configpath)} and
                    provider['name']=='SPheno' and provider['version']=='4.0.5',
                    'accepted SPheno origin must bind actual executed configuration and source provider version')
        spectrum = _pin(p['spectrum'],base); original = _pin(p['input_card'],base)
        generated = result['generated_slha']
        require(result['status'] == 'passed' and spectrum == out/(model+'.slha') and generated['path'] == str(spectrum) and
                generated['sha256'] == p['spectrum']['sha256'] and result['solver_input_sha256'] == p['input_card']['sha256'],
                'map must use the exact accepted return and original solver input')
        if model=='lowMSSM':
            from . import model_specific_spectrum as named
            observed.capture(configpath);observed.capture(weak.PROFILE)
            require(result['model_profile']==weak.NAME and result['configuration']=={'path':str(configpath),'sha256':custody._hash(configpath)} and
                result['physics_validated'] is False and result['requested_decays'] is False and result['decay_implementation_available'] is False,
                'accepted lowMSSM transport must retain its exact configuration/profile and no-decay scope')
            require(original==custody._pin(config['input_card'],configpath.parent), 'map original input must be the accepted selected lowMSSM card')
            require(result['full_slha']==named.inventory(named.raw_file(spectrum,p['spectrum']['sha256'])) and
                result['input_witness']==weak.input_witness(named.raw_file(original,p['input_card']['sha256']),False,'none'),
                'map must retain the complete accepted lowMSSM return and input witness')
        observed.capture(spectrum); observed.capture(original); observed.finish()
        return [Path(v['path']) for v in observed.pins.values()]
    finally: observed.close()


def _capture(task, base):
    validate(task); path = custody._regular(task['request'], base)
    raw = slha.raw_file(path); d = request_document(loads(raw))
    from . import supplied_contracts
    paths = [path, API, Path(supplied_contracts.__file__).resolve()]; interpreted = [path, API]
    if d['population']['kind']=='source-listed':
        pp, population_raw = _read_source(d['population']['source'], path.parent)
        population = loads(population_raw)
        keys(population,('schema_version','points'),'complete source-listed physical population')
        require(type(population['schema_version']) is int and population['schema_version']==1,'source-listed schema1 required')
        expected=population['points']
        for point in expected:
            keys(point, ('id', 'coordinate'), 'normalized source population point')
        require(len(expected)==len(d['points']) and [p['id'] for p in expected]==[p['id'] for p in d['points']] and
                [[rational(x) for x in p['coordinate']] for p in expected]==[[rational(x) for x in p['coordinate']] for p in d['points']],
                'entire ordered original source-listed point census required')
        paths.append(pp);interpreted.append(pp)
    for p in d['points']:
        consumed = {k: _read_source(p[k], path.parent) for k in ('spectrum','input_card','decay_manifest','provider')}
        parsed = [row[0] for row in consumed.values()]
        paths += parsed; interpreted += parsed
        provider = _provider(consumed['provider'][1])
        evidence = [_pin(e,path.parent) for e in provider['source_evidence']]
        paths += evidence; interpreted += evidence
        paths += _origin(p,path.parent)
    paths = sorted(set(paths))
    require(sum(p.stat().st_size for p in set(interpreted)) <= MAX_INPUT_BYTES, 'complete interpreted input inventory exceeds map byte ceiling')
    require(len(paths)<=100000 and sum(p.stat().st_size for p in paths)<=MAX_PROVENANCE_BYTES,
            'complete accepted provenance exceeds explicit inventory/streaming ceiling; never truncate')
    before = {p: _source_snapshot(p) for p in paths}
    require(before[path][0] == hashlib.sha256(raw).hexdigest(), 'request changed before map capture')
    return path, d, paths, before


def _identity(path):
    s = Path(path).stat()
    return s.st_dev,s.st_ino,s.st_mode,s.st_size,s.st_mtime_ns,s.st_ctime_ns


def _source_snapshot(path):
    """Stream opaque accepted native evidence; do not parse it as SLHA/JSON."""
    import os
    p=custody._regular(path,Path.cwd());before=_identity(p)
    require(0<=p.stat().st_size<=MAX_PROVENANCE_BYTES,'bounded provenance file required')
    h=hashlib.sha256();size=0
    with p.open('rb') as stream:
        opened=os.fstat(stream.fileno())
        while True:
            block=stream.read(1024**2)
            if not block:break
            size+=len(block);require(size<=before[3] and size<=MAX_PROVENANCE_BYTES,'provenance grew during streaming')
            h.update(block)
        closed=os.fstat(stream.fileno())
    index=lambda s:(s.st_dev,s.st_ino,s.st_mode,s.st_size,s.st_mtime_ns,s.st_ctime_ns)
    require(before==index(opened)==index(closed)==_identity(p) and size==before[3],'provenance identity/bytes changed during streaming')
    return h.hexdigest(),before


def _finish(task, base, paths, before):
    # Resolve acceptance again as well as exact bytes/identity; no cross-call cache.
    _, _, current, ending = _capture(task, base)
    require(paths == current and before == ending, 'map input/accepted-origin changed, including restored-byte identity drift')


def inputs(task, base):
    return _capture(task, base)[2]


def _value(b, spectrum, original):
    source = original if b['origin'] == 'input' else spectrum
    return sum((rational(t['factor']) * rational(slha.scalar(source,t['selector'])) for t in b['terms']), Fraction())


def _block(doc, name, scale, n, cp):
    def rows(block):
        sections = [s for s in doc['sections'] if s.get('name') == block and s['kind'] == 'block']
        if not sections: return None
        require(len(sections) == 1 and sections[0]['scale'] == scale, 'exact single mixing occurrence required: ' + block)
        rr = sections[0]['rows']; addresses = [tuple(r.get('codes',[])) for r in rr]
        require(len(rr) == n*n and all(r['kind'] == 'scalar' for r in rr) and len(set(addresses)) == n*n and
                set(addresses) == set(product(range(1,n+1), repeat=2)), 'complete MSSM mixing address population required: ' + block)
        return {tuple(r['codes']):rational(r['value']) for r in rr}
    real = rows(name); require(real is not None, 'missing complete mixing matrix ' + name)
    imag = rows('IM'+name)
    if imag is None: imag = {k:Fraction() for k in real}
    require(cp != 'real-signed' or not any(imag.values()), 'complex mixing cannot be silently treated as real')
    return real, imag, {'imaginary_source':'explicit_block' if any(s.get('name') == 'IM'+name for s in doc['sections']) else 'SLHA2_declared_zero_default'}


def _mixing(doc, c):
    out = {}; bound = rational(c['orthogonality_absolute'])
    for block,n,pdgs,basis in (('NMIX',4,NEUTRALINOS,['-i_bino','-i_wino3','higgsino_d0','higgsino_u0']),
                             ('UMIX',2,CHARGINOS,['-i_wino_minus','higgsino_d_minus']),
                             ('VMIX',2,CHARGINOS,['-i_wino_plus','higgsino_u_plus'])):
        real,imag,source = _block(doc,block,c['mixing_scale'],n,c['cp']); residuals = []
        for i,j in product(range(1,n+1),repeat=2):
            a = sum(real[i,k]*real[j,k]+imag[i,k]*imag[j,k] for k in range(1,n+1))-int(i==j)
            b = sum(imag[i,k]*real[j,k]-real[i,k]*imag[j,k] for k in range(1,n+1))
            require(abs(a) <= bound and abs(b) <= bound, 'mixing unitarity differs beyond the declared engineering band')
            residuals.append({'row':i,'column':j,'real_exact':exact(a),'imag_exact':exact(b)})
        out[block] = {**source,'basis':basis,'prescription':c['mixing_prescription'],'scale_token':c['mixing_scale'],
          'rows':[{'row':i,'pdg':pdgs[i-1],'entries':[{'column':j,'real_exact':exact(real[i,j]),'imag_exact':exact(imag[i,j]),
              'absolute_squared_exact':exact(real[i,j]**2+imag[i,j]**2)} for j in range(1,n+1)]} for i in range(1,n+1)],
          'unitarity_residuals':residuals,'production_rates_derived':False,'row_rephasing_performed':False}
    return out


def _charge_witness(doc,pdg):
    rows=[s for s in doc['sections'] if s.get('name')=='QNUMBERS' and s.get('pdg')==pdg]
    require(len(rows)<=1,'duplicate quantum-number particle definition refused')
    if not rows:return {'charge_e_exact':exact(CHARGES[pdg]),'source':'standard_SLHA_MSSM_particle_identity'}
    charge=[r for r in rows[0]['rows'] if r['tokens'][0]=='1']
    require(len(charge)==1 and len(charge[0]['tokens'])==2 and rational(charge[0]['tokens'][1])/3==CHARGES[pdg],
            'source QNUMBERS three-times-electric-charge differs from mapped particle')
    return {'charge_e_exact':exact(CHARGES[pdg]),'source':'literal_QNUMBERS_three_times_charge','source_line':charge[0]['line']}


def derive_point(spectrum_raw, input_raw, manifest_raw, provider_raw, point, d):
    spectrum, original = slha.inventory(spectrum_raw), slha.inventory(input_raw)
    require(not spectrum['native_error_rows'] and not original['native_error_rows'], 'SPINFO/DCINFO native error cannot become a physical point')
    provider = _provider(provider_raw)
    require(provider['mixing_prescription'] == d['conventions']['mixing_prescription'], 'mixing prescription must match the supplied provider')
    for doc in (spectrum,original):
        for s in doc['sections']:
            require(s.get('name') not in ('NMSSMRUN','NMNMIX','IMNMNMIX'), 'NMSSM spectrum cannot be relabelled as MSSM')
            if s.get('name') == 'MODSEL':
                for r in s['rows']:
                    if r.get('codes') in ([3],[4]): require(r['kind']=='scalar' and rational(r['value']) == 0, 'non-MSSM or RPV model cannot use this MSSM map')
                    if r.get('codes') == [5]:
                        require(r['kind']=='scalar' and rational(r['value']) == (0 if d['conventions']['cp']=='real-signed' else 2), 'explicit CP switch differs from sign/phase convention')
    witness = model_inputs.audit_slha_bytes(spectrum_raw, source_name=point['spectrum']['path'],
          expected_sha256=point['spectrum']['sha256'], completeness_manifest=loads(manifest_raw))
    masses = {r['pdg']:Fraction(r['mass_GeV_exact']) for r in witness['masses']}
    require(1000045 not in masses,'fifth neutralino cannot enter a four-state MSSM map')
    require(set((*NEUTRALINOS,*CHARGINOS)) <= set(masses), 'complete four-neutralino/two-chargino mass population required')
    ew = (*NEUTRALINOS,*CHARGINOS)
    require(all(masses[p] != 0 for p in ew), 'nonzero mapped electroweakino masses required')
    require(d['conventions']['cp'] != 'complex-positive' or all(masses[p]>0 for p in ew), 'CPV SLHA masses must be positive with complex phases retained')
    require([abs(masses[p]) for p in NEUTRALINOS] == sorted(abs(masses[p]) for p in NEUTRALINOS) and
            [abs(masses[p]) for p in CHARGINOS] == sorted(abs(masses[p]) for p in CHARGINOS), 'SLHA mass-order identities differ; never reorder the matrix or PDGs')
    coordinate = [_value(a['binding'],spectrum,original) for a in d['axes']]
    require(coordinate == [rational(x) for x in point['coordinate']], 'point coordinates differ from exact supplied source addresses')
    fixed = []
    for r in d['fixed_parameters']:
        actual = _value(r['binding'],spectrum,original)
        require(actual == rational(r['value']), 'fixed model parameter differs: '+r['id'])
        fixed.append({**r,'source_value_exact':exact(actual)})
    mix = _mixing(spectrum,d['conventions'])
    decays = {r['pdg']:r for r in witness['decays']}; observables=[]; issues=[]
    for s in d['species']:
        pdg=s['pdg'];require(pdg in masses and masses[pdg] != 0, 'selected species needs a nonzero actual pole mass')
        require(masses[pdg] > 0 or (pdg in ew and d['conventions']['cp']=='real-signed'), 'negative non-electroweakino kinematic mass refused; no tachyon absolute-value remedy')
        decay=decays.get(pdg);life=deepcopy(decay['lifetime']) if decay else {'status':'unknown_missing_total_width','proper_ctau_mm':None}
        if decay is None: issues.append({'species_id':s['id'],'kind':'missing_total_width','next_action':'obtain a source-bound total decay-width calculation; no invented stable lifetime'})
        elif decay['channel_completeness'].startswith('unresolved'):
            issues.append({'species_id':s['id'],'kind':'incomplete_decay_channels','next_action':'obtain full decay channels and on-shell/off-shell prescription; total-width lifetime remains conditional'})
        charge=_charge_witness(spectrum,pdg)
        observables.append({**s,'charge_witness':charge,'signed_mass_GeV_exact':exact(masses[pdg]),'pole_mass_GeV_exact':exact(abs(masses[pdg])),
            'negative_mass_convention':'SLHA_real_eigenstate_phase_required' if masses[pdg]<0 else None,
            'decay':deepcopy(decay),'lifetime':life})
    thresholds=[]
    for dec in witness['decays']:
        for ch in dec['channels']:
            pdg=dec['pdg']; daughters=[abs(x) for x in ch['daughter_pdgs']]
            known=pdg in masses and (masses[pdg]>=0 or pdg in ew) and all(x in masses and (masses[x]>=0 or x in ew) for x in daughters)
            delta=abs(masses[pdg])-sum(abs(masses[x]) for x in daughters) if known else None
            thresholds.append({'parent_pdg':pdg,'daughter_pdgs':ch['daughter_pdgs'],'source_line':ch['source_line'],
              'pole_mass_gap_GeV_exact':exact(delta) if delta is not None else None,
              'status':'unknown_missing_daughter_or_parent_mass' if delta is None else 'open_pole_threshold' if delta>0 else 'at_pole_threshold' if delta==0 else 'below_pole_threshold',
              'zero_branching_ratio':Fraction(ch['branching_fraction_exact'])==0,'width_or_branching_ratio_changed':False,
              'differential_or_resonant_decay_qualified':False})
            if Fraction(ch['branching_fraction_exact'])>0 and (delta is None or delta<=0):
                issues.append({'parent_pdg':pdg,'source_line':ch['source_line'],'kind':'unresolved_channel_kinematics',
                               'next_action':'check missing pole masses or the on-shell/off-shell source prescription; retain the literal nonzero channel'})
    splittings=[{'parent_pdg':p,'reference_pdg':1000022,'pole_mass_difference_GeV_exact':exact(abs(masses[p])-abs(masses[1000022]))}
                for p in dict.fromkeys((*ew[1:],*(s['pdg'] for s in d['species']))) if p!=1000022]
    return {'id':point['id'],'coordinate':point['coordinate'],'full_spectrum':spectrum,'full_original_input':original,
       'full_mass_decay_inventory':witness,'provider_prescription':provider,'source_origin':point['origin'],
       'source_transport_accepted':point['origin']['kind'] in ('accepted_cmssm_spectrum','accepted_lowmssm_spectrum','accepted_spheno_mssm_spectrum'),'numerical_accuracy_qualified':False,
       'mixings':mix,'other_mixing_blocks_retained_uninterpreted':[s for s in spectrum['sections'] if s.get('name','').endswith('MIX') and
            s.get('name') not in ('NMIX','UMIX','VMIX','IMNMIX','IMUMIX','IMVMIX')],
       'fixed_parameter_witnesses':fixed,'observables':observables,'pole_mass_splittings':splittings,
       'decay_threshold_diagnostics':thresholds,'unresolved_obligations':issues,
       'loop_splitting_or_total_width_computed':False,'rates_derived_from_mixing_fractions':False}


def _derive(path,d,before):
    rows=[]
    for p in d['points']:
        raw=[slha.raw_file(_pin(p[k],path.parent),p[k]['sha256']) for k in ('spectrum','input_card','decay_manifest','provider')]
        rows.append(derive_point(*raw,p,d))
    return {'schema_version':1,'status':'passed','status_scope':SCOPE,'source':d['source'],'axes':d['axes'],
      'conventions':d['conventions'],'species':d['species'],'components':d['components'],'energy_tev':d['energy_tev'],
      'population_law':d['population'],
      'points':rows,'population':{'requested_points':len(d['points']),'delivered_points':len(rows)},
      'input_pins':[{'path':str(p),'sha256':v[0],'size':p.stat().st_size} for p,v in before.items()],
      'source_equations':loads(slha.raw_file(API, before[API][0])), 'physics_validated':False,'execution_authorized':False,
      'original_task_complete':False,'native_calls':0,'supplied_cards_changed':False,
      'limitations':['Provider prescriptions are source assertions; accepted transport is not independent spectrum/decay accuracy.',
        'Total widths are supplied, never replaced by summed partial channels. Missing widths/channels stay unknown.',
        'Mixing row fractions are basis diagnostics, not production cross sections, branching models or detector acceptance.',
        'Pole gaps and rounded-literal lifetime conversion do not certify loop splitting, vacuum stability or off-shell/resonant phase space.',
        'MSSM solver/native matching, supplied projections and inference require separate accepted evidence.']}


def compile_map(task,base):
    path,d,paths,before=_capture(task,base);result=_derive(path,d,before)
    _finish(task,base,paths,before);return result


def context(task,base):
    path,d,paths,before=_capture(task,base)
    result={'schema_version':1,'kind':'mssm-spectrum-observable-context','mode':'mssm-observable-map',
      'ordinary_task':{'request':str(path)},'request':d,'input_pins':[{'path':str(p),'sha256':v[0],'size':p.stat().st_size} for p,v in before.items()],
      'equations':loads(slha.raw_file(API, before[API][0])),'physics_validated':False,'execution_authorized':False,
      'original_task_complete':False,'next_steps':['ordinary plan/approval/run for the complete map','source-bound LLP recipe handoff with supplied rates/responses','independent native spectrum, decay and inference qualification']}
    _finish(task,base,paths,before);return result


def validate_scope(spec):
    policy=spec.get('review_policy',{}).get('policy',{});scopes=policy.get('claim_scopes',{})
    require(spec.get('schema_version')==2 and spec.get('max_attempts')==1 and policy.get('max_redos')==0 and
            set(scopes)=={SCOPE} and scopes[SCOPE].get('actions')==['delivery'], 'one-attempt supplied MSSM map delivery scope required')


def verify_result(task,base,result):
    require(result==compile_map(task,base),'returned MSSM map differs from complete current source population');return True


def run(task,base,output):
    path,d,paths,before=_capture(task,base);result=_derive(path,d,before);_finish(task,base,paths,before)
    out=Path(output).expanduser().absolute()
    require(not out.exists() and not any(p.is_symlink() for p in (out,*out.parents)) and
            not any(p==out or p.is_relative_to(out) for p in paths),'fresh map output independent from all source inputs required')
    if 'output' in task:
        from .supplied_contracts import encode, publish
        require(len(encode(result, task['output']))<=MAX_INPUT_BYTES,'complete map output exceeds explicit 64 MiB delivery ceiling')
        out.mkdir(parents=True)
        target = publish(out, result, task['output'])
        try: _finish(task,base,paths,before)
        except Exception:
            target.rename(target.with_name('failed-'+target.name)); raise
        return result
    out.mkdir(parents=True);target=out/'mssm-observable-map.json'
    expected=(json.dumps(result,indent=2,allow_nan=False)+'\n').encode()
    require(len(expected)<=MAX_INPUT_BYTES,'complete map output exceeds explicit 64 MiB delivery ceiling')
    detached=loads(expected)
    try:
        receipt=slha.write_exact(target,detached);initial=_identity(target)
        _finish(task,base,paths,before)
        require(receipt=={'path':str(target.resolve()),'sha256':hashlib.sha256(expected).hexdigest()} and
                _output_bytes(target)==expected and _identity(target)==initial and
                (json.dumps(detached,indent=2,allow_nan=False)+'\n').encode()==expected and
                (json.dumps(result,indent=2,allow_nan=False)+'\n').encode()==expected,'published map differs from its exact initial commitment')
    except Exception:
        if target.exists():target.rename(out/'failed-mssm-observable-map.json')
        raise
    return result


def _output_bytes(path):
    import os
    p=custody._regular(path,Path.cwd());before=_identity(p)
    require(0<p.stat().st_size<=MAX_INPUT_BYTES,'bounded nonempty map output required')
    with p.open('rb') as stream:
        opened=os.fstat(stream.fileno());raw=stream.read(MAX_INPUT_BYTES+1);closed=os.fstat(stream.fileno())
    index=lambda s:(s.st_dev,s.st_ino,s.st_mode,s.st_size,s.st_mtime_ns,s.st_ctime_ns)
    require(before==index(opened)==index(closed)==_identity(p) and len(raw)<=MAX_INPUT_BYTES,'map output changed during bounded consumption')
    return raw


def main(argv=None):
    import argparse
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--request',required=True)
    parser.add_argument('--llp-template');parser.add_argument('--output-dir')
    args=parser.parse_args(argv);path=custody._regular(args.request,Path.cwd());task={'request':str(path)}
    if args.llp_template is not None:
        require(args.output_dir is not None,'LLP source handoff requires an explicit fresh output directory')
        from . import mssm_llp_handoff
        result=mssm_llp_handoff.prepare(task,path.parent,args.llp_template,args.output_dir)
    else:
        require(args.output_dir is None,'output is only used for explicit LLP preparation');result=context(task,path.parent)
    print(json.dumps(result,indent=2,allow_nan=False));return 0


if __name__=='__main__':raise SystemExit(main())
