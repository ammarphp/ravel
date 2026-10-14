"""Ntuple inventory→nominal kernel→ROOT-stream preparation for an analysis task.

The caller supplies the task's requirement roster, target families and ordered
stage list; the research portfolio covers exactly those. Never resolves Rucio,
reads credentials or ROOT payloads, runs Snakemake, fits backgrounds or submits
results. Preparation is an actionable partial capability; complete physics and
manuscript closure remain separate stages.
"""
from copy import deepcopy
import hashlib
import re
from pathlib import Path
from urllib.parse import urlsplit
from ravel.physics import root_stream, root_stream_core as c, columnar_ntuple_recipe as h

SCOPE = 'source_bound_input_and_kernel_preparation'
FIELDS = ('schema_version', 'original_goal', 'goal_binding', 'requirements', 'inventory',
          'recipe', 'branches', 'resolved_members', 'sample_definitions', 'site_runtime',
          'review_policy', 'assumptions', 'portfolio')


def _identities(value, what):
    c.require(type(value) is list and value and all(type(x) is str and x.strip() for x in value) and
              len(set(value)) == len(value), 'nonempty unique ' + what + ' required')
    return list(value)


def roster(document, *, complete=True):
    """Supplied task roster: requirements, and for a whole task its families and stages."""
    allowed = {'requirements', 'target_families', 'stages'}
    c.require(type(document) is dict and 'requirements' in document and set(document) <= allowed and
              (not complete or set(document) == allowed), 'supplied requirement roster required')
    rows = document['requirements']
    c.require(type(rows) is list and all(type(r) is dict for r in rows), 'requirement rows required')
    result = {'requirements': _identities([r.get('id') for r in rows], 'requirement identities')}
    for key in ('target_families', 'stages'):
        if key in document:
            result[key] = _identities(document[key], key.replace('_', ' '))
    return result


def validate(task):
    c.keys(task, ('request',), 'ntuple inventory task'); c.pin(task['request']); return task


def inventory(value):
    c.require(type(value) is list and 1 <= len(value) <= 1000000, 'complete inventory required')
    dids, guids = set(), set()
    for row in value:
        c.keys(row, ('did', 'guid', 'adler32', 'display_size', 'events'), 'supplied inventory row')
        c.require(type(row['did']) is str and re.fullmatch('[A-Za-z0-9_.-]+:[A-Za-z0-9_.-]+', row['did']), 'literal scoped file DID required')
        c.require(type(row['guid']) is str and re.fullmatch('[A-Fa-f0-9]{8}(?:-[A-Fa-f0-9]{4}){3}-[A-Fa-f0-9]{12}', row['guid']), 'literal GUID required')
        c.require(row['did'] not in dids and row['guid'].lower() not in guids, 'duplicate original member refused')
        dids.add(row['did']); guids.add(row['guid'].lower())
        c.require(type(row['adler32']) is str and re.fullmatch('ad:[0-9a-f]{8}', row['adler32']), 'supplied Adler32 token required')
        c.text(row['display_size']); c.integer(row['events'], 0, 10**15, 'inventory event count')
    return deepcopy(value)


def _load(task, base):
    validate(task); cap = c.Capture(); path, raw = cap.read(task['request'], base)
    d = c.strict(raw); c.keys(d, FIELDS, 'ntuple inventory request')
    c.require(type(d['schema_version']) is int and d['schema_version'] == 1, 'request schema1 required')
    def bound(pin, limit=8*1024**2):
        p, _ = cap.read(pin, path.parent, limit)
        return {**pin, 'path': str(p)}
    for key in ('original_goal', 'requirements', 'inventory', 'recipe', 'branches', 'review_policy', 'portfolio'):
        c.pin(d[key]); d[key] = bound(d[key])
    cap.read(d['original_goal'], path.parent)
    requirement = cap.document(d['requirements'], path.parent)
    task_roster = roster(requirement)
    rows = inventory(cap.document(d['inventory'], path.parent))
    recipe = h.validate_recipe(cap.document(d['recipe'], path.parent))
    cap.columnar_selection = None
    if recipe['schema_version'] == 2:
        from ravel.physics import columnar_selection as selection
        recipe_path, _ = cap.read(d['recipe'], path.parent)
        recipe, compiled, tracker = selection.rebase_recipe(recipe, recipe_path.parent, cap)
        cap.columnar_selection = (compiled, tracker)
    for row in recipe['sf_applicability']: row['source'] = bound(row['source'])
    if 'fitted_categories' in recipe:
        recipe['fitted_categories']['source'] = bound(recipe['fitted_categories']['source'])
    branches = cap.document(d['branches'], path.parent)
    c.require(type(branches) is list and len(branches) <= 1024 and
              len({b['name'] for b in branches}) == len(branches) and
              {b['name'] for b in branches} == set(h.required_branches(recipe)), 'exact complete needed branch schema required')
    flags = selection.bit_branches(recipe) if recipe['schema_version'] == 2 else h.bit_branches(recipe)
    for b in branches:
        c.keys(b, ('name', 'shape', 'dtype', 'unit'), 'ntuple branch')
        c.require(b['dtype'] in ('float32', 'float64', 'int8', 'uint8', 'int32', 'uint32', 'int64', 'uint64', 'bool'), 'literal primitive branch type required')
        if recipe['schema_version'] == 2:
            expected_shape, expected_unit = selection.branch_description(recipe, compiled['request'], b['name'])
        else:
            expected_shape, expected_unit = h.branch_description(recipe, b['name'])
        c.require(b['shape'] == expected_shape, 'native scalar/object shape differs')
        if expected_unit is None:
            c.require(type(b['unit']) is str and b['unit'].strip() and
                      b['unit'] not in ('unknown', 'unqualified'),
                      'known native auxiliary needs an explicit source-bound unit; none is inferred')
        else:
            c.require(b['unit'] == expected_unit, 'native source unit differs')
        if b['name'] in flags: c.require(b['dtype'] in ('int8', 'uint8', 'int32', 'bool'), 'native bit field type differs')
        if b['name'] in ('year', 'mcChannelNumber'): c.require(b['dtype'] == 'uint32', 'native event integer type differs')
    portfolio = cap.document(d['portfolio'], path.parent)
    c.keys(portfolio, ('schema_version', 'stages', 'prepared_stages', 'target_families', 'missing_scientific_inputs'), 'whole research portfolio')
    c.require(type(portfolio['schema_version']) is int and portfolio['schema_version'] == 2 and
              type(portfolio['target_families']) is list and
              sorted(portfolio['target_families']) == sorted(task_roster['target_families']) and
              len(set(portfolio['target_families'])) == len(portfolio['target_families']),
              'portfolio target families must equal the requested families')
    stages = portfolio['stages']
    c.require(type(stages) is list and all(type(s) is dict for s in stages) and
              [s.get('id') for s in stages] == task_roster['stages'], 'complete ordered requested stages required')
    prepared = _identities(portfolio['prepared_stages'], 'prepared stages')
    c.require(set(prepared) <= set(task_roster['stages']), 'prepared stages must be requested stages')
    for s in stages:
        c.keys(s, ('id', 'request', 'missing'), 'research stage')
        c.require(type(s['missing']) is list, 'explicit unresolved stage obligations required')
        if s['request'] is not None: s['request'] = bound(s['request'])
    c.require(type(portfolio['missing_scientific_inputs']) is list, 'full unresolved scientific inputs required')
    cap.read(d['review_policy'], path.parent)
    c.require(type(d['assumptions']) is list and d['assumptions'], 'declared physics assumptions required')
    c.require(type(d['goal_binding']) is dict, 'whole-question goal binding required')
    optional = {}
    for name in ('resolved_members', 'sample_definitions', 'site_runtime'):
        optional[name] = None if d[name] is None else cap.document(d[name], path.parent)
    if optional['resolved_members'] is not None:
        c.require(type(optional['resolved_members']) is list, 'complete resolved members required')
        for member in optional['resolved_members']: member['source'] = bound(member['source'])
    if optional['sample_definitions'] is not None:
        c.require(type(optional['sample_definitions']) is list, 'complete sample definitions required')
        for sample in optional['sample_definitions']:
            c.keys(sample, ('id', 'dsid', 'kind', 'process', 'normalization'), 'declared sample')
            if sample['normalization'] is not None:
                n = sample['normalization']; n['source'] = bound(n['source']); n['original_population'] = bound(n['original_population'])
        if cap.columnar_selection is not None:
            c.require({s['dsid'] for s in optional['sample_definitions']} <= set(compiled['request']['sample_dsids']),
                      'joint response must serve every original supplied MC sample; no omitted DSID')
    cap.inventory_runtime_assets = {}
    if optional['site_runtime'] is not None:
        site = optional['site_runtime']; c.keys(site, ('runtime', 'site', 'limits'), 'site/runtime')
        rt = site['runtime']; rt['python'] = bound(rt['python'], 64*1024**2)
        for tree in rt['trees']:
            tree['manifest'] = bound(tree['manifest'], 32*1024**2)
            tree['root'] = str(root_stream.custody._ordinary(tree['root'], path.parent, directory=True))
        rt['site_roots'] = [str(root_stream.custody._ordinary(p, path.parent, directory=True)) for p in rt['site_roots']]
        assets, _, _, _ = root_stream.runtime({'runtime': rt}, path.parent, cap)
        cap.inventory_runtime_assets = assets
    cap.finish()
    return path, d, rows, recipe, branches, portfolio, optional, cap


def inputs(task, base):
    *_, cap = _load(task, base); cap.finish()
    root_stream.custody.asset_check(cap.inventory_runtime_assets)
    return sorted({*cap.rows, *map(Path, cap.inventory_runtime_assets)})


def execution_seconds(task, base):
    _load(task, base); return 60


def goal_inputs(spec, base):
    _, d, *_, cap = _load(spec['task'], base)
    c.require(spec.get('schema_version') == 2 and spec.get('goal_binding') == d['goal_binding'], 'ordinary producer must retain original goal binding')
    cap.finish()


def validate_scope(spec):
    p = spec.get('review_policy', {}).get('policy', {})
    c.require(spec.get('schema_version') == 2 and spec.get('max_attempts') == 1 and
              p.get('max_redos') == 0 and set(p.get('claim_scopes', {})) == {SCOPE} and
              p['claim_scopes'][SCOPE].get('actions') == ['delivery'], 'one-attempt preparation delivery only')
    return spec


def context_inputs(task, base):
    # Context consumes bounded source documents. Runtime binary identities are
    # admitted by ordinary task planning, not copied into a model tool context.
    *_, cap = _load(task, base)
    cap.finish()
    return sorted(p for p in cap.rows if p not in {Path(x) for x in cap.inventory_runtime_assets})


def context(task, base):
    _, d, rows, recipe, branches, portfolio, optional, cap = _load(task, base)
    requirement = cap.document(d['requirements'], base)
    cap.finish()
    return {'schema_version': 1, 'kind': 'ntuple-inventory-source-context', 'inventory_files': len(rows),
            'inventory_events': sum(r['events'] for r in rows), 'recipe': recipe, 'branches': branches,
            'portfolio': portfolio, 'requirements': d['requirements'], 'requirements_document': requirement,
            'original_goal_source': d['original_goal'], 'goal_binding': d['goal_binding'],
            'missing_external_inputs': [key for key, value in optional.items() if value is None],
            'changed_selection_response': None if cap.columnar_selection is None else cap.columnar_selection[0],
            'next_ordinary_mode': 'ntuple-inventory', 'downstream_mode': 'root-stream',
            'execution_authorized': False, 'original_task_complete': False, 'physics_validated': False}


def join_members(rows, resolved, definitions, authority):
    """No PFN, exact byte size, tree entries, campaign or process is guessed."""
    c.require(type(resolved) is list and len(resolved) == len(rows), 'all original file identities must resolve')
    c.require(type(definitions) is list and definitions, 'explicit whole sample population required')
    samples = {}; uris = set()
    for d in definitions:
        c.keys(d, ('id', 'dsid', 'kind', 'process', 'normalization'), 'sample definition')
        c.require(d['id'] not in samples and d['kind'] in ('signal_mc', 'background_mc'), 'explicit distinct MC sample identity required')
        samples[d['id']] = {**deepcopy(d), 'members': []}
    for i, (original, member) in enumerate(zip(rows, resolved)):
        c.keys(member, ('did', 'guid', 'adler32', 'inventory_events', 'analysis_entries', 'size_bytes', 'uri', 'sample', 'source'), 'resolved original member')
        c.require({k: member[k] for k in ('did', 'guid', 'adler32')} == {k: original[k] for k in ('did', 'guid', 'adler32')} and
                  member['inventory_events'] == original['events'], 'literal original inventory association/order differs')
        c.pin(member['source']); c.integer(member['analysis_entries'], 0, 10**15, 'separately observed analysis-tree entries')
        c.integer(member['size_bytes'], 1, 10**15, 'exact observed bytes; rounded display size is not evidence')
        c.require(member['sample'] in samples and member['uri'] not in uris, 'exact sample and distinct PFN required')
        sample = samples[member['sample']]; match = re.search(r'\.(\d{6})\.', original['did'].split(':', 1)[1])
        c.require(match is not None and sample['dsid'] == int(match.group(1)), 'DSID source association differs')
        u = urlsplit(member['uri']); c.require(u.scheme == 'root' and u.hostname and not (u.username or u.password or u.query or u.fragment), 'unsigned remote ROOT PFN required')
        uris.add(member['uri'])
        sample['members'].append({'id': 'file_%06d' % i, 'did': original['did'], 'guid': original['guid'],
            'uri': member['uri'], 'tree': 'analysis', 'entries': member['analysis_entries'], 'size_bytes': member['size_bytes'],
            'checksum': {'algorithm': 'adler32', 'value': original['adler32'][3:], 'authority': member['source']}})
    c.require(all(s['members'] for s in samples.values()), 'unused/omitted declared sample refused')
    return c.dataset({'schema_version': 1, 'membership_authority': authority,
                      'ordering': 'declared_sample_member_source_entry', 'samples': list(samples.values())})


def _approved(task, out):
    from ravel.workflow import science
    for rd in (out, *out.parents):
        if (rd / science.PLAN).is_file():
            plan = science.verify_worker(rd); spec = science.execution_spec(rd); validate_scope(spec)
            c.require(spec['mode'] == 'ntuple-inventory' and spec['task'] == task and
                      out == (rd / plan['output_directory'] / 'ntuple-inventory').absolute(), 'actual admitted preparation destination differs')
            return
    raise ValueError('ordinary approved ntuple inventory worker required')


def run(task, base, output):
    out = Path(output).absolute(); _approved(task, out)
    path, d, rows, recipe, branches, portfolio, optional, cap = _load(task, base)
    c.require(not out.exists() and '..' not in out.parts and not any(p.is_symlink() for p in (out, *out.parents)), 'fresh ordinary preparation destination required')
    c.require(not any(out == p or out.is_relative_to(p.parent) for p in cap.rows), 'output must be disjoint from original input directories')
    out.mkdir(parents=True)
    emitted = []
    def publish(name, value):
        pin = root_stream.write_new(out / name, value); emitted.append(pin); return pin
    invpin = publish('original-inventory.json', rows)
    portfolio_pin = publish('whole-research-portfolio.json', portfolio)
    recipe_pin = publish('kernel-recipe.json', recipe)
    missing = [key for key, value in optional.items() if value is None]
    kernel = None; bundle_files = {}; response_pin = None
    if cap.columnar_selection is not None:
        from ravel.physics import columnar_selection as selection
        compiled, tracker = cap.columnar_selection
        response_pin = publish('joint-response-preparation.json', compiled)
        if not compiled['ready']:
            missing.extend(compiled['missing']); kernel_raw = None
        else:
            kernel_raw = selection.kernel_bytes(recipe, compiled)
            bundle_files = selection.publish_dependencies(tracker, out, emitted)
    else:
        kernel_raw = h.kernel_bytes(recipe)
    if kernel_raw is not None:
        kernel_path = out / 'kernel.py'
        with kernel_path.open('xb') as handle: handle.write(kernel_raw)
        kernel = {'path': str(kernel_path), 'sha256': hashlib.sha256(kernel_raw).hexdigest(), 'size': len(kernel_raw)}
        emitted.append(kernel); bundle_files['kernel.py'] = kernel
        root_stream.custody.asset_check({kernel['path']: kernel})
    if optional['sample_definitions'] is not None:
        missing.extend('full_normalization:' + row['id'] for row in optional['sample_definitions'] if row['normalization'] is None)
    prepared = None
    if not missing:
        resolved = optional['resolved_members']
        for member in resolved: cap.read(member['source'], path.parent)
        # Placeholder authority is replaced before a document is delivered.
        ds = join_members(rows, resolved, optional['sample_definitions'], d['inventory'])
        authority = publish('root-membership.json', {'schema_version': 1, 'samples': ds['samples']})
        ds['membership_authority'] = authority; ds_pin = publish('root-dataset.json', ds)
        analysis = h.analysis_document(recipe, branches, d['original_goal'], kernel)
        c.analysis(analysis, ds); analysis_pin = publish('root-analysis.json', analysis)
        c.keys(optional['site_runtime'], ('runtime', 'site', 'limits'), 'site/runtime')
        cfg = c.config({'schema_version': 1, 'dataset': ds_pin, 'analysis': analysis_pin,
            'bundle': {'entry': 'kernel.py', 'blind_entry': None, 'files': bundle_files, 'review_source': recipe_pin}, **optional['site_runtime']})
        config_pin = publish('root-config.json', cfg)
        policy = cap.document(d['review_policy'], path.parent)
        root_policy = deepcopy(policy)
        # A caller supplies separate scope policies; preparation does not extend
        # its own authority to processing, background inference or the note.
        c.require(set(root_policy['policy']['claim_scopes']) == {root_stream.SCOPE}, 'downstream explicit ROOT delivery policy required')
        spec = {'schema_version': 2, 'mode': 'root-stream', 'source': 'Complete source-bound ntuple analysis with declared nominal-only corrections',
            'assumptions': d['assumptions'], 'max_seconds': cfg['limits']['max_seconds'], 'max_attempts': 1,
            'approval_mode': 'physicist', 'review_policy': root_policy, 'goal_binding': d['goal_binding'], 'task': {'config': config_pin}}
        root_stream.validate_scope(spec)
        from ravel.workflow import science
        science.validate(spec)
        # Invoke existing transitive admission; runtime and full denominator
        # evidence are checked here rather than asserting readiness from pins.
        root_stream.inputs(spec['task'], out)
        prepared = publish('root-science.json', spec)
    result = {'schema_version': 1, 'kind': 'ntuple-inventory-and-kernel-preparation', 'status': 'passed', 'status_scope': SCOPE,
              'inventory': invpin, 'inventory_files': len(rows), 'inventory_events': sum(r['events'] for r in rows),
              'inventory_events_are_analysis_tree_entries': False, 'kernel': kernel, 'kernel_recipe': recipe_pin, 'portfolio': portfolio_pin,
              'joint_response_preparation': response_pin,
              'root_specification': prepared, 'execution_ready': prepared is not None,
              'missing_external_inputs': missing, 'remaining_stages': [s for s in portfolio['stages'] if s['id'] not in portfolio['prepared_stages']],
              'missing_scientific_inputs': portfolio['missing_scientific_inputs'],
              'original_task_complete': False, 'execution_authorized': False, 'physics_validated': False,
              'root_data_accesses': 0, 'fits': 0, 'input_pins': list(cap.rows.values()),
              'limitations': ['Declared conditional SF products are not WP/trigger/calibration qualification.',
                'Nominal-only regions and event common-weight moments are not a validated background law or discovery sensitivity.',
                'RSE PFNs and checksums are metadata; remote byte snapshot and credential validity require actual site execution.',
                'Future signal availability for each target family is retained separately from missing code and current inputs.']}
    publish('ntuple-inventory-preparation.json', result); cap.finish()
    root_stream.custody.asset_check(cap.inventory_runtime_assets)
    root_stream.custody.asset_check({p['path']: p for p in emitted})
    return result


def write_report(result, out):
    root_stream.write_new(Path(out) / 'ntuple-inventory-report.json', result)
    return [{'stem': 'ntuple-inventory-report', 'files': ['ntuple-inventory-report.json'],
             'scope': 'Complete inventory/kernel preparation only; physics and the whole task remain open.'}]
