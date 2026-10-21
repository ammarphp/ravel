"""Generate capability knowledge from source declarations without importing adapters.

Registration, reported tool qualification and scientific qualification are separate.
No native tool, provider SDK or adapter is executed by this module.
"""
from __future__ import annotations

import argparse
import ast
import hashlib
import json
from pathlib import Path
import re
import sys

ATLAS = 'src/ravel/data/knowledge/atlas.json'
# First-line marker a documentation generator writes into an index of source declarations.
GENERATED_INDEX_MARKER = '<!-- ravel:generated-index -->'
QUALIFICATION = 'src/ravel/data/knowledge/qualification.json'
KINDS = ('op', 'cmd', 'tool', 'check', 'hb', 'trap', 'proto', 'doc', 'rule',
         'checklist', 'skill', 'role', 'ana', 'impl', 'art', 'model', 'xs',
         'conv', 'lesson', 'outcome')
# Signature review terms whose implementing check is named in the code. Each target was checked by
# reading it: the entry point validates the property the term names. A term absent here has no
# identified implementing check and links a 'declared_term' row instead.
REVIEW_TERM_CHECKS = {
    'acceptance_certificate': 'validation.certify_acceptance',        # acceptance x efficiency tiered gate
    'basis_manifest': 'validation.validate_run_state.check_basis_manifest',  # inputs/basis_manifest.json gate
    'census': 'validation.validate_run_state.check_resource_census',  # inputs/resource_census.json gate
    'deviations': 'validation.verify_pack.check_deviations_ledger',   # DEVIATIONS.md ledger vs artifacts
    'fit_alarms': 'validation.regression_triggers.evaluate',          # deterministic fit and scan alarms
    'invisible_card': 'physics.delphes_cards.invisible_census',       # per-PDG calorimeter/MET invisibility
    'lhe_check': 'validation.lhe_check',                              # pre-shower LHE guard
    'likelihood_pairing': 'validation.pairing_check',                 # likelihood-to-selection pairing gate
    'limit_status': 'validation.verify_pack.check_limit_record',      # reads limit_status and typed limits
    'normalization_ledger': 'physics.normalization_ledger.check',     # recomputes ledger scale and yields
    'numerical_reference': 'validation.numerical_reference',          # held-out numerical comparisons
    'routine_validation': 'validation.validate_cutflow',              # one-time per-routine cutflow validation
    'summary_complete': 'validation.summary_audit',                   # summary-plot completeness gate
}

TIERS = ('registered', 'unit_tested', 'native_smoke', 'physics_qualified')


def encode(value):
    return (json.dumps(value, sort_keys=True, indent=2, ensure_ascii=False,
                       allow_nan=False) + '\n').encode()


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def source_root():
    """The Ravel source checkout the atlas is generated from.

    An installed package carries no sources, so its location says nothing about the
    checkout: RAVEL_ROOT or the current directory's checkout is used, as for other
    source-bound commands. Absent both, the failure names the remedy.
    """
    from ravel.paths import repository_root
    root = repository_root()
    if root is None:
        raise FileNotFoundError('The knowledge atlas is generated from a Ravel source checkout; '
                                'set RAVEL_ROOT to its directory or run from that checkout.')
    return root


def literal(path, name):
    """A module-level literal, including later ``name[key] = literal`` registrations."""
    tree = ast.parse(path.read_text())
    value = None
    for node in tree.body:
        if isinstance(node, (ast.Assign, ast.AnnAssign)):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            if any(isinstance(t, ast.Name) and t.id == name for t in targets):
                value = ast.literal_eval(node.value)
            elif value is not None and isinstance(value, dict):
                for t in targets:
                    if isinstance(t, ast.Subscript) and isinstance(t.value, ast.Name) and t.value.id == name:
                        value[ast.literal_eval(t.slice)] = ast.literal_eval(node.value)
    if value is None:
        raise ValueError(f'{path.name} lacks {name}')
    return value


def generate(root=None):
    """Return a stable atlas from the selected checkout, with relative source pins."""
    from ravel.workflow.capability_routing import catalogue
    root = Path(root or source_root()).resolve()
    package = root / 'src/ravel'
    entries, pins = {}, {}
    # Material the distribution registry withholds is never indexed, so the
    # shipped atlas names only shipped sources.
    from ravel import evidence_layout
    registry = (evidence_layout.load_registry(root)
                if (root / evidence_layout.REGISTRY).is_file() else None)

    def withheld(path):
        if registry is None:
            return False
        relative = Path(path).relative_to(root).as_posix()
        return evidence_layout._is_internal(relative, registry)

    def shipped(paths):
        return [path for path in paths if not withheld(path)]

    def pin(path):
        path = Path(path)
        relative = path.relative_to(root).as_posix()
        if withheld(path):
            raise ValueError('withheld source cannot be indexed: ' + relative)
        value = {'path': relative, 'sha256': digest(path.read_bytes())}
        pins[relative] = value
        return dict(value)

    def add(kind, identity, title, summary, path, **extra):
        identity = f'{kind}:{identity}'
        if identity in entries:
            raise ValueError('duplicate generated knowledge ID: ' + identity)
        row = {'id': identity, 'kind': kind, 'title': title, 'summary': summary,
               'status': 'registered', 'source': pin(path), 'links': {}, **extra}
        entries[identity] = row
        return row

    if registry is not None:
        pin(root / evidence_layout.REGISTRY)
    for relative in ('workflow/knowledge_atlas.py','workflow/capability_routing.py','workflow/source_syntax.py',
                     'workflow/scoped.py','physics/scoped.py'):
        pin(package / relative)
    worker_tree = ast.parse((package / 'physics/science_worker.py').read_text())
    worker_dispatch = any(isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id == 'adapter' for n in ast.walk(worker_tree))
    catalog = catalogue(root)
    for value in catalog['source_pins']:
        pin(value['path'])
    qualification_path = root / QUALIFICATION
    qualifications = json.loads(qualification_path.read_text())
    pin(qualification_path)
    descriptors = json.loads((package / 'data/mode_descriptors.json').read_text())['modes']
    signatures_path = package / 'data/operation_signatures.json'
    signatures = {}
    if signatures_path.exists():
        data = json.loads(signatures_path.read_text()); pin(signatures_path)
        signatures = data.get('operations', data.get('signatures', data))
        if isinstance(signatures, list):
            signatures = {r.get('operation', r.get('id')): r for r in signatures}
    from ravel.workflow.operation_registration import descriptor_document, registered_rows
    registrations = registered_rows(signatures)
    descriptors = descriptor_document({'modes': descriptors}, signatures)['modes']
    modes = {}
    review_terms = {}
    for item in catalog['operations']:
        mode = item['mode']; descriptor = descriptors.get(mode)
        if descriptor is None:
            raise ValueError('mode lacks descriptor: ' + mode)
        signature = signatures.get(mode, {})
        q = qualifications.get('operations', {}).get(mode, {})
        tier = q.get('validation_tier', 'registered')
        if tier not in TIERS or (tier != 'registered' and not q.get('evidence')):
            raise ValueError('qualification tier requires evidence: ' + mode)
        for evidence in q.get('evidence', []):
            if not isinstance(evidence, dict) or set(evidence) != {'path', 'sha256'}:
                raise ValueError('qualification requires path and sha256 evidence: ' + mode)
            observed = pin(root / evidence['path'])
            if observed != evidence:
                raise ValueError('qualification evidence drift: ' + mode)
        row = add('op', mode, mode, descriptor['summary'], package / 'workflow/science.py',
                  search_context=item.get('contract', '').split('\n\n')[0],
                  tags=sorted(set(sum((descriptor[k] for k in ('tools','inputs','outputs','context','operations','observables')), []))),
                  catalogue={'kind': 'science-mode', 'adapter': item.get('module'),
                             'adapter_exists': bool(item.get('source')),
                             'entrypoints': item.get('entrypoints', []),
                             'worker_destination': 'ravel.physics.science_worker' if worker_dispatch else None,
                             'worker_source': pin(package / 'physics/science_worker.py')},
                  op={'use_when': [], 'do_not_use_when': [],
                      'inputs': signature.get('consumes', descriptor['inputs']),
                      'outputs': signature.get('produces', descriptor['outputs']),
                      'basis': signature.get('basis', []), 'claim_kinds': signature.get('claim_kinds', []),
                      'effects': signature.get('effects', []), 'cost_class': signature.get('cost_class', 'undeclared'),
                      'validation_tier': tier, 'examples': [],
                      'applicability': descriptor.get('applicability', {'scope': 'general'}),
                      'vocabulary_status': 'typed_signature' if signature else 'declared_vocabulary'},
                  links={'handbooks': [], 'checks': [], 'traps': [], 'commands': [], 'tools': [], 'docs': []})
        modes[mode] = row
        if item.get('source'): pin(item['source']['path'])
        for value in item.get('variants', []):
            if isinstance(value, dict) and value.get('source'): pin(value['source']['path'])
        review_terms[row['id']] = [str(c).removeprefix('check:').removeprefix('ravel.')
                                   for c in signature.get('review', {}).get('checks', [])]

    # Existing synthetic documents provide offline task examples without curation.
    for path in shipped(sorted((package / 'data/inference/examples').glob('*.json'))):
        doc = json.loads(path.read_text()); mode = doc.get('kind')
        if mode in modes:
            modes[mode]['op']['examples'].append({'phrase': doc.get('description', modes[mode]['summary']),
                'spec': {'mode': mode, 'task': {'input': path.relative_to(root).as_posix()}},
                'source': pin(path), 'validation': 'adapter_task_schema'})

    # Curators own only these three operation fields; other fields stay source derived.
    # A record the distribution withholds belongs to a withheld operation and is not indexed.
    for path in shipped(sorted((package / 'data/knowledge/curation').glob('*.json'))):
        doc = json.loads(path.read_text()); pin(path)
        mode = doc.get('id', path.stem).removeprefix('op:')
        fields = doc.get('op', {k:v for k,v in doc.items() if k != 'id'})
        if mode not in modes or set(fields) - {'use_when','do_not_use_when','examples'}:
            raise ValueError('unknown curation operation or fields: ' + path.name)
        modes[mode]['op'].update(fields)
        modes[mode]['curation_source'] = pin(path)

    # Contract-owned curation supplies the same fields and must agree with any
    # retained compatibility declaration. It never supplies qualification.
    for mode, registration in registrations.items():
        row = modes[mode]
        fields = registration['curation']
        if row.get('curation_source') and any(row['op'][key] != value for key, value in fields.items()):
            raise ValueError('contract curation conflicts with source declaration: ' + mode)
        row['op'].update(fields)
        row['curation_source'] = pin(signatures_path)

    manifest_path = root / 'native/setup/toolchain-manifest.json'
    from ravel.setup import manifest as mf
    manifest = mf.view(root)
    pin(manifest_path)
    for group in manifest['groups']:
        source = root / 'native/setup/groups' / (group['id'] + '.json')
        source = source if source.is_file() else manifest_path
        row = add('tool', group['id'], group['title'], group['title'], source,
                  installer_group=group['id'], licenses=group.get('licenses', []),
                  depends_on=group.get('depends_on', []), qualification_status='not_installed',
                  qualification_scope='Installer declaration; installation not inspected')
        row['links']['checks'] = []
        for check in group.get('checks', []):
            cid = 'doctor/' + group['id'] + '/' + check['id']
            add('check', cid, check['id'], 'Toolchain doctor declaration', source,
                check={'catches': check.get('instruction', check.get('kind', 'toolchain readiness'))})
            row['links']['checks'].append('check:' + cid)
    from ravel.setup import manifest as mf
    for item in qualifications.get('tools', []):
        if item['status'] not in ('qualified','built_but_unqualified','not_installed','excluded'):
            raise ValueError('unknown tool qualification status: ' + item['id'])
        if mf.withheld_tool(manifest, item):
            continue  # bound only to groups this tree withholds or does not declare
        row = add('tool', item['id'], item['title'], item['summary'], qualification_path,
                  qualification_status=item['status'], qualification_scope=item['evidence_scope'],
                  source_locator=item['source_locator'])
        row['links']['installer_groups'] = ['tool:' + group for group in item['installer_groups']]

    # Source-only reference registration uses the same typed tool-row interface.
    from ravel.workflow.recast_route import register_higgs_reference
    register_higgs_reference(add, package)
    from ravel.validation.qualification_rows import register_qualification_reference
    register_qualification_reference(add, package)

    # Every tool term is resolvable, even when the installer has no provider for it.
    for mode, row in modes.items():
        bindings = manifest.get('operations', [])
        bindings = {v['mode']: v for v in bindings} if isinstance(bindings, list) else bindings
        groups = bindings.get(mode, [])
        if isinstance(groups, dict): groups = groups.get('groups', [])
        row['links']['tools'].extend('tool:' + g for g in groups if 'tool:' + g in entries)
        for term in descriptors[mode]['tools']:
            identity = 'descriptor/' + term
            if 'tool:' + identity not in entries:
                add('tool', identity, term, 'Declared descriptor tool: ' + term,
                    package / 'data/mode_descriptors.json', qualification_status='not_installed',
                    qualification_scope='No exact installer binding declared for this vocabulary term')
            row['links']['tools'].append('tool:' + identity)
            entries['tool:' + identity]['links'].setdefault('operations', []).append(row['id'])

    # Source declarations and functions, rather than imports of scientific executors.
    check_paths = list((package / 'validation').glob('*.py')) + [package / 'workflow/physics_knowledge.py']
    for path in shipped(sorted(check_paths)):
        if path.name == '__init__.py': continue
        tree = ast.parse(path.read_text()); module = path.relative_to(root / 'src').with_suffix('').as_posix().replace('/', '.').removeprefix('ravel.')
        if path.parent.name == 'validation':
            add('check', module, module, ast.get_docstring(tree) or module, path,
                check={'catches': ast.get_docstring(tree) or 'Declared validator module'})
        for node in tree.body:
            if isinstance(node, ast.FunctionDef) and any(t in node.name for t in ('check','validate','gate','alarm')):
                cid = module + '.' + node.name
                add('check', cid, cid, ast.get_docstring(node) or node.name, path,
                    check={'catches': ast.get_docstring(node) or 'Source-declared check function'})
        try: checks = literal(path, 'CHECKS')
        except (ValueError, TypeError): checks = []
        for cid in checks:
            if 'check:' + cid not in entries:
                add('check', cid, cid, 'Declared computed check', path, check={'catches': str(cid)})

    # Computed claim rows are data declarations with source-bound callable consumers.
    claim_registry = package / 'data/claim_checks.json'
    claim_rows = json.loads(claim_registry.read_text())['checks']; pin(claim_registry)
    for name, row in sorted(claim_rows.items()):
        module_path = package / 'validation/claim_checks' / ('rows.py' if row['family'] == 'context' else 'legacy.py')
        if 'check:' + name not in entries:
            add('check', name, name, 'Computed claim check of retained raw evidence', module_path,
                check={'catches': name})

    registry_path = package / 'validation/regression_triggers.py'
    for name in literal(registry_path, 'TRIGGERS'):
        add('check', 'regression/' + name, name, 'Computed inference alarm: ' + name, registry_path,
            check={'catches': 'Registered inference alarm ' + name})
    for path in shipped(sorted((root / '.claude/agents').glob('*.md'))):
        add('role', 'legacy/' + path.stem, path.stem, 'Legacy agent role card', path)
    roles_path = package / 'data/roles/registry.json'
    if roles_path.is_file():
        from .role_registry import registry_document, all_cards
        from .role_registration import source_pins
        source_pins(package, pin)
        pin(package / 'workflow/role_registry.py')
        role_document = registry_document(roles_root=roles_path.parent)
        for card in all_cards(document=role_document, roles_root=roles_path.parent):
            override = role_document['roles'][card['id']].get('override')
            source = roles_path.parent / override if override and (roles_path.parent / override).is_file() else roles_path
            add('role', card['id'], card['id'], card['purpose'], source, catalogue=card)
    doc_paths = literal(package / 'paths.py', 'WORKFLOW_INSTRUCTIONS')
    bundled_paths = set(doc_paths)
    bundle = package / 'data/workflow'
    bundled_files = {p.relative_to(bundle).as_posix() for p in bundle.rglob('*') if p.is_file()}
    if bundled_files != bundled_paths:
        raise ValueError('workflow instruction bundle is not closed')
    for relative in sorted(bundled_paths):
        if pin(bundle / relative)['sha256'] != digest((root / relative).read_bytes()):
            raise ValueError('workflow instruction bundle drift: ' + relative)
    # Operations that only a typed signature declares are indexed by the same documentation scan.
    scoped_names = set(literal(package / 'workflow/scoped_spec.py', 'MODES'))
    signature_only = {name for name, value in signatures.items()
                      if isinstance(value, dict) and 'implementation' in value
                      and name not in modes and name not in scoped_names}
    signature_docs = {name: [] for name in sorted(signature_only)}
    scanned = sorted(set(modes) | signature_only)
    mode_pattern = re.compile(r'(?<![\w-])(?:' + '|'.join(re.escape(m) for m in scanned) + r')(?![\w-])')
    texts = {p.relative_to(root).as_posix(): p.read_text() for p in shipped((root / 'docs').rglob('*.md'))}
    # A generated index enumerates every declaration it maps, so its mentions are not operation
    # knowledge: presenting the whole index at each operation exceeds the bounded instruction read.
    # Such a document is registered as a doc; only an explicit registration reference binds it.
    mentions = {p: (set() if GENERATED_INDEX_MARKER in text else set(mode_pattern.findall(text)))
                for p, text in texts.items()}
    # An explicit contract may bind a shared procedure by its exact heading.
    # Validate the shipped bytes instead of inventing a doc link from its name.
    for mode, registration in registrations.items():
        for reference in registration['documentation']:
            relative, section = reference['path'], reference['section']
            path = root / relative
            from ravel.validation.core import fail
            if relative not in texts or any(p.is_symlink() for p in (path, *path.parents)):
                fail(f'operations.{mode}.registration.documentation.path', relative,
                     'existing shipped regular Markdown file', repair='repair the contract documentation reference')
            headings = [line.lstrip('#').strip() for line in texts[relative].splitlines()
                        if re.match(r'^#{1,6} ', line)]
            if section not in headings:
                fail(f'operations.{mode}.registration.documentation.section', section,
                     'exact heading in ' + relative, repair='repair the contract documentation reference')
            mentions.setdefault(relative, set()).add(mode)
    # Marked indexes are registered documents without mention-derived operation links.
    indexes = {p for p, text in texts.items() if GENERATED_INDEX_MARKER in text}
    doc_paths = sorted(set(doc_paths) | indexes | {p for p, names in mentions.items() if names})
    for relative in doc_paths:
        path = root / relative
        text = texts.get(relative) or path.read_text()
        row = add('doc', relative, next((s.lstrip('# ').strip() for s in text.splitlines() if s.startswith('#')), relative),
                  'Packaged workflow instruction' if relative in bundled_paths else 'Source reference document', path)
        for mode in mentions.get(relative, set(mode_pattern.findall(text))):
            (modes[mode]['links']['docs'] if mode in modes else signature_docs[mode]).append(row['id'])
    pin(package / 'paths.py')
    for folder, kind, glob in [('.claude/rules','rule','*.md'),
                               ('docs/workflow/checklists','checklist','*.md'),
                               ('.claude/skills','skill','*/SKILL.md')]:
        for path in shipped(sorted((root / folder).glob(glob))):
            add(kind, path.parent.name if kind == 'skill' else path.stem, path.stem,
                next((s.lstrip('# ').strip() for s in path.read_text().splitlines() if s.startswith('#')), path.stem), path)
    traps_path = root / 'docs/workflow/checklists/physics-traps.md'
    for match in re.finditer(r'^\| (T\d+) \| (.+)$', traps_path.read_text(), re.M):
        add('trap', match[1], match[1], match[2], traps_path)
    path = package / 'data/inference/interpretation_traps.json'
    for trap in json.loads(path.read_text())['traps']:
        add('trap', trap['id'], trap['id'], trap['statement'], path)
    protocols_path = root / 'docs/workflow/checklists/judgment-protocols.md'
    for match in re.finditer(r'^## (P\d+) [^\n]*', protocols_path.read_text(), re.M):
        add('proto', match[1], match[0].lstrip('# '), match[0].lstrip('# '), protocols_path)

    research_path = package / 'workflow/research_protocol.py'
    for purpose in sorted(literal(research_path, 'PURPOSES')):
        add('proto', 'research/' + purpose, purpose, 'Declared research experiment purpose', research_path)
    methodology_path = package / 'data/research/methodology-stages.json'
    if methodology_path.exists():
        doc = json.loads(methodology_path.read_text()); pin(methodology_path)
        stages = doc.get('stages', [])
        stages = list(stages.values()) if isinstance(stages, dict) else stages
        for stage in stages:
            add('proto', 'methodology/' + stage['id'], stage.get('title',stage['id']),
                stage.get('summary',stage.get('purpose',stage['id'])), methodology_path)

    for path in shipped(sorted((package / 'data/skills/tools').glob('*/SKILL.md'))):
        text = path.read_text(); name = path.parent.name
        match = re.search(r'ravel-requires-modes:\s*"([^"\n]*)"', text)
        hb = add('hb', name, name, next((s[2:] for s in text.splitlines() if s.startswith('# ')), name), path)
        hb['links'] = {'operations': [], 'checks': []}
        for mode in (match[1].split() if match else []):
            if mode not in modes: raise ValueError('handbook names unknown mode: ' + mode)
            hb['links']['operations'].append('op:' + mode)
            modes[mode]['links']['handbooks'].append(hb['id'])
        for target in sorted(set(re.findall(r'ravel\.[\w.]+', text))):
            module, _, function = target.rpartition('.')
            module_path = root / 'src' / (module.replace('.', '/') + '.py')
            if not module_path.exists() or withheld(module_path): continue
            tree = ast.parse(module_path.read_text())
            if not any(isinstance(n, ast.FunctionDef) and n.name == function for n in tree.body): continue
            cid = target.removeprefix('ravel.')
            if 'check:' + cid not in entries:
                add('check', cid, cid, 'Handbook check target', module_path, check={'catches': 'Handbook-cited source function'})
            hb['links']['checks'].append('check:' + cid)
            for mode_id in hb['links']['operations']:
                entries[mode_id]['links']['checks'].append('check:' + cid)
        pitfalls = text.split('## Pitfalls',1)[-1] if '## Pitfalls' in text else ''
        pitfalls = pitfalls.split('\n## ',1)[0]
        for n, line in enumerate(re.findall(r'^[-*] .+(?:\n[ \t]+[^\n]+)*', pitfalls, re.M), 1):
            add('hb', name + '#pitfall-' + str(n), name + ' pitfall ' + str(n), line[2:], path,
                links={'handbooks':[hb['id']], 'checks':list(hb['links']['checks'])}, advisory='Advisory:' in line or 'Caught by' not in line)

    # The method-study graph's stage check vocabulary and the cross-fit executor's receipt
    # checks, read from source without importing either; then the ML methodology handbooks.
    ml_graph, ml_crossfit = package / 'workflow/graphs/ml_study.py', package / 'physics/ml_crossfit.py'
    if shipped([ml_graph]):
        stages = next(ast.literal_eval(n.value) for n in ast.parse(ml_graph.read_text()).body
                      if isinstance(n, ast.Assign) and any(isinstance(t, ast.Name) and t.id == 'CHECKS' for t in n.targets))
        judged = {}
        for stage, keys in stages.items():
            for key in keys: judged.setdefault(key, []).append(stage)
        for key, at in sorted(judged.items()):
            add('check', 'ml-' + key, 'ml-' + key, 'ML study check judged at ' + ', '.join(at), ml_graph,
                check={'catches': 'Computed by the study graph or recomputed by a registered validator from a pinned '
                                  'stage artifact; a check without either is missing and blocks'})
    if shipped([ml_crossfit]):
        computed = {n.value for n in ast.walk(ast.parse(ml_crossfit.read_text()))
                    if isinstance(n, ast.Constant) and isinstance(n.value, str) and re.fullmatch(r'check:ml-[a-z0-9-]+', n.value)}
        for cid in sorted(computed - set(entries)):
            add('check', cid.removeprefix('check:'), cid.removeprefix('check:'), 'ML cross-fit receipt check', ml_crossfit,
                check={'catches': 'Computed by the cross-fit executor into its receipt and recomputed by its validator'})
    ml_handbooks = package / 'data/ml/handbooks.json'
    if shipped([ml_handbooks]) and 'ml-training' in modes:
        for item in json.loads(ml_handbooks.read_text())['handbooks']:
            hb = add('hb', item['id'].removeprefix('hb:'), item['title'], item['content'], ml_handbooks,
                     links={'operations': ['op:ml-training'], 'checks': list(item['pitfall_checks'])})
            modes['ml-training']['links']['handbooks'].append(hb['id'])

    for path in shipped(sorted((package / 'data/roles').glob('*.json'))):
        data = json.loads(path.read_text()); identity = data.get('id', path.stem).removeprefix('role:')
        add('role', identity, data.get('title', identity), data.get('purpose', data.get('description', identity)), path)
    for mode, routing in qualifications.get('routing', {}).items():
        if mode not in modes: raise ValueError('routing names absent mode: ' + mode)
        modes[mode]['links']['traps'].extend('trap:' + t for t in routing.get('traps', []))
        role = routing.get('consult_role')
        if role:
            if 'role:' + role not in entries:
                add('role', role, role, routing['basis'], qualification_path,
                    status=routing.get('role_status', 'held:R-55'))
            modes[mode]['links']['consult_role'] = 'role:' + role
    # Signature review terms name checks; a term without a source-declared check gets its own entry.
    def review_links(terms):
        links = []
        for term in terms:
            identity = 'check:' + REVIEW_TERM_CHECKS.get(term, term)
            if identity not in entries:
                identity = 'check:review/' + term
                if identity not in entries:
                    add('check', 'review/' + term, term, 'no implementing check linked',
                        signatures_path, check={'catches': term}).update(status='declared_term')
            if identity not in links: links.append(identity)
        return links

    for identity, terms in review_terms.items():
        row = entries[identity]
        row['links']['checks'] = list(dict.fromkeys(row['links']['checks'] + review_links(terms)))
    # Scoped workflows and lifecycle operations remain distinct from science modes.
    scoped_path = package / 'workflow/scoped_spec.py'
    for name in literal(scoped_path, 'MODES'):
        add('op', name, name, 'Bounded scoped ' + name + ' workflow', scoped_path,
            catalogue={'kind':'scoped-mode'},
            op={'use_when':[], 'do_not_use_when':[], 'inputs':[], 'outputs':[], 'basis':[],
                'claim_kinds':[], 'effects':[], 'cost_class':'undeclared', 'validation_tier':'registered',
                'examples':[], 'vocabulary_status':'declared_vocabulary'},
            links={'checks':['check:validation.validate_task_contract'], 'docs':['doc:docs/workflow/reference/scoped-workflows.md']})
    lifecycle_path = package / 'validation/validate_run_state.py'
    for stage in literal(lifecycle_path, 'STAGE_ORDER'):
        add('op', 'stage/' + stage, stage, 'Contract lifecycle stage ' + stage, lifecycle_path,
            catalogue={'kind':'lifecycle-stage'},
            op={'use_when':[], 'do_not_use_when':[], 'inputs':[], 'outputs':[], 'basis':[],
                'claim_kinds':[], 'effects':[], 'cost_class':'undeclared', 'validation_tier':'registered',
                'examples':[], 'vocabulary_status':'declared_vocabulary'},
            links={'checks':['check:validation.validate_run_state'], 'docs':['doc:docs/workflow/README.md']})
    for name, signature in signatures.items():
        if not isinstance(signature, dict) or 'implementation' not in signature: continue
        identity = 'op:' + name
        if identity in entries: continue
        add('op', name, name, 'Declared operation signature ' + name, signatures_path,
            catalogue={'kind':signature['implementation'].get('kind','declared')},
            op={'use_when':[], 'do_not_use_when':[], 'inputs':signature.get('consumes',[]),
                'outputs':signature.get('produces',[]), 'basis':signature.get('basis',[]),
                'claim_kinds':signature.get('claim_kinds',[]), 'effects':signature.get('effects',[]),
                'cost_class':signature.get('cost',{}), 'validation_tier':'registered', 'examples':[],
                'vocabulary_status':'typed_signature'},
            links={'docs': signature_docs.get(name, []),
                   'checks': review_links(str(c).removeprefix('check:').removeprefix('ravel.')
                                          for c in signature.get('review', {}).get('checks', []))})
    for filename, key in [('consult_bindings.json','consult_role'),('executors.json','executor_role')]:
        path = package / 'data/knowledge' / filename
        if not path.exists(): continue
        data = json.loads(path.read_text()); pin(path)
        for mode, role in data.get('operations', data.get('bindings', {})).items():
            if mode in modes: modes[mode]['links'][key] = 'role:' + str(role).removeprefix('role:')
    path = package / 'data/knowledge/premises.json'
    if path.exists():
        data = json.loads(path.read_text()); pin(path)
        # The bundle citation contract also covers source-defined conventions.
        for convention in data.get('conventions', []):
            add('conv', convention['id'].removeprefix('conv:'), convention['title'],
                convention['statement'], path)
        premises = data.get('premises', [])
        premises = list(premises.values()) if isinstance(premises, dict) else premises
        for premise in premises:
            tid = premise['id'].removeprefix('trap:')
            if 'trap:' + tid not in entries: add('trap', tid, tid, premise['statement'], path)
            for mode in premise.get('operations', []):
                if mode in modes: modes[mode]['links']['traps'].append('trap:' + tid)

    from .higgs_registration import index_registration
    index_registration(root, add, pin)

    cli_path = package / 'cli.py'
    commands = literal(cli_path, 'FOCUSED_COMMANDS')
    # Also index root commands and argparse subcommands in focused modules.
    for command, (module, summary) in commands.items():
        row = add('cmd', command, 'ravel ' + command, summary, cli_path)
        if command in modes:
            row['links']['operations'] = ['op:' + command]
            modes[command]['links']['commands'].append(row['id'])
        target = package / (module.replace('.', '/') + '.py')
        if not target.is_file():
            raise ValueError('focused command module absent: ' + command + ' -> ' + module)
        if target.exists():
            pin(target)
            for node in ast.walk(ast.parse(target.read_text())):
                if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr=='add_parser' and node.args and isinstance(node.args[0], ast.Constant) and isinstance(node.args[0].value,str):
                    name = command + ' ' + node.args[0].value
                    if 'cmd:' + name not in entries: add('cmd', name, 'ravel ' + name, summary, target)
    for node in ast.walk(ast.parse(cli_path.read_text())):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr=='add_parser' and node.args and isinstance(node.args[0],ast.Constant) and isinstance(node.args[0].value,str):
            name = node.args[0].value
            if 'cmd:' + name not in entries: add('cmd',name,'ravel '+name,'Root CLI command',cli_path)
    # Index existing source-bound context surfaces, without copying their store contents.
    for relative in ('workflow/agentrivet_brief.py','workflow/model_portfolio_knowledge.py',
                     'workflow/physics_knowledge.py','workflow/research_protocol.py',
                     'workflow/research_tools.py','workflow/scientific_context.py',
                     'workflow/review_context.py','workflow/trap_sweep.py','physics/cross_sections.py'):
        path = package / relative
        if path.exists() and not withheld(path):
            tree = ast.parse(path.read_text())
            add('impl', relative, relative, ast.get_docstring(tree) or relative, path)
    for mode, row in modes.items():
        groups = set(row['links']['tools'])
        tool_context = [t['summary'] for t in entries.values() if t['kind'] == 'tool' and groups.intersection(t['links'].get('installer_groups', []))]
        row['search_context'] += '\n' + '\n'.join(tool_context)
    for row in entries.values():
        for key, values in row['links'].items():
            if isinstance(values,list): row['links'][key] = sorted(set(values))
    # The source tree retains development recipes and operations. The agent-visible
    # atlas contains only release declarations, using the installer's same list.
    from ravel.setup import manifest as mf
    held_groups = mf.unreleased_groups(manifest)
    held_modes = mf.unreleased_operations(manifest)
    def visible(row):
        if row['id'] in {'op:' + mode for mode in held_modes}:
            return False
        if row.get('installer_group') in held_groups:
            return False
        # Links to development declarations do not withhold their parent operation.
        return not mf.release_mentions(manifest, [row['id'], row['title'], row['summary']])
    entries = {key: row for key, row in entries.items() if visible(row)}
    for row in entries.values():
        if 'search_context' in row:
            row['search_context'] = '\n'.join(line for line in row['search_context'].splitlines()
                                              if not mf.release_mentions(manifest, line))
    for row in entries.values():
        for key, value in list(row['links'].items()):
            if isinstance(value, list):
                row['links'][key] = [identity for identity in value if identity in entries]
            elif isinstance(value, str) and value not in entries:
                del row['links'][key]
    # The complete input roster stays pinned for deterministic regeneration. It is
    # source provenance, including retained development recipes, not a tool offer.
    for path in sorted((package / 'data/knowledge/schema').glob('*.json')): pin(path)
    return {'schema_version':1,'kind':'knowledge-atlas',
            'generator':{'module_sha256':digest((package / 'workflow/knowledge_atlas.py').read_bytes()),'sources':sorted(pins.values(),key=lambda p:p['path'])},
            'entries':sorted(entries.values(),key=lambda r:r['id'])}


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--root', type=Path)
    ap.add_argument('--write', action='store_true')
    args = ap.parse_args(argv)
    try:
        root = args.root or source_root()
    except FileNotFoundError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    result = generate(root)
    if args.write: (root / ATLAS).write_bytes(encode(result))
    else: print(encode(result).decode(),end='')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
