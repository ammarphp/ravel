"""Source-backed analysis discovery and adaptation planning. Never authorizes execution."""
from __future__ import annotations
from collections import Counter
import hashlib
from importlib.resources import files
import json
from pathlib import Path, PurePosixPath
import re
import subprocess

SCHEMA_VERSION = 1
FAMILIES = {
    'fiducial-measurement': 'Particle-level observable and reference comparison',
    'search-recast': 'Search selection and detector-response validation',
    'heavy-ion': 'Ion beams, centrality and nuclear reference treatment',
    'long-lived': 'Lifetime, decay geometry and non-prompt response',
    'forward': 'Forward acceptance, diffraction and beam optics',
    'neutrino': 'Forward neutrino flux and interaction modeling',
    'flavour': 'Hadron production, decays and flavor observables',
    'calibration': 'Auxiliary calibration rather than an independent measurement',
}
COMMON_REQUIREMENTS = [
    'Pin the routine, runtime, model, event sample, beam settings and weight convention.',
    'Resolve fiducial objects, overlap removal, bins and observable definitions against the paper.',
    'Declare units, integrated versus differential bins, absolute versus normalized output, and exposure.',
    'Compare fixed-event cut decisions and reference quantities before an expensive campaign.',
    'Record a concrete compute budget and physicist CHECK-IN 1; this packet is not approval.',
]
FAMILY_REQUIREMENTS = {
    'flavour': [
        'Validate fragmentation, hadron species, prompt/feed-down separation and decay branching conventions.',
        'For decay observables, validate the decay/amplitude model and normalization rather than assuming hard-process generation is sufficient.',
    ],
    'calibration': [
        'Treat this as an auxiliary calibration; identify its dependent physics routines and beam/energy applicability.',
        'Validate the calibration sample, percentile mapping and correlated uncertainty before reuse.',
    ],
    'fiducial-measurement': [
        'Validate stable-particle/dressed-lepton definitions, jet algorithm and generator cuts.',
        'For inference, acquire the covariance or full likelihood, SM prediction and theory uncertainties; do not treat measurement bins as independent counts.',
        'Define overlapping-measurement treatment before combining analyses; a reference YODA file is not a likelihood.',
    ],
    'search-recast': [
        'Validate trigger, reconstruction, identification/tagging and migration against published efficiencies and cutflows.',
        'Map signal and control regions to the exact likelihood channels and account for overlapping regions.',
        'Retain signal contamination, finite-MC uncertainty, nuisance correlations and normalization basis.',
    ],
    'heavy-ion': [
        'Add validated ion/fixed-target beam support, centrality calibration and nuclear normalization.',
        'Specify event mixing, medium/background treatment and event-plane conventions when applicable.',
        'A proton-proton detector/exclusion adapter cannot be assumed valid for nuclear observables.',
    ],
    'long-lived': [
        'Add validated proper-lifetime sampling, boosts, decay geometry and survival probabilities.',
        'Bind prompt/displaced/track/timing reconstruction efficiencies and trigger response to the published lifetime domain.',
        'Verify benchmark masses and lifetimes without extrapolating efficiency maps outside their support.',
    ],
    'forward': [
        'Validate diffractive/elastic generation, rapidity-gap and forward-particle definitions.',
        'Bind beam optics, proton/forward acceptance and pileup assumptions where relevant.',
    ],
    'neutrino': [
        'Separate forward flux generation, transport, neutrino interactions and detector response.',
        'Validate flavor, target material, energy response and flux/interaction covariance.',
    ],
}
FEATURE_REQUIREMENTS = {
    'restframes': 'Pin RestFrames and test frame definitions and numerical boundaries on shared events.',
    'onnx': 'Pin ONNX model bytes, feature order, preprocessing, precision and runtime; compare classifier scores on fixed inputs.',
    'mva': 'Pin classifier weights and preprocessing; test feature ordering and classifier response.',
    'fastjet-contrib': 'Provision the exact FastJet contrib algorithms and validate grooming/substructure settings.',
    'smearing': 'Declare the actual smearing/efficiency functions and validate response; routine availability does not calibrate the detector.',
    'centrality': 'Acquire and verify the centrality calibration and its beam/energy validity.',
    'event-mixing': 'Preserve event-mixing populations, normalization and uncertainty correlations.',
    'heavy-ion': 'Inspect nuclear event metadata and normalization before using pp infrastructure.',
    'lifetime': 'Inspect the lifetime/vertex convention and preserve units and mother-daughter identity.',
    'tau-objects': 'Validate tau decay, polarization and identification conventions.',
    'large-r-jets': 'Validate large-R/groomed-jet constituents, tagging and calibration.',
}


def classify(row):
    """Conservative triage, not a manual paper review or proof of compatibility."""
    f=row['features']; meta=row.get('metadata',{})
    text=' '.join((row['name'],row['title'],str(meta.get('Keywords','')),str(meta.get('Beams','')))).lower()
    if row['experiment']=='FASER' or re.search(r'neutrino.*(?:flux|cross.section)',text):
        family='neutrino'
    elif 'calib' in text or row['name'].endswith('_CENTRALITY'):
        family='calibration'
    elif row['experiment'] in ('LHCf','TOTEM','ATLAS, ALFA','CMS, TOTEM'):
        family='forward'
    elif 'llp-domain' in f or re.search(r'disappearing|displaced|long.?lived',text):
        family='long-lived'
    elif set(f)&{'heavy-ion','heavy-ion-domain'}:
        family='heavy-ion'
    elif row['experiment'] in ('LHCf','TOTEM','ATLAS, ALFA','CMS, TOTEM') or 'forward-domain' in f:
        family='forward'
    elif row['framework']=='simpleanalysis' or re.search(r'\bsearch\b|supersymmetr|\bsusy\b',text):
        family='search-recast'
    elif 'flavour-domain' in f or (row['experiment']=='LHCb' and re.search(r'decay|branching|asymmetry',text)):
        family='flavour'
    else: family='fiducial-measurement'
    # Absence of a pattern is never evidence that the dependency is absent.
    return {'family':family, 'classification_basis':'automated conservative triage; manual paper and transitive-dependency review required'}


def summarize(catalog):
    rows=catalog['entries']
    return {'entries':len(rows),
            'by_framework':dict(sorted(Counter(r['framework'] for r in rows).items())),
            'by_experiment':dict(sorted(Counter(r['experiment'] for r in rows).items())),
            'by_family':dict(sorted(Counter(r['family'] for r in rows).items())),
            'upstream_status':dict(sorted(Counter(r['upstream_status'] for r in rows).items())),
            'with_source':sum(bool(r['source_files']) for r in rows),
            'with_reference_file':sum(bool(r['reference_files']) for r in rows),
            'with_model_index_match':sum(bool(r['model_index_matches']) for r in rows),
            'unique_atlas_analysis_ids':len({i for r in rows for i in r['analysis_ids']}),
            'unique_inspire_ids':len({r['inspire_id'] for r in rows if r['inspire_id']}),
            'new_physics_validations':0}


def _path(value):
    if not isinstance(value,str) or not value or '\\' in value:
        raise ValueError('invalid source path')
    p=PurePosixPath(value)
    if p.is_absolute() or '..' in p.parts or str(p)!=value:
        raise ValueError('source path must be normalized and relative')


def validate_catalog(catalog):
    if not isinstance(catalog,dict) or catalog.get('schema_version')!=SCHEMA_VERSION:
        raise ValueError('unsupported analysis catalogue schema')
    sources=catalog.get('sources',{})
    for key in ('rivet','simpleanalysis'):
        source=sources.get(key,{})
        if not re.fullmatch('[0-9a-f]{40}',source.get('revision','')):
            raise ValueError('catalogue needs exact upstream revisions')
        if not source.get('repository','').startswith('https://'):
            raise ValueError('catalogue needs HTTPS upstream URLs')
    rows=catalog.get('entries')
    if not isinstance(rows,list) or not rows: raise ValueError('empty or invalid catalogue')
    ids=set()
    for row in rows:
        if not isinstance(row,dict): raise ValueError('invalid catalogue row')
        framework=row.get('framework'); name=row.get('name')
        if framework not in ('rivet','simpleanalysis') or not isinstance(name,str) or not re.fullmatch(r'[A-Za-z0-9_]+',name):
            raise ValueError('invalid routine identity')
        identity=framework+':'+name
        if row.get('id')!=identity or identity in ids: raise ValueError('duplicate or inconsistent routine identity')
        ids.add(identity)
        if row.get('source_id')!=framework: raise ValueError('source identity mismatch')
        if row.get('physics_validated_by_ravel') is not False:
            raise ValueError('survey cannot confer physics validation')
        for key in ('source_files','reference_files','plot_files','analysis_ids','publication_urls','model_index_matches','metadata_issues'):
            if not isinstance(row.get(key),list): raise ValueError(f'{identity}: invalid {key}')
        for key in ('features','metadata'):
            if not isinstance(row.get(key),dict): raise ValueError(f'{identity}: invalid {key}')
        for key in ('experiment','title','upstream_status'):
            if not isinstance(row.get(key),str) or not row[key]: raise ValueError(f'{identity}: invalid {key}')
        facts=row['source_files']+row['reference_files']+row['plot_files']
        if 'metadata_file' in row: facts=facts+[row['metadata_file']]
        for asset in row.get('external_assets',[]): facts+=asset['matches']
        for fact in facts:
            _path(fact['path'])
            if not re.fullmatch('[0-9a-f]{40}',fact.get('git_blob','')): raise ValueError('invalid Git blob identity')
            if 'sha256' in fact and not re.fullmatch('[0-9a-f]{64}',fact['sha256']): raise ValueError('invalid source digest')
        if row.get('source_relation') not in ('direct','alias','unresolved'): raise ValueError('invalid source relation')
        if bool(row['source_files']) == (row['source_relation']=='unresolved'): raise ValueError('inconsistent source relation')
        if row.get('family')!=classify(row)['family']: raise ValueError('stale or invalid classification')
    expected=summarize(catalog)
    if catalog.get('summary')!=expected: raise ValueError('catalogue summary disagrees with entries')
    if sources['rivet'].get('selected_info_files') != expected['by_framework'].get('rivet',0):
        raise ValueError('Rivet source denominator mismatch')
    if sources['simpleanalysis'].get('registered_routines') != expected['by_framework'].get('simpleanalysis',0):
        raise ValueError('SimpleAnalysis source denominator mismatch')
    return catalog


def _unique_json(pairs):
    value={}
    for k,v in pairs:
        if k in value: raise ValueError('duplicate JSON key: '+k)
        value[k]=v
    return value


def load_catalog(path=None):
    raw=(Path(path).read_text() if path is not None else
         files('ravel').joinpath('data/analysis-catalog.json').read_text())
    return validate_catalog(json.loads(raw,object_pairs_hook=_unique_json,
        parse_constant=lambda x: (_ for _ in ()).throw(ValueError('non-finite JSON'))))


def search(catalog, query='', experiment=None, framework=None, family=None):
    if framework is not None and framework not in ('rivet','simpleanalysis'): raise ValueError('unknown framework')
    if family is not None and family not in FAMILIES: raise ValueError('unknown adaptation family')
    def matches(r):
        haystack=' '.join([r['id'],r['title'],*r['analysis_ids'],*r['publication_urls'],str(r['metadata'].get('References',''))]).casefold()
        return (all(t in haystack for t in query.casefold().split())
                and (experiment is None or experiment.casefold() in r['experiment'].casefold().split(', '))
                and (framework is None or framework==r['framework'])
                and (family is None or family==r['family']))
    return [r for r in catalog['entries'] if matches(r)]


def resolve(catalog, identity):
    token=identity.strip().casefold().rstrip('/')
    candidates=[]
    for row in catalog['entries']:
        aliases=[row['id'],row['name'],*row['analysis_ids'],*row['publication_urls']]
        aliases += ['ATLAS-'+x for x in row['analysis_ids']]
        if row['inspire_id']: aliases += ['ins'+row['inspire_id']]
        for url in row['publication_urls']:
            if '/abs/' in url: aliases += [url.rsplit('/',1)[-1], 'arxiv:'+url.rsplit('/',1)[-1]]
        if token in {x.casefold().rstrip('/') for x in aliases}: candidates.append(row)
    if len(candidates)!=1:
        names=', '.join(r['id'] for r in candidates)
        raise ValueError('ambiguous analysis identity; select a routine: '+names if candidates else 'analysis not in this snapshot; use analyses list or an explicit external admission review')
    return candidates[0]


def source_url(catalog,row,path):
    src=catalog['sources'][row['source_id']]
    return src['repository']+'/-/blob/'+src['revision']+'/'+path


def adaptation_packet(catalog,row):
    from .physics.native_capabilities import CAPABILITIES
    registered = CAPABILITIES.get(row['name']) if row['framework']=='simpleanalysis' else None
    if registered is not None:
        registered = json.loads(json.dumps(registered))
    requirements=list(COMMON_REQUIREMENTS)+FAMILY_REQUIREMENTS[row['family']]
    requirements += [message for feature,message in FEATURE_REQUIREMENTS.items() if feature in row['features']]
    blockers=[]
    if not row['source_files']: blockers.append('Source implementation unresolved in the pinned inventory.')
    if row['metadata_issues']: blockers += row['metadata_issues']
    if row['framework']=='rivet':
        requirements.append('Use a compatible Rivet 4/YODA 2 runtime for this snapshot; verify options, correlated subevents, negative weights and merge/finalize behavior.')
        blockers.append('No general fixed-event Rivet admission lifecycle has been scientifically validated by this catalogue.')
    elif not registered:
        blockers.append('No registered native full-chain adapter for this routine; assess the external SimpleAnalysis interface before porting.')
    else:
        blockers.append('Existing adapter registration has restricted models and statistical routes; no run or physics certificate is supplied here.')
    for asset in row.get('external_assets', []):
        if len(asset['matches']) != 1:
            blockers.append('Unresolved literal asset (external or dynamically constructed): ' + asset['literal'])
    if 'SINGLEWEIGHT' in row['upstream_status']:
        requirements.append('Upstream marks SINGLEWEIGHT: do not apply an unvalidated multiweight workflow.')
    if 'NOTREENTRY' in row['upstream_status'] or 'NOREENTRY' in row['upstream_status'] or str(row['metadata'].get('Reentrant', '')).lower() == 'false':
        requirements.append('No demonstrated reentrant finalize: validate merging unfinalized/raw objects; do not assume finalized files can be merged safely.')
    if row['model_index_matches']:
        requirements.append('Fetch and validate the exact indexed workspace and signal patch; index membership alone establishes neither format nor executability.')
    else:
        requirements.append('Statistical-model availability is unknown in this limited cross-index; inspect the paper and auxiliary resources without assuming absence.')
    if row.get('upstream_status') != 'VALIDATED':
        blockers.append('Upstream per-routine status is not unqualified VALIDATED; inspect its validation and intended use.')
    return {'schema_version':1,'kind':'analysis-adaptation-plan','analysis':row['id'],
            'catalogue_date':catalog['retrieved_at_utc'],'source_revision':catalog['sources'][row['source_id']]['revision'],
            'family':row['family'],'classification_basis':row['classification_basis'],
            'source_urls':[source_url(catalog,row,f['path']) for f in row['source_files']],
            'publication_urls':row['publication_urls'],'features_to_review':row['features'],
            'upstream_status':row['upstream_status'],'reference_files_present':len(row['reference_files']),
            'reference_content_verified':False,'probability_model_index_matches':row['model_index_matches'],
            'registered_native_adapter':registered, 'requirements':requirements,'blockers':blockers,
            'compute_authorized':False,'physics_validated':False,
            'next_action':'Resolve this adaptation plan against source and published references, then propose a bounded fixed-event validation with a concrete check-in.'}


def verify_source(catalog,row,root):
    """Read-only verification of a local checkout; no compilation or external commands from metadata."""
    root=Path(root).resolve(); issues=[]; checked=[]
    actual=subprocess.run(['git','-C',str(root),'rev-parse','HEAD'],capture_output=True,text=True)
    expected=catalog['sources'][row['source_id']]['revision']
    if actual.returncode or actual.stdout.strip()!=expected: issues.append('repository HEAD differs from catalogue revision or is not readable')
    facts=list(row['source_files'])
    if 'metadata_file' in row: facts.append(row['metadata_file'])
    for asset in row.get('external_assets',[]):
        if len(asset['matches'])!=1: issues.append('unresolved literal asset (external or dynamically constructed): '+asset['literal'])
        facts.extend(asset['matches'])
    if not row['source_files']: issues.append('no source implementation to verify')
    for fact in facts:
        _path(fact['path']); path=root/fact['path']
        if path.is_symlink() or not path.resolve().is_relative_to(root):
            issues.append('source is a symlink or escapes checkout: '+fact['path']); continue
        if not path.is_file(): issues.append('missing file: '+fact['path']); continue
        raw=path.read_bytes()
        oid=hashlib.sha1(b'blob '+str(len(raw)).encode()+b'\0'+raw).hexdigest()
        if oid!=fact['git_blob'] or ('sha256' in fact and hashlib.sha256(raw).hexdigest()!=fact['sha256']):
            issues.append('changed file: '+fact['path'])
        checked.append(fact['path'])
    return {'analysis':row['id'],'status':'FAIL' if issues else 'PASS','checked_files':checked,'issues':issues,
            'scope':'Selected routine source/metadata/literal assets only; not transitive dependencies, compilation, runtime ABI or physics.',
            'compute_authorized':False,'physics_validated':False}
