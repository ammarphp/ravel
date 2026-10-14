"""Source-only computational backend discovery and CheckMATE request preparation.

No upstream Python import, subprocess, install, inference, or execution authority.
The first route prepares the actual single-analysis CheckMATE parameter file and
imports its fixed-column numerical table. It does not implement CheckMATE again.
"""
from __future__ import annotations

import ast
import base64
from collections import Counter, defaultdict
import configparser
import hashlib
import io
import json
import math
from pathlib import Path, PurePosixPath
import re
import zlib

CM_REVISION = 'ee2eeab2d067124ab29f58a9e64825b8843a451e'
CM_252_REVISION = 'bacf9d17ff8e844e3b40851849e21f0dd0f0638c'
MA_REVISION = 'c2275a7967e75d7b78c4c385be9f232ef0fb2cc0'
PAD_REVISION = '181264d8a36a86f6aacc323bbd34a9abf3d09230'
CARDS = {
    'atlas7tev': 'delphes_skimmed_ATLAS.tcl',
    'atlas8tev': 'delphes_skimmed_ATLAS.tcl',
    'atlas13tev': 'delphes_skimmed_ATLAS_13TeV.tcl',
    'atlas14tev_projected': 'delphes_skimmed_ATLAS_14TeV.tcl',
    'atlas14tev_hl_flatbtagger': 'delphes_skimmed_ATLAS_14TeV.tcl',
    'cms7tev': 'delphes_skimmed_CMS.tcl',
    'cms8tev': 'delphes_skimmed_CMS.tcl',
    'cms13tev': 'delphes_skimmed_CMS_13TeV.tcl',
    'cms14tev_projected': 'delphes_skimmed_CMS_14TeV.tcl',
}
CM_ENGINE = (
    'tools/python/CheckMATE.in', 'tools/python/info.py',
    'tools/python/checkmate_core.py', 'tools/python/process.py',
    'tools/python/events.py', 'tools/python/detectorsettings.py',
    'tools/python/resultcollector.py', 'tools/python/evaluator.py',
    'tools/python/cls.py', 'tools/python/multibin_limit.py',
    'tools/python/multibin_limit_full.py', 'tools/python/spey_wrapper.py',
    'tools/python/hs3_wrapper.py', 'tools/fritz/src/main.cc',
    'tools/fritz/src/fritz/Fritz.cc', 'tools/fritz/src/global/EventFile.cc',
    'tools/fritz/src/delpheshandler/DelphesHandler.cc',
    'tools/analysis/src/base/AnalysisBase.cc',
)
COLUMNS = ('analysis', 'sr', 'o', 'b', 'db', 's', 'ds',
           's95obs', 's95exp', 'robscons', 'rexpcons')


def _sha(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


def read_json(path):
    def pairs(items):
        out = {}
        for key, value in items:
            if key in out:
                raise ValueError('duplicate JSON key: ' + key)
            out[key] = value
        return out
    return json.loads(Path(path).read_text(), object_pairs_hook=pairs,
                      parse_constant=lambda x: (_ for _ in ()).throw(ValueError(x)))


def _released_metadata(path):
    """Expose upstream json.loads last-key behavior plus every duplicate value."""
    duplicates = []
    def pairs(items):
        out = {}
        for key, value in items:
            if key in out:
                duplicates.append({'key': key, 'previous': out[key], 'effective': value})
            out[key] = value
        return out
    obj = json.loads(Path(path).read_text(), object_pairs_hook=pairs,
                     parse_constant=lambda x: (_ for _ in ()).throw(ValueError(x)))
    return obj, duplicates


def _fact(root, relative):
    p = PurePosixPath(relative)
    if p.is_absolute() or '..' in p.parts:
        raise ValueError('source path escapes root')
    root = Path(root).resolve()
    path = root / p
    # Reject a symlink at any relative component, including a missing target.
    if any(part.is_symlink() for part in [path, *path.parents] if part.is_relative_to(root)):
        raise ValueError('linked source input: ' + relative)
    if not path.is_file():
        return {'path': relative, 'status': 'missing'}
    with path.open('rb') as stream:
        first = stream.read(128)
    if first.startswith(b'version https://git-lfs.github.com/spec/v1'):
        return {'path': relative, 'status': 'lfs-pointer'}
    return {'path': relative, 'status': 'present', 'bytes': path.stat().st_size,
            'sha256': _sha(path)}


def verify_facts(root, facts):
    for fact in facts:
        if fact != _fact(root, fact['path']):
            raise ValueError('source or asset changed: ' + fact['path'])


def _assignment(path, target):
    tree = ast.parse(Path(path).read_text())
    found = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and any(
            isinstance(t, ast.Attribute) and t.attr == target for t in node.targets
        ):
            found.append(ast.literal_eval(node.value))
    if len(found) != 1:
        raise ValueError('cannot resolve released static ' + target)
    return found[0]


def checkmate_catalog(root, *, revision=CM_REVISION):
    """Use exactly Info.analysis_groups and active list lines, not all CC files."""
    root = Path(root).resolve()
    if revision not in (CM_REVISION,CM_252_REVISION):raise ValueError('unsupported explicit CheckMATE revision')
    if revision==CM_252_REVISION and (root/'VERSION').read_text().strip()!='2.5.2':raise ValueError('explicit2.5.2 source version required')
    engine=tuple('tools/python/CheckMATE.raw' if x=='tools/python/CheckMATE.in' else x for x in CM_ENGINE) if revision==CM_252_REVISION else CM_ENGINE
    groups = sorted(_assignment(root / 'tools/python/info.py', 'analysis_groups'))
    rows, seen, lists = [], set(), []
    for group in groups:
        listing = f'data/analysis_info/{group}_analyses.txt'
        lists.append(_fact(root, listing))
        for line in (root / listing).read_text().splitlines():
            # Deliberately match the actual get_all_checkmate_analyses reader.
            if line.startswith('#') or not line.strip():
                continue
            name = line.split()[0]
            if not re.fullmatch(r'[A-Za-z0-9_]+', name) or name in seen:
                raise ValueError('invalid/duplicate active CheckMATE routine')
            seen.add(name)
            meta_path = f'data/analysis_info/{group}/{name}_var.j'
            meta, duplicates = _released_metadata(root / meta_path)
            metadata_identity = meta.get('analysis')
            detector = CARDS.get(meta['experiment'])
            if detector is None:
                raise ValueError('unmapped upstream detector setup')
            paths = [meta_path, f'data/analysis_info/{group}/{name}_ref.dat',
                     f'tools/analysis/src/analyses/{group}/{name}.cc',
                     f'tools/analysis/include/analyses/{group}/{name}.h',
                     'data/cards/' + detector]
            cr_path = f'tools/analysis/src/analyses/{group}/{name}_CR.cc'
            if (root / cr_path).exists():
                paths.append(cr_path)
            # Entire analysis-local namespace is declared, not a literal-only scan.
            assets = sorted(p.relative_to(root).as_posix()
                            for p in (root / 'data' / name).rglob('*') if p.is_file())
            facts = [_fact(root, p) for p in paths]
            asset_paths = []
            conf_duplicates = []
            conf_path = f'data/{name}/pyhf_conf.json'
            if (root / conf_path).is_file():
                conf, conf_duplicates = _released_metadata(root / conf_path)
                for item in conf['analysis']:
                    for key in ('bkgonly', 'patchset'):
                        value = item.get(key)
                        if value:
                            relative = str(PurePosixPath('data') / name / 'Likelihoods' / value)
                            _fact(root, relative)  # Reject traversal immediately.
                            asset_paths.append(relative)
            rows.append({'id': 'checkmate:' + name, 'name': name, 'group': group,
                         'framework': 'checkmate', 'experiment': meta['experiment'],
                         'ecm_tev': float(meta['ecm']), 'luminosity_fb_inverse': float(meta['lumi']),
                         'detector_card': 'data/cards/' + detector,
                         'signal_regions': meta['signal_regions'],
                         'multibin_groups': meta.get('mb_signal_regions', {}),
                         'likelihood_label': meta.get('likelihoods'),
                         'expectation_known': meta.get('expectation_known') == 'y',
                         'facts': facts, 'asset_paths': sorted(set(assets + asset_paths)),
                         'listed_region_count': int(line.split()[1]),
                         'source_region_count': len(meta['signal_regions']),
                         'metadata_identity': metadata_identity,
                         'metadata_identity_match': metadata_identity == name,
                         'duplicate_metadata_keys': duplicates,
                         'duplicate_statistical_mapping_keys': conf_duplicates,
                         'scientific_coverage': False})
    return {'kind': 'computational-backend-catalogue', 'schema_version': 1,
            'framework': 'checkmate', 'root': str(root), 'revision': revision,
            'upstream_version':'2.5.2' if revision==CM_252_REVISION else '2.6.0',
            'revision_scope': 'Declared known layout; Git commit independently recorded by caller.',
            'engine_facts': [_fact(root, p) for p in engine], 'list_facts': lists,
            'entries': rows, 'active_routines': len(rows),
            'likelihood_labels': dict(Counter(str(r['likelihood_label']) for r in rows)),
            'multibin_routines': sum(bool(r['multibin_groups']) for r in rows),
            'served_tasks': None, 'scope': 'Discovery only; no runtime or scientific task execution.'}


def pad_catalog(root):
    """Read pinned PAD URL metadata. URLs are neither acquired files nor builds."""
    root = Path(root).resolve()
    rows, facts = [], []
    for stem, version in (('pad', 'v1.2'), ('padforma5tune', 'v1.1'), ('padforsfs', 'vSFS')):
        rel = f'src/pad_configuration/meta/{stem}_data.jz'
        raw = (root / rel).read_bytes()
        if len(raw) > 2 * 1024 * 1024:
            raise ValueError('PAD encoded metadata too large')
        lines = raw.decode().splitlines()
        if len(lines) != 2 or not lines[0].startswith('# Ma5 - PAD metadata created on'):
            raise ValueError('unknown PAD metadata framing')
        dec = zlib.decompressobj()
        data = dec.decompress(base64.b64decode(lines[1], validate=True), 16 * 1024 * 1024 + 1)
        if len(data) > 16 * 1024 * 1024 or not dec.eof or dec.unused_data:
            raise ValueError('PAD decoded metadata too large or trailing payload')
        metadata = json.loads(data)
        facts.append(_fact(root, rel))
        for row in metadata:
            rows.append({'id': 'madanalysis5:' + stem + ':' + row['name'],
                         'name': row['name'], 'framework': 'madanalysis5',
                         'database': stem, 'runtime_route': version,
                         'declared_pad_version': row['padversion'],
                         'minimum_ma5_metadata': row['ma5version'], 'gcc_metadata': row['gcc'],
                         'description': row['description'], 'asset_urls': row['url'],
                         'asset_acquisition': 'unverified', 'scientific_coverage': False})
    return {'kind': 'computational-backend-catalogue', 'schema_version': 1,
            'framework': 'madanalysis5', 'root': str(root), 'revision': PAD_REVISION,
            'madanalysis_revision': MA_REVISION, 'facts': facts, 'entries': rows,
            'catalogue_rows': len(rows), 'unique_names': len({r['name'] for r in rows}),
            'served_tasks': None, 'scope': 'Separate PAD metadata, not acquired PAD code or a runtime.'}


def resolve(catalogue, identity):
    rows = [r for r in catalogue['entries'] if identity in (r['id'], r['name'])]
    if len(rows) != 1:
        raise ValueError('unknown or ambiguous backend routine; use qualified identity')
    return rows[0]


def statistical_route(row, model, quantity):
    """Mirror released dispatch; expose capabilities, never substitute models."""
    if model not in ('simple', 'full', 'fullpyhf'):
        raise ValueError('explicit CheckMATE model required')
    if quantity not in ('region_table', 'multibin_cls', 'multibin_limits'):
        raise ValueError('unknown backend quantity')
    if not row['expectation_known']:
        raise ValueError('no expectation: selection-only source contract needed')
    if quantity == 'region_table':
        return {'engine': 'Evaluator.calc_r_values', 'multibin': 'none', 'model': model,
                'dependencies': ['numpy', 'scipy'],
                'semantics': 'Yield/error and conservative single-SR r values; these are not CLs.'}
    if not row['multibin_groups']:
        raise ValueError('analysis has no declared multibin groups')
    label = row['likelihood_label']
    if label == 'hs3':
        if model != 'full':
            raise ValueError('upstream overrides model with HS3; request full explicitly')
        if quantity == 'multibin_cls':
            raise ValueError('HS3 CLs are uncomputed placeholder 1 in this pin; request limits or qualify a derivative')
        return {'engine': 'hs3_wrapper.calc_workspace', 'multibin': 'detailed', 'model': model,
                'dependencies': ['ROOT>=6.32.14+XRooFit', 'numpy', 'pyhf', 'jsonpatch'],
                'semantics': 'XRooFit limits only; returned CLs placeholders must not be imported.'}
    if label == 'cov':
        engine, dependencies = 'spey_wrapper.calc_cov', ['spey', 'spey-pyhf', 'jax', 'pyhf']
        semantics = 'Source covariance approximation; not the full published likelihood.'
    elif model == 'simple':
        engine, dependencies = 'multibin_limit.calc_point', ['numpy', 'pyhf']
        semantics = 'Constructed simplified model; one shared histosys nuisance, not official full-model equivalence.'
    elif label == 'y':
        engine = 'spey_wrapper.calc_point' if model == 'full' else 'multibin_limit_full.calc_point'
        dependencies = ['spey', 'spey-pyhf', 'jax', 'pyhf'] if model == 'full' else ['pyhf', 'jsonpatch']
        semantics = 'Published background model plus generated signal patch; mapping/CR treatment still require validation.'
    else:
        # Released fullpyhf fallback mistakenly tests statcomb rather than statmod.
        raise ValueError('no supported full-model branch for this label/pin; no silent simplified fallback')
    return {'engine': engine, 'multibin': 'scan' if quantity == 'multibin_cls' else 'detailed',
            'model': model, 'dependencies': dependencies, 'semantics': semantics}



def effective_statistics(route):
    """Released CheckMATE's post-parser transition, not runtime observation.

    Detailed forces both CLs and observed/expected limits in checkmate_core;
    HS3 subsequently returns CLs placeholders and writes five expected limits.
    We retain the extra work rather than promising an observed-only endpoint.
    """
    detailed = route['multibin'] == 'detailed'
    scan = route['multibin'] == 'scan'
    hs3 = route['engine'] == 'hs3_wrapper.calc_workspace'
    return {'source_transition': 'checkmate_core.CheckMATE2.evaluate/statonly -> stateval',
            'observed_cls_requested_from_wrapper': detailed or scan,
            'observed_upper_limit_requested_from_wrapper': detailed,
            'expected_band_requested_from_wrapper': detailed,
            'returned_cls_computed': False if hs3 else None,
            'hs3_cls_placeholders_quarantined': hs3,
            'extra_work_vs_declared_quantity': detailed,
            'runtime_observed': False,
            'scope': ('Detailed computes/writes observed plus five expected limits; upstream HS3 CLs value1 is uncomputed.'
                      if hs3 else 'Scan forces observed CLs; detailed forces CLs and observed/expected limits; region-table disables multibin.')}


def _number(value, name, *, positive=False):
    if type(value) not in (int, float) or not math.isfinite(value) or value < 0 or positive and value == 0:
        raise ValueError(name + ' must be finite and ' + ('positive' if positive else 'nonnegative'))
    return value


def _native_path(value):
    path = Path(value)
    if not path.is_absolute() or not re.fullmatch(r'[A-Za-z0-9_./-]+', str(path)):
        raise ValueError('this upstream shell/config reader requires an absolute path without spaces/metacharacters')
    return path


def legacy_framing(path):
    """Producer version label does not select the actual event wire grammar."""
    with Path(path).open() as stream:
        lines=[]
        for line in stream:
            if line.strip():lines.append(line.strip())
            if len(lines)==2:break
    if len(lines)!=2 or not re.fullmatch(r'HepMC::Version [23]\.[0-9.]+',lines[0]) or lines[1]!='HepMC::IO_GenEvent-START_EVENT_LISTING':
        raise ValueError('declared legacy IO_GenEvent wire grammar differs from supplied framing')
    return {'producer_header':lines[0],'wire_grammar':'HepMC2 IO_GenEvent','native_parse_observed':False}

def prepare_checkmate(catalogue, request, out):
    """Materialize a real parameter file. Missing runtime remains an explicit blocker.

    Only pre-showered HepMC2 is implemented here. LHE implies a new Pythia stage;
    generic Delphes ROOT needs an independently bound detector-origin contract.
    Both remain route obligations, rather than silently applying physics defaults.
    """
    required = {'routine', 'events', 'format', 'max_events', 'cross_section_fb',
                'cross_section_error_fb', 'random_seed', 'model', 'quantity',
                'output_parent', 'name', 'weight_convention', 'runtime'}
    if not isinstance(request, dict) or set(request) != required:
        raise ValueError('exact provider request fields required')
    row = resolve(catalogue, request['routine'])
    if request['format'] != 'hepmc2':
        raise ValueError('only pre-showered HepMC2 route; LHE/shower, HepMC3 conversion, ROOT detector origin need separate contracts')
    for key in ('max_events', 'random_seed'):
        if type(request[key]) is not int or request[key] <= 0:
            raise ValueError(key + ' must be a positive integer')
    if not isinstance(request['weight_convention'], str) or not request['weight_convention'].strip():
        raise ValueError('explicit weight convention required')
    if not re.fullmatch('[A-Za-z0-9_-]+', request['name']):
        raise ValueError('safe run name required')
    event = request['events']
    if not isinstance(event, dict) or set(event) != {'path', 'sha256'}:
        raise ValueError('event pin required')
    path = _native_path(event['path'])
    if path.is_symlink() or not path.is_file() or _sha(path) != event['sha256']:
        raise ValueError('event input is missing, linked or changed')
    legacy_framing(path)
    if path.suffix.lower() != '.hepmc':
        raise ValueError('released input parser requires .hepmc for HepMC events')
    parent = _native_path(request['output_parent'])
    if (parent / request['name']).exists():
        raise ValueError('native output already exists; never overwrite or merge')
    route = statistical_route(row, request['model'], request['quantity'])
    if request['quantity'] != 'region_table' and row['duplicate_statistical_mapping_keys']:
        raise ValueError('released statistical map has duplicate keys; qualify an explicit mapping derivative before inference')
    root = Path(catalogue['root'])
    verify_facts(root, catalogue['engine_facts'] + catalogue['list_facts'] + row['facts'])
    paths = row['asset_paths'] if request['quantity'] != 'region_table' else [
        p for p in row['asset_paths'] if not '/Likelihoods/' in p and not p.endswith('pyhf_conf.json')]
    # Read complete declared analysis-local assets at preparation, including ML
    # preprocessing/models, rather than treating a source include as consumption.
    asset_facts = [_fact(root, p) for p in paths]
    missing = [f['path'] for f in row['facts'] + asset_facts if f['status'] != 'present']
    runtime = request['runtime']
    runtime_facts, native_command = [], None
    blockers = ['Runtime build, configured installation layout and loaded libraries are unqualified.']
    if route['multibin']=='detailed':
        blockers.append('Released detailed dispatch forces extra CLs and expected-limit work; future inference must budget the complete effective scope.')
    if runtime is not None:
        if not isinstance(runtime, dict) or set(runtime) != {'executable', 'fritz', 'manifest'}:
            raise ValueError('runtime needs exact executable, fritz and build/loaded-closure manifest pins')
        for pin in runtime.values():
            p = _native_path(pin['path'])
            if set(pin) != {'path', 'sha256'} or p.is_symlink() or not p.is_file() or _sha(p) != pin['sha256']:
                raise ValueError('runtime pin changed')
            runtime_facts.append(pin)
        native_command = [runtime['executable']['path'], str(Path(out).resolve() / 'checkmate.ini')]
        # Existence/hash is still not runtime consumption or build qualification.
    else:
        blockers.append('No installed CheckMATE executable/fritz/closure supplied.')
    if missing:
        blockers.append('Missing/LFS assets: ' + ', '.join(missing))
    config = configparser.ConfigParser(interpolation=None)
    config['Parameters'] = {
        'Name': request['name'], 'Analyses': row['name'], 'OutputDirectory': str(parent),
        'OutputExists': 'ask', 'SkipParamCheck': 'true', 'RandomSeed': str(request['random_seed']),
        'Multibin': route['multibin'], 'Model': route['model'], 'Backend': 'numpy',
        'Cls': str(request['quantity'] == 'multibin_cls').lower(),
        'Uplim': str(request['quantity'] == 'multibin_limits').lower(),
        'Expected': 'false',
        'TotalResultFileColumns': ','.join(COLUMNS), 'No_MC_Stat_Err': 'false',
        'WriteDelphesEvents': 'true', 'WritePythiaEvents': 'false',
    }
    config['supplied'] = {'Events': str(path), 'MaxEvents': str(request['max_events']),
                          'XSect': str(_number(request['cross_section_fb'], 'cross section', positive=True)) + '*FB',
                          'XSectErr': str(_number(request['cross_section_error_fb'], 'cross section error')) + '*FB'}
    stream = io.StringIO(); config.write(stream)
    result = {'kind': 'backend-provider-preparation', 'schema_version': 1,
              'upstream_revision': catalogue['revision'], 'routine': row['id'],
              'request': request, 'statistical_route': route,
              'requested_statistics': {'observed_cls': request['quantity'] == 'multibin_cls',
                  'observed_upper_limit': request['quantity'] == 'multibin_limits',
                  'expected_band': False},
              'effective_statistics': effective_statistics(route),
              'source_facts': catalogue['engine_facts'] + catalogue['list_facts'] + row['facts'],
              'asset_facts': asset_facts, 'runtime_facts': runtime_facts,
              'native_command': native_command, 'native_output': str(parent / request['name']),
              'expected_outputs': ['analysis/', 'fritz/', 'delphes/', 'evaluation/total_results.txt', 'result.txt']
                + (['multibin_limits/results.dat'] if route['multibin'] != 'none' else []),
              'blockers': blockers, 'executed': False, 'scientific_coverage': False,
              'scope': 'Actual upstream input syntax preparation only; ordinary study integration, runtime and output qualification pending.'}
    out = Path(out); out.mkdir(parents=True, exist_ok=False)
    (out / 'checkmate.ini').write_text(stream.getvalue())
    result['configuration_sha256'] = hashlib.sha256((out / 'checkmate.ini').read_bytes()).hexdigest()
    (out / 'provider-preparation.json').write_text(json.dumps(result, indent=2, allow_nan=False) + '\n')
    return result


def import_region_table(path, row):
    """Retain all native row values; no clipping, CLs alias, inferred covariance."""
    raw = Path(path).read_bytes()
    lines = [line.split() for line in raw.decode().splitlines() if line.strip()]
    if not lines or tuple(lines[0]) != COLUMNS:
        raise ValueError('native table header differs from declared upstream columns')
    rows, seen = [], set()
    for values in lines[1:]:
        if len(values) != len(COLUMNS) or values[0] != row['name'] or values[1] in seen:
            raise ValueError('wrong analysis, duplicate or incomplete table row')
        seen.add(values[1]); numbers = [float(v) for v in values[2:]]
        if not all(math.isfinite(n) for n in numbers):
            raise ValueError('nonfinite native output')
        rows.append(dict(zip(COLUMNS, [*values[:2], *numbers])))
    if seen != set(row['signal_regions']):
        raise ValueError('complete native signal-region census required')
    return {'kind': 'native-backend-table-import', 'schema_version': 1, 'routine': row['id'],
            'table_sha256': hashlib.sha256(raw).hexdigest(), 'rows': rows,
            'cls': None, 'covariance': None, 'physics_validated': False,
            'scope': 'Source-column numerical import; r_obs_cons is not observed CLs and rows are not joint-independent bins.'}


def paper_join(ravel_catalogue, cm_catalogue, supplied_aliases=(), other_catalogues=()):
    """Join explicit paper identities, keeping routines distinct and unresolved."""
    groups = defaultdict(list)
    unresolved = []
    known = {r['id'] for c in (ravel_catalogue, cm_catalogue, *other_catalogues) for r in c['entries']}
    for row in ravel_catalogue['entries']:
        def references(value):
            if isinstance(value, str):
                return [value]
            if isinstance(value, list) and all(isinstance(v, str) for v in value):
                return value
            raise ValueError('publication references must be text or a list of text')
        refs = references(row.get('publication_urls', [])) + references(row.get('metadata', {}).get('References', []))
        ids = set(re.findall(r'(?:arxiv\s*:\s*|arxiv.org/abs/)(\d{4}\.\d{4,5})', ' '.join(refs), re.I))
        if len(ids) == 1:
            groups['arxiv:' + ids.pop()].append(row['id'])
        else:
            unresolved.append(row['id'])
    for row in cm_catalogue['entries']:
        match = re.fullmatch(r'(?:atlas|cms)_(\d{4})_(\d{4,5})', row['name'])
        if match:
            groups['arxiv:' + '.'.join(match.groups())].append(row['id'])
        else:
            unresolved.append(row['id'])
    unresolved.extend(r['id'] for c in other_catalogues for r in c['entries'])
    # PAD ATLAS-SUSY identifiers require a separately sourced alias; no fuzzy
    # topic/name matching and no implication of equivalent object/stat contracts.
    for alias in supplied_aliases:
        if set(alias) != {'paper', 'routine', 'source_pin'} or not re.fullmatch(r'arxiv:\d{4}\.\d{4,5}', alias['paper']):
            raise ValueError('explicit sourced paper alias required')
        if alias['routine'] not in known:
            raise ValueError('alias routine is not in a supplied catalogue')
        pin = alias['source_pin']
        if not isinstance(pin, dict) or set(pin) != {'path', 'sha256'}:
            raise ValueError('alias requires exact supporting source bytes')
        path = Path(pin['path'])
        if path.is_symlink() or not path.is_file() or _sha(path) != pin['sha256']:
            raise ValueError('alias supporting source changed')
        groups[alias['paper']].append(alias['routine'])
        unresolved = [identity for identity in unresolved if identity != alias['routine']]
    shared = {k: sorted(set(v)) for k, v in sorted(groups.items())
              if len({x.split(':')[0] for x in v}) > 1}
    return {'kind': 'paper-identity-join', 'schema_version': 1, 'shared_papers': shared,
            'shared_paper_count': len(shared), 'unresolved': sorted(unresolved),
            'observed_paper_keys': len(groups),
            'supplied_aliases': list(supplied_aliases),
            'served_tasks': None, 'scientific_equivalence': False,
            'scope': 'Paper identity join only. Different revisions, selections, detector/weight/statistics contracts remain distinct.'}


def main(argv=None):
    """Runnable source/preparation tools; there is deliberately no launch command."""
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    actions = parser.add_subparsers(dest='action', required=True)
    discovery = actions.add_parser('catalogue')
    discovery.add_argument('--backend', choices=['checkmate', 'pad'], required=True)
    discovery.add_argument('--source', required=True)
    discovery.add_argument('--out', required=True)
    discovery.add_argument('--source-revision',choices=[CM_REVISION,CM_252_REVISION],default=CM_REVISION)
    prepare = actions.add_parser('prepare-checkmate')
    prepare.add_argument('--catalogue', required=True)
    prepare.add_argument('--request', required=True)
    prepare.add_argument('--out', required=True)
    table = actions.add_parser('import-region-table')
    table.add_argument('--catalogue', required=True)
    table.add_argument('--routine', required=True)
    table.add_argument('--table', required=True)
    table.add_argument('--out', required=True)
    args = parser.parse_args(argv)
    if args.action == 'prepare-checkmate':
        prepare_checkmate(read_json(args.catalogue), read_json(args.request), args.out)
        print(Path(args.out).resolve() / 'provider-preparation.json')
        return 0
    if args.action == 'catalogue':
        result = checkmate_catalog(args.source,revision=args.source_revision) if args.backend=='checkmate' else pad_catalog(args.source)
    else:
        catalogue = read_json(args.catalogue)
        result = import_region_table(args.table, resolve(catalogue, args.routine))
    target = Path(args.out)
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open('x') as stream:
        stream.write(json.dumps(result, indent=2, allow_nan=False) + '\n')
    print(target.resolve())
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
