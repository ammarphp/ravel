"""Finite resonance hypotheses -> ordinary studies -> separate search results.

This is a source compiler and evidence consumer, not a scheduler or likelihood
combiner. A supplied physical interpretation is a premise, not authenticated
physics. Every hypothesis/search pair, including missing/incompatible pairs,
survives compilation and reporting. Existing science and review gates own jobs.
"""
from copy import deepcopy
from fractions import Fraction
from decimal import Decimal
import argparse
import hashlib
import itertools
import json
import math
from pathlib import Path, PurePosixPath
import re

from ravel.physics.ma5_pad import InputCapture
from ravel.physics.ma5_saf import Capture, _json, _keys
from . import science, physics_review, task_completion
from .state_io import atomic_json, read_json
from .scientific_artifact import _pointer

BASES = ('bsm', 'sm_plus_bsm', 'signed_interference')
ROLES = {
    'prediction': ('model-events', 'model-derivation-bridge', 'model-tool-bridge',
                   'model-inputs', 'diagrammatica-code', 'eft-functions', 'mssm-observable-map'),
    'response': ('analyze', 'ma5-pad', 'ma5-saf', 'quantities', 'group-normalization'),
    'template': ('signal-template', 'scientific-delivery'),
    'constraint': ('native-likelihood', 'published-model', 'model-portfolio',
                   'checkmate-events', 'contur-yoda', 'contur-import', 'hs3-likelihood',
                   'svj-recipe', 'mass-width-grid', 'llp-plane-recipe'),
    'summary': ('published-summary', 'scientific-delivery'),
}
SAFE = re.compile(r'[A-Za-z][A-Za-z0-9_-]{0,63}\Z')


def _require(condition, message):
    if not condition: raise ValueError(message)


def _text(value):
    _require(type(value) is str and value.strip() and len(value.encode()) <= 8000,
             'bounded explicit source meaning required')


def _id(value):
    _require(type(value) is str and SAFE.fullmatch(value), 'safe distinct identity required')
    return value


def _number(value, *, positive=False):
    try: good = type(value) in (int, float) and math.isfinite(value)
    except OverflowError: good = False
    _require(good and (not positive or value > 0), 'finite physical coordinate required')
    return value


def _rows(value, maximum, *, empty=False):
    _require(type(value) is list and (0 if empty else 1) <= len(value) <= maximum,
             'complete bounded source population required')
    return value


def _strings(values, maximum=64, *, empty=False):
    _rows(values, maximum, empty=empty)
    for value in values: _text(value)
    _require(len(set(values)) == len(values), 'distinct complete source labels required')


def _digest(value):
    return hashlib.sha256(_bytes(value)).hexdigest()


def _bytes(value):
    return (json.dumps(value, sort_keys=True, indent=2, allow_nan=False)+'\n').encode()


def _pin(path, raw):
    return {'path': str(path), 'sha256': hashlib.sha256(raw).hexdigest()}


def _pin3(path, raw):
    return {**_pin(path, raw), 'size': len(raw)}


def _source(capture, pin, base, *, document=False):
    path, raw = capture.pin(pin, base)
    return path, _json(raw) if document else raw


def _physics(h):
    # Rosters are unordered physical declarations. Keep signed daughter
    # multiplicities and exact binary64/int values; no approximate clustering.
    def numeric(x): return str(Fraction(x))
    return {'spin': h['spin'], 'cp': h['cp'],
        **{k: numeric(h[k]) for k in ('mass_gev', 'width_gev', 'energy_tev')},
        'production': sorted(h['production']),
        'decays': sorted([{'products': sorted(d['products']),
            'branching_ratio': numeric(d['branching_ratio'])} for d in h['decays']],
            key=lambda d: tuple(d['products'])),
        'couplings': sorted([{**x, 'real': numeric(x['real']), 'imag': numeric(x['imag'])}
            for x in h['couplings']], key=lambda x: x['name']),
        'interference': h['interference'], 'basis': h['basis']}


def _summary_target(spec, base, c, *, contract_override=None):
    """Project available typed targets from the SAME captured summary bytes.

    No quantity-unit parsing, implicit energy conversion or opaque adapter
    interpretation. Other modes have no supported target projection here.
    """
    if spec['mode'] != 'published-summary': return None
    from ravel.physics import published_summary
    task = published_summary.validate(spec['task'])
    path, raw = c.read(task['input'], base, task['input_sha256'])
    contract = _json(raw) if contract_override is None else contract_override
    def panel(document, directory, identity):
        _require(document.get('schema_version') == 1 and
                 document.get('kind') == 'published-limit-summary/v1',
                 'typed published summary panel contract required')
        _, survey = _source(c, document['survey'], directory, document=True)
        _, manifest = _source(c, document['manifest'], directory, document=True)
        for pin in document['source_assets'].values(): _source(c, pin, directory)
        # Existing source census/basis validator runs on the captured objects.
        published_summary.inspect(survey, manifest, document)
        return {'panel_id': identity, 'energy_tev': document['energy_tev'],
                'target_basis': deepcopy(manifest['target_basis']),
                'window': deepcopy(document['window']),
                'prediction_basis': None, 'quantity_unit': None}
    if task['schema_version'] == 1:
        targets = [panel(contract, path.parent, None)]
    else:
        _require(contract.get('schema_version') == 2 and
                 contract.get('kind') == 'requested-published-summary/v2',
                 'typed requested published summary contract required')
        targets = []
        for row in _rows(contract['panels'], 4):
            pp, document = _source(c, row['summary'], path.parent, document=True)
            targets.append(panel(document, pp.parent, row['id']))
        _require(len({x['panel_id'] for x in targets}) == len(targets),
                 'unique complete summary target panel roster required')
    return {'mode': 'published-summary', 'targets': targets,
            'unavailable_typed_fields': ['prediction_basis', 'quantity_unit']}


def _stage_target(stage, spec, sp, h, search, c, base):
    if stage.get('target_mapping') is not None:
        _, mapped = _source(c, stage['target_mapping'], base, document=True)
        if mapped.get('schema_version') == 2:
            from . import stage_correspondence
            _keys(mapped, ('schema_version','original_study','hypothesis_sha256','search_sha256',
                'projected_target','bindings','sources','limitations'), 'operative stage correspondence')
            projection = stage_correspondence.project(spec, sp.parent, c)
            _require(projection is not None and mapped['original_study'] == stage['study'] and
                mapped['hypothesis_sha256'] == _digest(h) and
                mapped['search_sha256'] == (None if search is None else _digest(search)) and
                mapped['projected_target'] == projection, 'actual full stage projection/source differs from mapping')
            comparison = stage_correspondence.compare(projection, h, search, mapped['bindings'])
            for pin in _rows(mapped['sources'],32): _source(c,pin,base)
            _strings(mapped['limitations'],empty=True)
            return {'stage':stage['id'],'original_study':stage['study'],'projection':projection,
                'semantic_status':'operative_bindings_and_explicit_source_premises',
                'mapping':stage['target_mapping'],'comparison':comparison,
                'limitations':mapped['limitations']}, list(mapped['limitations'])
    projection = _summary_target(spec, sp.parent, c)
    info = {'stage': stage['id'], 'original_study': stage['study'],
            'projection': projection, 'semantic_status': 'unprojected_source_premise',
            'mapping': None, 'limitations': []}
    if projection is None:
        _require(stage.get('target_mapping') is None,
                 'target map requires a supported actual typed stage projection')
        return info, []
    for target in projection['targets']:
        _require(target['energy_tev'] == h['energy_tev'] and
                 (search is None or target['energy_tev'] == search['applicability']['energy_tev']),
                 'actual study collision energy differs from hypothesis/search; no implicit conversion')
    if stage.get('target_mapping') is None:
        info['semantic_status'] = 'target_correspondence_missing'
        return info, ['source-grounded actual study target mapping missing: ' + stage['id']]
    _, mapping = _source(c, stage['target_mapping'], base, document=True)
    _keys(mapping, ('schema_version', 'original_study', 'hypothesis_sha256',
        'search_sha256', 'projected_target', 'correspondence', 'sources', 'limitations'),
        'actual study target source mapping')
    _require(type(mapping['schema_version']) is int and mapping['schema_version'] == 1 and
        mapping['original_study'] == stage['study'] and
        mapping['hypothesis_sha256'] == _digest(h) and
        mapping['search_sha256'] == (None if search is None else _digest(search)) and
        mapping['projected_target'] == projection,
        'target mapping must bind the original study and actual full projected target')
    correspondence = mapping['correspondence']
    _keys(correspondence, ('model', 'observable', 'basis', 'meaning'), 'target correspondence premise')
    _require(correspondence['model'] == h['interpretation'] and
        correspondence['observable'] == (None if search is None else search['observable']) and
        correspondence['basis'] == h['basis'],
        'explicit selected physical model/observable/basis correspondence required')
    _text(correspondence['meaning'])
    for pin in _rows(mapping['sources'], 32): _source(c, pin, base)
    _strings(mapping['limitations'], empty=True)
    info.update(semantic_status='located_correspondence_premise',
                mapping=stage['target_mapping'], limitations=mapping['limitations'])
    return info, [*mapping['limitations']]


def _hypothesis(h, c, base):
    _keys(h, ('id', 'interpretation', 'spin', 'cp', 'mass_gev', 'width_gev', 'energy_tev',
              'production', 'decays', 'couplings', 'interference', 'basis', 'model', 'sources', 'missing'), 'resonance hypothesis')
    _id(h['id']); _text(h['interpretation'])
    _require(type(h['spin']) is int and h['spin'] in (0, 1, 2) and
             h['cp'] in ('even', 'odd', 'mixed', 'unspecified'), 'explicit supported spin/CP premise required')
    _number(h['mass_gev'], positive=True); _number(h['width_gev']); _number(h['energy_tev'], positive=True)
    _require(0 <= h['width_gev'] < h['mass_gev'], 'declared finite resonance width domain required')
    _strings(h['production']); _rows(h['decays'], 32)
    products = []
    for d in h['decays']:
        _keys(d, ('products', 'branching_ratio'), 'declared decay')
        _rows(d['products'], 8)
        _require(all(type(p) is int and p != 0 for p in d['products']), 'literal signed daughter PDGs required')
        key = tuple(sorted(d['products'])); _require(key not in products, 'duplicate physical decay channel')
        products.append(key); _number(d['branching_ratio'])
        _require(0 <= d['branching_ratio'] <= 1, 'physical declared branching fraction required')
    _require(sum(d['branching_ratio'] for d in h['decays']) <= 1 + 1e-12,
             'declared branching fraction sum exceeds unity')
    _rows(h['couplings'], 64); names = set()
    for coupling in h['couplings']:
        _keys(coupling, ('name', 'real', 'imag', 'unit', 'convention'), 'source coupling')
        _id(coupling['name']); _require(coupling['name'] not in names, 'duplicate coupling coordinate')
        names.add(coupling['name']); _number(coupling['real']); _number(coupling['imag'])
        _text(coupling['unit']); _text(coupling['convention'])
    _require(h['basis'] in BASES and h['interference'] in ('none', 'included_signed', 'unknown'),
             'explicit prediction/interference basis required')
    _require(h['interference'] != 'included_signed' or h['basis'] in ('signed_interference', 'sm_plus_bsm'),
             'signed interference cannot be a positive standalone BSM prediction')
    _source(c, h['model'], base)
    for pin in _rows(h['sources'], 32): _source(c, pin, base)
    _strings(h['missing'], empty=True)


def _search(s, c, base):
    _keys(s, ('id', 'experiment', 'version', 'source', 'routine_ids', 'applicability', 'observable', 'missing'), 'search record')
    _id(s['id']); _text(s['experiment']); _text(s['version']); _source(c, s['source'], base)
    _strings(s['routine_ids']); _strings(s['missing'], empty=True)
    a = s['applicability']
    _keys(a, ('mass_gev', 'width_over_mass', 'energy_tev', 'spins', 'cp', 'production', 'decays', 'bases'), 'search applicability')
    for key in ('mass_gev', 'width_over_mass'):
        if a[key] is None: continue  # Source absence stays an explicit blocker.
        _require(type(a[key]) is list and len(a[key]) == 2, 'literal closed applicability interval required')
        low, high = map(_number, a[key]); _require(0 <= low < high, 'ordered search domain required')
    _number(a['energy_tev'], positive=True)
    _rows(a['spins'], 3); _require(all(type(x) is int and x in (0,1,2) for x in a['spins']) and len(set(a['spins'])) == len(a['spins']), 'explicit source spin roster required')
    _strings(a['cp']); _require(set(a['cp']) <= {'even','odd','mixed','unspecified'}, 'source CP roster required')
    _strings(a['production']); _strings(a['bases']); _require(set(a['bases']) <= set(BASES), 'source prediction basis required')
    _rows(a['decays'], 32)
    _require(all(type(d) is list and d and all(type(p) is int and p != 0 for p in d) for d in a['decays']), 'explicit signed search decay products required')
    _require(len({tuple(sorted(d)) for d in a['decays']}) == len(a['decays']), 'duplicate search decay domain')
    _keys(s['observable'], ('quantity', 'unit', 'confidence', 'scope'), 'constraint observable')
    for value in s['observable'].values(): _text(value)


def _blockers(h, s):
    a = s['applicability']; reasons = [*h['missing'], *s['missing']]
    for match, reason in (
        (a['mass_gev'] is not None and a['mass_gev'][0] <= h['mass_gev'] <= a['mass_gev'][1],
         'mass domain not supplied' if a['mass_gev'] is None else 'mass outside supplied search domain'),
        (a['width_over_mass'] is not None and a['width_over_mass'][0] <= h['width_gev']/h['mass_gev'] <= a['width_over_mass'][1],
         'width domain not supplied' if a['width_over_mass'] is None else 'width outside supplied search domain'),
        (h['energy_tev'] == a['energy_tev'], 'collision energy differs'),
        (h['spin'] in a['spins'] and h['cp'] in a['cp'], 'spin/CP basis incompatible'),
        (set(h['production']) <= set(a['production']), 'production basis incompatible'),
        (all(tuple(sorted(d['products'])) in {tuple(sorted(x)) for x in a['decays']} for d in h['decays']), 'decay basis incompatible'),
        (h['basis'] in a['bases'], 'prediction/interference basis incompatible'),
        (h['interference'] != 'unknown', 'interference treatment remains unknown')):
        if not match: reasons.append(reason)
    return reasons


def _load(request_path):
    c = InputCapture(); p, raw = c.read(str(request_path), Path.cwd()); r = _json(raw)
    _keys(r, ('schema_version','parent_contract','census_scope','hypotheses','searches','correlations','stages','pairs'), 'whole resonance recipe')
    _require(type(r['schema_version']) is int and r['schema_version'] == 1, 'resonance recipe schema1 required')
    _text(r['census_scope'])
    parent_pin = r['parent_contract']; _keys(parent_pin, ('path','sha256','size'), 'original task contract pin')
    parent_path, parent_raw = c.pin({k:parent_pin[k] for k in ('path','sha256')}, p.parent)
    _require(type(parent_pin['size']) is int and parent_pin['size'] == len(parent_raw), 'parent contract size differs')
    from ravel.validation.validate_task_contract import validate
    parent = _json(parent_raw); _require(not validate(parent), 'valid original parent task required')
    task_completion.validate_requirements(parent)
    hypotheses, searches = {}, {}
    for h in _rows(r['hypotheses'], 8):
        _hypothesis(h,c,p.parent); _require(h['id'] not in hypotheses, 'duplicate hypothesis')
        hypotheses[h['id']] = h
    _require(len(hypotheses) >= 2 and len({_digest(_physics(h)) for h in hypotheses.values()}) == len(hypotheses),
             'at least two physically distinct declared hypotheses required')
    for s in _rows(r['searches'], 8):
        _search(s,c,p.parent); _require(s['id'] not in searches, 'duplicate search')
        searches[s['id']] = s
    _require(len(hypotheses)*len(searches) <= 32, 'finite whole pair/report budget exceeded')
    expected = {tuple(sorted(x)) for x in itertools.combinations(searches, 2)}; seen = set()
    for relation in _rows(r['correlations'], 28, empty=True):
        _keys(relation, ('searches','state','sources','meaning'), 'cross-search relation')
        _require(type(relation['searches']) is list and len(relation['searches']) == 2, 'two distinct search IDs required')
        key = tuple(sorted(relation['searches'])); _require(key in expected and key not in seen, 'complete unique cross-search relation required')
        seen.add(key); _require(relation['state'] in ('independent','shared','unknown'), 'explicit correlation disposition required')
        _text(relation['meaning'])
        for pin in _rows(relation['sources'], 32, empty=relation['state']=='unknown'): _source(c,pin,p.parent)
    _require(seen == expected, 'every cross-search relationship must remain explicit')
    stages = {}; order = []; targets = {}; target_blockers = {}
    for stage in _rows(r['stages'], 128, empty=True):
        _keys(stage, ('id','hypothesis','search','role','study','documents','links','exports','claim_scope','missing',*(['quantities'] if 'quantities' in stage else []),*(['target_mapping'] if 'target_mapping' in stage else []),*(['retained_producer'] if 'retained_producer' in stage else [])), 'ordinary resonance stage')
        _require(type(stage.get('retained_producer',False)) is bool, 'explicit retained producer flag required')
        qids=set()
        for quantity in _rows(stage.get('quantities',[]),16,empty=True):
            _keys(quantity,('id','pointer','unit','meaning'),'delivered constraint quantity')
            _id(quantity['id']);_require(quantity['id'] not in qids,'distinct constraint quantity census required');qids.add(quantity['id'])
            _text(quantity['unit']);_text(quantity['meaning'])
            _require(type(quantity['pointer']) is str and quantity['pointer'].startswith('/'),'literal complete-result quantity selector required')
        identity = _id(stage['id']); _require(identity not in stages and stage['hypothesis'] in hypotheses, 'unique stage and existing hypothesis required')
        _require(stage['search'] is None or stage['search'] in searches, 'stage search absent')
        sp, spec = _source(c,stage['study'],p.parent,document=True)
        science.validate(spec)
        _require(stage['role'] in ROLES and spec['mode'] in ROLES[stage['role']], 'stage must use the actual existing operation family')
        _require(spec.get('schema_version') == 2 and spec['max_attempts'] == 1 and spec['review_policy']['policy']['max_redos'] == 0 and 'resonance_handoff' not in spec, 'ordinary original one-attempt study required')
        binding = spec.get('goal_binding'); _require(type(binding) is dict and binding['contract'] == parent_pin, 'every stage must retain the exact original parent goal binding')
        _require(stage['claim_scope'] in spec['review_policy']['policy']['claim_scopes'], 'source scope absent from original policy')
        documents = {}
        for d in _rows(stage['documents'], 8, empty=True):
            _keys(d, ('id','task_key','source'), 'stage scientific document')
            _id(d['id']); _require(d['id'] not in documents and d['task_key'] in spec['task'], 'unique source task-document binding required')
            dp, doc = _source(c,d['source'],p.parent,document=True)
            _require(type(spec['task'][d['task_key']]) is str and science.regular(spec['task'][d['task_key']],sp.parent) == dp, 'configured task document differs from supplied source')
            documents[d['id']] = (d,dp,doc)
        slots = set()
        for link in _rows(stage['links'], 32, empty=True):
            task_path = 'task_key' in link
            _keys(link, ('task_key','from_stage','export') if task_path else ('document','pointer','from_stage','export'), 'accepted output handoff')
            _require((task_path or link['document'] in documents) and link['from_stage'] in stages, 'handoff must be an earlier ordinary stage in the finite recipe')
            if task_path:
                from . import stage_correspondence
                stage_correspondence.task_slot(spec,link['task_key'])
            predecessor = stages[link['from_stage']][0]
            _require(predecessor['hypothesis'] == stage['hypothesis'] and (predecessor['search'] is None or predecessor['search'] == stage['search']), 'handoff cannot borrow another physical hypothesis/search')
            _require(link['export'] in predecessor['exports'], 'handoff export absent')
            pointer = ('task',link['task_key']) if task_path else (link['document'],link['pointer'])
            _require(pointer not in slots, 'duplicate scientific handoff slot'); slots.add(pointer)
            if task_path:
                descriptor=predecessor['exports'][link['export']]
                _require(type(descriptor) is dict and descriptor.get('kind')=='generated_member' and
                    stages[link['from_stage']][2]['mode']=='model-events',
                    'Events task link requires a committed actual model-events member')
            else:
                from . import stage_correspondence
                slot = _pointer(documents[link['document']][2],link['pointer'])
                stage_correspondence.document_slot(spec,documents[link['document']][2],link['pointer'],slot)
                _source(c,{k:slot[k] for k in ('path','sha256')},documents[link['document']][1].parent)
        _require(type(stage['exports']) is dict and 1 <= len(stage['exports']) <= 16, 'complete declared output export census required')
        for name, rel in stage['exports'].items():
            _id(name)
            if type(rel) is dict:
                _keys(rel,('kind','path','format'),'recorded generated member export')
                _require(spec['mode']=='model-events' and rel['kind']=='generated_member' and rel['format']=='HepMC2',
                    'only actual generated HepMC2 export is admitted')
                q=PurePosixPath(rel['path'])
                _require(q.parts and q.parts[0]=='Events' and not q.is_absolute() and '..' not in q.parts and str(q)==rel['path'],
                    'canonical original generated member required')
            else:
                q = PurePosixPath(rel)
                _require(type(rel) is str and rel and not q.is_absolute() and '..' not in q.parts and str(q)==rel, 'canonical relative ordinary output export required')
        _require('result' in stage['exports'] and stage['exports']['result']=='result.json', 'complete ordinary result must be retained')
        _strings(stage['missing'], empty=True)
        targets[identity], target_blockers[identity] = _stage_target(stage, spec, sp,
            hypotheses[stage['hypothesis']], searches.get(stage['search']), c, p.parent)
        stages[identity]=(stage,sp,spec,documents);order.append(identity)
    pairs = []; seen = set(); used = set()
    for row in _rows(r['pairs'], 32):
        _keys(row, ('hypothesis','search','mapping','stages','backend_portfolio','missing'), 'complete hypothesis/search pair')
        key=(row['hypothesis'],row['search']); _require(key[0] in hypotheses and key[1] in searches and key not in seen, 'distinct full hypothesis/search census required'); seen.add(key)
        h,s = hypotheses[key[0]],searches[key[1]]; blockers=_blockers(h,s); _strings(row['missing'],empty=True);blockers+=row['missing']
        _strings(row['stages'],128,empty=True)
        _require(all(x in stages and stages[x][0]['hypothesis']==key[0] and stages[x][0]['search'] in (None,key[1]) for x in row['stages']), 'pair contains another hypothesis/search stage')
        used.update(row['stages'])
        blockers += [reason for identity in row['stages'] for reason in target_blockers[identity]]
        if row['mapping'] is None: blockers.append('source-grounded model/search convention mapping missing')
        else:
            _, mapping = _source(c,row['mapping'],p.parent,document=True)
            _keys(mapping, ('hypothesis','search','hypothesis_sha256','search_sha256','basis','observable','sources','limitations'), 'physical source mapping')
            _require(mapping['hypothesis']==h['id'] and mapping['search']==s['id'] and mapping['hypothesis_sha256']==_digest(h) and mapping['search_sha256']==_digest(s) and mapping['basis']==h['basis'] and mapping['observable']==s['observable'], 'exact full hypothesis/search/convention mapping required')
            for pin in _rows(mapping['sources'],32): _source(c,pin,p.parent)
            _strings(mapping['limitations'],empty=True);blockers+=mapping['limitations']
        if not any(stages[x][0]['role']=='constraint' for x in row['stages']): blockers.append('ordinary constraint stage missing')
        if h['interference']=='included_signed' and any(stages[x][2]['mode']=='signal-template' for x in row['stages']):
            blockers.append('positive pyhf signal-template is not a signed-interference construction; supply total-mean/native route')
        if row['backend_portfolio'] is not None:
            from . import backend_portfolio
            bp,_=_source(c,row['backend_portfolio'],p.parent)
            _, br, _, entries, bc=backend_portfolio._load(bp)
            _require(br['model']==h['model'] and br['signal_basis']==h['basis'] and br['energy_tev']==h['energy_tev'], 'backend portfolio must retain the selected physical model/basis')
            for pin in backend_portfolio.input_pins(bp): c.stream_pin(pin,bp.parent,allow_empty=True)
            bc.finish()
            blockers += [v for e in entries for v in e['blockers']]
        pairs.append({'id':key[0]+'--'+key[1], **deepcopy(row),'stage_targets':[targets[x] for x in row['stages']],
            'blockers':list(dict.fromkeys(blockers))})
    _require(seen == set(itertools.product(hypotheses,searches)), 'missing hypothesis/search pair cannot disappear from the original denominator')
    _require(used == set(stages), 'unassigned stage cannot receive preparation')
    c.finish(); return p,r,parent,hypotheses,searches,stages,pairs,c


def assess(request_path):
    p,r,parent,_,_,stages,pairs,c=_load(request_path)
    result={'kind':'whole-resonance-recipe','schema_version':1,'request':_pin(p,c.files[p][1]),
        'original_request':parent['prompt'],'parent_contract':r['parent_contract'],
        'census_scope':r['census_scope'],'hypotheses':r['hypotheses'],'searches':r['searches'],
        'correlations':r['correlations'],'pairs':pairs,'stage_ids':list(stages),
        'cross_search_combination':None,'scientific_exhaustiveness_verified':False,
        'parent_task_accepted':False,'execution_authorized':False,'physics_validated':False}
    c.finish(); return result


def input_pins(request_path):
    *_,c = _load(request_path)
    return [_pin(p,b) for p,(_,b) in c.files.items()] + [
        {'path':str(p),'sha256':fact[1]} for p,(fact,_) in c.streams.items()]


def _fresh(out, c, runs=()):
    out=Path(out).absolute()
    _require('..' not in out.parts and not out.exists() and not any(p.is_symlink() for p in (out,*out.parents)), 'fresh canonical ordinary compiler destination required')
    protected=[*c.files,*c.streams,*[science.root(x) for x in runs]]
    _require(not any(out==p or p.is_relative_to(out) or (p.is_dir() and out.is_relative_to(p)) for p in protected), 'compiler must preserve original scientific sources/runs')
    return out


def preparation_pins(request_path, stage_id, runs):
    p,_,_,_,_,stages,_,c=_load(request_path)
    _require(type(runs) is dict and set(runs)<=set(stages) and stage_id in stages, 'known explicit stage/predecessor map required')
    _,_,spec,_=stages[stage_id]
    for path in science.task_inputs(spec,stages[stage_id][1].parent):
        c.stream_pin({'path':str(path),'sha256':science.execution.file_hash(path)},p.parent,allow_empty=True)
    _,_,observed=_stage_spec(p,stages,stage_id,runs,c)
    _finish_accepted(observed,c)
    pins=[_pin(q,b) for q,(_,b) in c.files.items()]+[{'path':str(q),'sha256':f[1]} for q,(f,_) in c.streams.items()]
    for dep in delivery_pins(request_path,runs):
        if dep['path'] not in {x['path'] for x in pins}:pins.append(dep)
    return pins


def delivery_pins(request_path,runs):
    pins=input_pins(request_path);c=InputCapture();roots={}
    _require(type(runs) is dict,'explicit result map required')
    for value in runs.values():
        root=science.root(value);members=set()
        for path in root.rglob('*'):
            _require(not path.is_symlink() and (path.is_file() or path.is_dir()),'ordinary complete terminal evidence required')
            c.ordinary(path,directory=path.is_dir())
            if path.is_file():
                members.add(path);pin={'path':str(path),'sha256':science.execution.file_hash(path)}
                c.stream_pin(pin,root,allow_empty=True);pins.append(pin)
        roots[root]=members
    c.finish()
    for root,members in roots.items():
        _require({q for q in root.rglob('*') if q.is_file()}==members,'ending terminal evidence membership changed')
    return list({x['path']:x for x in pins}.values())


def _write(out, name, value, emitted):
    from . import research_blueprint
    path=out/name;raw=_bytes(value);research_blueprint._write(path,raw)
    emitted.read(str(path),out,hashlib.sha256(raw).hexdigest())
    return _pin(path,raw)


def _set(doc, pointer, value):
    # Existing blueprint uses the same explicit non-root JSON pointer parser.
    from . import research_blueprint
    research_blueprint._replace(doc,pointer,deepcopy(value))


def _absolute_pins(value, base):
    if type(value) is dict:
        if set(value)=={'path','sha256'}:
            return {**value,'path':str(science.regular(value['path'],base))}
        return {k:_absolute_pins(v,base) for k,v in value.items()}
    if type(value) is list:return [_absolute_pins(v,base) for v in value]
    return value


def _accepted(stage_entry, run, c, request_pin):
    stage,_,_,_=stage_entry;rd=science.root(run)
    retained=stage.get('retained_producer',False)
    if retained:
        from . import retained_science_review
        proof=retained_science_review.observe(rd,action='reuse')
        _require(proof['mode']=='model-events','retained member reuse is limited to model-events producers')
    else: science.verify_plan(rd,approved=True)
    spec=science.execution_spec(rd)
    if retained and 'resonance_handoff' not in spec:
        # An original accepted producer need not claim it was created by this
        # later compiler. Its complete recorded specification must instead be
        # exactly the supplied original study, under the existing reuse proof.
        _require(spec==stage_entry[2],'retained producer original study specification differs')
    else:
        _require('resonance_handoff' in spec,'ordinary result lacks its original resonance recipe handoff')
        _,hraw=c.read(spec['resonance_handoff'],rd);h=_json(hraw)
        _require(h['stage_id']==stage['id'] and h['request']==request_pin and
            h['original_study']==dict(stage['study'],path=str(stage_entry[1])), 'ordinary output belongs to another original recipe/stage')
        effective=deepcopy(spec);effective.pop('resonance_handoff')
        _require(h['effective_specification']==effective,'recorded producer effective specification differs')
    if not retained:
        handoff_inputs(spec,rd)
        packet=science.packet(rd,write=False)
        _require(not packet['errors'] and packet['execution']['status']=='succeeded', 'accepted handoff requires unchanged successful ordinary execution')
    view=physics_review.status(rd,retained_study=retained)
    _require(view['state']=='accepted' and view['claim_scope']==stage['claim_scope'] and not view['live_errors'], 'current exact scoped review required; no hold/unreviewed result can propagate')
    snapshot=physics_review.snapshot(rd,action='reuse',retained_study=retained)
    _require(not physics_review.validate_snapshot(snapshot), 'detached ordinary review admission invalid')
    selected,_,_=science._selected(rd,read_json(rd/science.PLAN));_require(len(selected['outputs'])==1, 'one ordinary output root required')
    output=rd/selected['outputs'][0]; files={}
    for name,rel in stage['exports'].items():
        if type(rel) is dict:
            from ravel.physics import model_event_commitment
            def document(name):
                _,raw=c.read(str(output/name),rd);return _json(raw)
            request=document('native-input.json');result=document('model-events-native.json')
            from ravel.physics import model_events
            original_path,original_raw=c.read(stage_entry[2]['task']['config'],stage_entry[1].parent)
            config_path,config_raw=c.read(spec['task']['config'],rd)
            original=_json(config_raw)
            _require(original==_json(original_raw) or original==_absolute_pins(_json(original_raw),original_path.parent),
                'materialized producer config differs from exact original operative inputs')
            expected=deepcopy(original)
            for key,value in expected['runtime']['options'].items():
                if value is not None:
                    expected['runtime']['options'][key]=str(model_events.bridge._regular(value,config_path.parent,directory=key.endswith('_path')))
            _require(request['config_sha256']==hashlib.sha256(config_raw).hexdigest() and request['config']==expected,
                'recorded producer differs from original operative generation source')
            commitment=document('generated-member-commitment.json');census=document('generated-artifact-census.json')
            delivered=document('model-events.json');ordinary=document('result.json')
            _require(delivered==ordinary and all(delivered.get(k)==v for k,v in result.items()),'complete ordinary producer result differs')
            _require(rel['path']==request['config']['outputs']['hepmc_relative'] and
                request['config']['shower']['backend']!='OFF' and result.get('shower_population') is not None,
                'export must be the observed original shower stream')
            files[name]=model_event_commitment.member(commitment,request,result,census,rel['path'],c)
            shower=result['shower_population']
            _require(shower.get('format')=='HepMC2' and shower.get('complete_framing') is True and
                shower.get('raw_sha256')==files[name]['sha256'] and
                shower.get('weight_names')==[row['hepmc_name'] for row in request['config']['outputs']['shower_weight_map']],
                'selected member differs from actual complete producer shower observation')
            continue
        path=output/rel;pin={'path':str(path),'sha256':science.execution.file_hash(path)}
        c.stream_pin(pin,rd,allow_empty=True);_require(c.streams[path][0][0][3]>0,'declared output export is empty');files[name]=pin
    # Retain the entire actual native output inventory, not a successful scalar.
    membership=set()
    for path in output.rglob('*'):
        _require(not path.is_symlink() and (path.is_file() or path.is_dir()), 'ordinary full native output census required')
        c.ordinary(path,directory=path.is_dir())
        if path.is_file():
            membership.add(path);c.stream_pin({'path':str(path),'sha256':science.execution.file_hash(path)},rd,allow_empty=True)
    return rd,spec,files,snapshot,output,membership,retained


def _finish_accepted(rows,c):
    c.finish()
    for rd,spec,_,snapshot,output,members,retained in rows:
        _require({p for p in output.rglob('*') if p.is_file()}==members, 'ending actual output membership changed')
        if spec['mode']=='model-events' and ((output/'generated-member-commitment.json').is_file() or
                output/'generated-member-commitment.json' in c.files):
            from ravel.physics import model_event_commitment
            _,raw=c.read(str(output/'generated-member-commitment.json'),rd);commitment=_json(raw)
            _,raw=c.read(str(output/'native-input.json'),rd)
            model_event_commitment.verify(commitment,_json(raw)['process'])
        if not retained: science.verify_plan(rd,approved=True)
        _require(science.execution_spec(rd)==spec and physics_review.snapshot(rd,action='reuse',retained_study=retained)==snapshot, 'accepted result authority changed during observation')
    c.finish()
    # Revalidate every exact producer commitment AFTER the review refresh.
    for rd,spec,_,_,output,members,_ in rows:
        _require({p for p in output.rglob('*') if p.is_file()}==members, 'ending output membership changed after review')
        if spec['mode']=='model-events' and ((output/'generated-member-commitment.json').is_file() or
                output/'generated-member-commitment.json' in c.files):
            _,raw=c.read(str(output/'generated-member-commitment.json'),rd)
            _,request=c.read(str(output/'native-input.json'),rd)
            model_event_commitment.verify(_json(raw),_json(request)['process'])
    c.finish()


def _stage_spec(p, stages, identity, runs, c):
    stage,sp,source,documents=stages[identity];spec=deepcopy(source);observed=[];copies={}
    for did,(d,path,doc) in documents.items():copies[did]=_absolute_pins(deepcopy(doc),path.parent)
    for link in stage['links']:
        _require(link['from_stage'] in runs, 'actual separately accepted predecessor output is required')
        result=_accepted(stages[link['from_stage']],runs[link['from_stage']],c,_pin(p,c.files[p][1]));observed.append(result)
        if 'resonance_handoff' in result[1]:
            _,hraw=c.read(result[1]['resonance_handoff'],result[0]);h=_json(hraw)
            _require(h['request']==_pin(p,c.files[p][1]), 'cannot borrow a result from another resonance recipe epoch')
        else:
            _require(result[6] and stages[link['from_stage']][0].get('retained_producer') is True,
                'only authenticated retained original producer may lack later recipe metadata')
        if 'task_key' in link:
            spec['task'][link['task_key']]=result[2][link['export']]['path']
            _producer_analysis_population(spec,sp.parent,result,c)
        else:
            from . import stage_correspondence
            doc=copies[link['document']];slot=_pointer(doc,link['pointer'])
            extra=stage_correspondence.document_slot(spec,doc,link['pointer'],slot)
            _set(doc,link['pointer'],{**result[2][link['export']],**extra})
    # The actual adapter classifies its paths. Digests, presets and physical
    # labels are strings too, so they must never be relocated as pathnames.
    classified=set(science.task_inputs(source,sp.parent))
    for key,value in spec['task'].items():
        if type(value) is str:
            candidate=Path(value) if Path(value).is_absolute() else sp.parent/value
            if value==source['task'].get(key) and candidate.absolute() in classified:spec['task'][key]=str(candidate.absolute())
    if spec['mode'] == 'published-summary':
        inputs = [value for did, value in copies.items()
                  if documents[did][0]['task_key'] == 'input']
        _require(len(inputs) <= 1, 'unique source summary document binding required')
        if inputs:
            original = _summary_target(source, sp.parent, c)
            effective = _summary_target(spec, sp.parent, c, contract_override=inputs[0])
            _require(effective == original,
                     'accepted predecessor changed the mapped actual study target')
    if stage.get('target_mapping') is not None:
        _,mapped=_source(c,stage['target_mapping'],p.parent,document=True)
        if mapped.get('schema_version')==2:
            from . import stage_correspondence
            overrides={documents[did][0]['task_key']: value for did,value in copies.items()}
            original=stage_correspondence.project(source,sp.parent,c)
            effective=stage_correspondence.project(spec,sp.parent,c,documents=overrides)
            stage_correspondence.same_target(original,effective)
    return spec,copies,observed


def _producer_analysis_population(spec,base,producer,c):
    from ravel.physics import event_census
    output=producer[4]
    _,raw=c.read(str(output/'model-events-native.json'),output);result=_json(raw)
    _,raw=c.read(spec['task']['metadata'],base);metadata=_json(raw)
    shower=result['shower_population'];generation=result['intended']['generation']
    _require(metadata['beam_pdg']==generation['beam_pdg'] and
        list(map(Decimal, map(str,metadata['beam_energy_gev'])))==list(map(Decimal,map(str,generation['energy_gev']))) and
        metadata['events']==shower['returned_events'] and metadata['weight_names']==shower['weight_names'],
        'consumer metadata differs from actual original producer beam/weight/population')
    # The released consumer validates full framing, exposure, all weights,
    # cross-section source and grouped normalization; no substitute census.
    event_census.census(science.regular(spec['task']['events'],base),metadata,
        nominal_weight=spec['task'].get('nominal_weight'),rivet_version=spec['task']['runtime']['version'])


def _document_task(spec, task_key, destination):
    spec['task'][task_key]=destination['path']
    if task_key=='input':
        # These are the existing adapters' exact top-level input commitments.
        for key in ('input_sha256','contract_sha256'):
            if key in spec['task']:spec['task'][key]=destination['sha256']


def prepare_stage(request_path, stage_id, runs, output):
    """Explicitly compile ONE chosen step; never dispatch, approve or auto-advance."""
    p,r,_,_,_,stages,pairs,c=_load(request_path)
    _require(type(runs) is dict and set(runs)<=set(stages) and stage_id in stages, 'known explicit predecessor run map required')
    stage=stages[stage_id][0]
    affected=[x for x in pairs if stage_id in x['stages']]
    _require(affected and all(not x['blockers'] for x in affected) and not stage['missing'], 'resolve named hypothesis/search/stage blockers before ordinary preparation')
    spec,copies,observed=_stage_spec(p,stages,stage_id,runs,c)
    out=_fresh(output,c,runs.values());out.mkdir(parents=True);emitted=Capture()
    for did,doc in copies.items():
        destination=_write(out,did+'.json',doc,emitted)
        _document_task(spec,stages[stage_id][3][did][0]['task_key'],destination)
    handoff={'schema_version':1,'request':_pin(p,c.files[p][1]),'stage_id':stage_id,
        'original_study':dict(stages[stage_id][0]['study'],path=str(stages[stage_id][1])),
        'predecessor_runs':deepcopy(runs),'effective_specification':deepcopy(spec)}
    hp=_write(out,'resonance-handoff.json',handoff,emitted)
    spec['resonance_handoff']=hp['path'];science.validate(spec)
    _write(out,'science.json',spec,emitted)
    # Real existing adapter validation, full scientific/runtime/goal inputs and
    # its resource hook. No metadata-only bypass and no execution here.
    expanded=science.task_inputs(spec,out)
    for path in expanded:c.stream_pin({'path':str(path),'sha256':science.execution.file_hash(path)},out,allow_empty=True)
    result={'kind':'resonance-stage-preparation','stage_id':stage_id,'hypothesis':stage['hypothesis'],
        'search':stage['search'],'role':stage['role'],'specification':_pin(out/'science.json',_bytes(spec)),
        'ordinary_rundir':str(out/'ordinary-study'),'original_parent':r['parent_contract'],
        'next_command':['ravel','plan','--rundir',str(out/'ordinary-study'),'--spec',str(out/'science.json')],
        'accepted_predecessors':[{'rundir':str(x[0]),'review':x[3],'exports':x[2]} for x in observed],
        'execution_authorized':False,'parent_task_accepted':False,'physics_validated':False}
    _write(out,'preparation.json',result,emitted);_finish_accepted(observed,c);emitted.finish()
    return result


def handoff_inputs(spec,base):
    """Normal science intake binds hypotheses, searches and fresh old-run gates."""
    c=InputCapture();hp,raw=c.read(spec['resonance_handoff'],base);h=_json(raw)
    _keys(h,('schema_version','request','stage_id','original_study','predecessor_runs','effective_specification'),'resonance ordinary handoff')
    _require(type(h['schema_version']) is int and h['schema_version']==1, 'handoff schema1 required')
    rp,_=c.pin(h['request'],hp.parent)
    p,_,_,_,_,stages, pairs,source=_load(rp)
    identity=h['stage_id'];_require(identity in stages, 'unknown ordinary recipe stage')
    _require(all(not x['blockers'] for x in pairs if identity in x['stages']) and not stages[identity][0]['missing'], 'physical applicability changed or unresolved')
    _require(h['original_study']==dict(stages[identity][0]['study'],path=str(stages[identity][1])), 'original scientific study changed')
    effective=deepcopy(spec);effective.pop('resonance_handoff')
    _require(effective==h['effective_specification'], 'ordinary resonance study was modified')
    wanted,copies,observed=_stage_spec(p,stages,identity,h['predecessor_runs'],source)
    for did,value in copies.items():
        task_key=stages[identity][3][did][0]['task_key'];path,b=c.read(effective['task'][task_key],base)
        _require(_json(b)==value, 'generated scientific input differs from exact accepted output/source')
        _document_task(wanted,task_key,_pin(path,b))
    _require(wanted==effective,'hypothesis/study policy or resources changed')
    _finish_accepted(observed,source);c.finish()
    return [_pin(q,b) for cap in (c,source) for q,(_,b) in cap.files.items()] + [
        {'path':str(q),'sha256':fact[1]} for q,(fact,_) in source.streams.items()]


def prepare_backends(request_path, hypothesis, search, selected, output):
    """Use the existing original-context backend portfolio handoff unchanged."""
    p,_,_,_,_,_,pairs,c=_load(request_path)
    row=next((x for x in pairs if (x['hypothesis'],x['search'])==(hypothesis,search)),None)
    _require(row is not None and not row['blockers'] and row['backend_portfolio'] is not None, 'current applicable configured backend portfolio required')
    from . import backend_portfolio
    bp,_=c.pin(row['backend_portfolio'],p.parent)
    out=_fresh(output,c);result=backend_portfolio.prepare(bp,selected,out);c.finish()
    return result


def construct_regional(document_pin, runtime, fit, output, *, base_dir, max_seconds):
    """Existing signed TOTAL-mean construction; no independent negative Poisson."""
    from ravel.physics import statistical_construction
    c=InputCapture();_,raw=c.pin(document_pin,base_dir);document=_json(raw)
    statistical_construction.validate(document)
    for pin in statistical_construction.source_inputs(document,base_dir):
        c.read(str(pin),base_dir)
    out=_fresh(output,c)
    result=statistical_construction.write_native_bundle(document,out,runtime=runtime,fit=fit,max_seconds=max_seconds)
    generated=Capture()
    _,construction=generated.read(str(out/'construction.json'),out)
    _,card=generated.read(str(out/'model.txt'),out)
    _,config=generated.read(str(out/'native-input.json'),out)
    _,handoff=generated.read(str(out/'handoff.json'),out)
    _require(_json(construction)==document and card==statistical_construction.datacard(document),
             'constructed full mean or datacard differs from supplied signed law')
    expected={'schema_version':2 if 'saved_fit' in fit else 1,'source':document['question'],
        'model':{'files':[{**_pin(out/'model.txt',card),'staged_path':'model.txt'}],'card':'model.txt',
            'regions':[{'channel':b['id'],'role':b['role']} for b in document['bins']],
            'physics_model':None,'signal_replacement':None,'construction':_pin(out/'construction.json',construction)},
        'runtime':runtime,'fit':fit,'max_seconds':max_seconds}
    if 'expected_data' in document:expected['expected_data']=document['expected_data']
    _require(_json(config)==expected and _json(handoff)==result,
             'constructed native input or returned handoff changed')
    c.finish();generated.finish();return result


def research_portfolio(proposal, context, *, proposal_base, context_pin, presented_pins):
    """Optional existing cycle admission, including every currently declared rival."""
    from . import research_blueprint
    return research_blueprint.bound_portfolio(proposal,context,proposal_base=proposal_base,
        context_pin=context_pin,presented_pins=presented_pins)


def portfolio_correspondence(proposal, base, presented_pins):
    """Optional complete recipe correspondence before existing cycle admission."""
    c=InputCapture();mp,manifest=_source(c,proposal['stage_correspondence'],base,document=True)
    _keys(manifest,('schema_version','recipe','stages'),'whole portfolio stage correspondence')
    _require(type(manifest['schema_version']) is int and manifest['schema_version']==1,
        'whole portfolio correspondence schema1 required')
    rp,_=c.pin(manifest['recipe'],mp.parent)
    _,_,_,_,_,stages,pairs,source=_load(rp)
    experiments={row['id']:row for row in proposal['experiments']};seen=set()
    for row in _rows(manifest['stages'],8):
        _keys(row,('experiment','stage'),'actual experiment stage binding')
        _require(row['experiment'] in experiments and row['experiment'] not in seen and row['stage'] in stages,
            'complete distinct current experiment/stage roster required')
        seen.add(row['experiment']);stage=stages[row['stage']][0]
        study=experiments[row['experiment']]['study']
        _require(type(study) is dict and set(study) in ({'path','sha256'},{'path','sha256','size'}),
            'closed original study pin required')
        original=stages[row['stage']][1]
        _require(science.regular(study['path'],base)==original and study['sha256']==stage['study']['sha256'] and
            ('size' not in study or type(study['size']) is int and study['size']==len(source.files[original][1])),
            'experiment differs from exact operative study source')
        _require(stage.get('target_mapping') is not None and
            not stage['missing'] and all(not pair['blockers'] for pair in pairs if row['stage'] in pair['stages']),
            'experiment must use the exact operative recipe study without unresolved blockers')
    _require(seen==set(experiments),'missing portfolio experiment cannot disappear from correspondence')
    presented={(str(science.regular(pin['path'],base)),pin['sha256']) for pin in presented_pins}
    for capture in (c,source):
        for path,(_,raw) in capture.files.items():
            _require((str(path),hashlib.sha256(raw).hexdigest()) in presented,
                'whole correspondence sources must be existing disclosed Host inputs')
        for path,(fact,_) in capture.streams.items():
            _require((str(path),fact[1]) in presented,'whole operative stage dependencies must be disclosed Host inputs')
        capture.finish()
    return manifest


def collect(request_path, runs, output):
    """Complete finite intake. Unknown/failed/unreviewed pairs remain explicit."""
    p,r,parent,_,_,stages,pairs,c=_load(request_path)
    _require(type(runs) is dict and set(runs)<=set(stages), 'known explicit ordinary result map required')
    out = _fresh(output,c,runs.values()) if output is not None else None
    if out is not None: out.mkdir(parents=True)
    emitted=Capture();observed=[];results={};terminal=[]
    for identity,(stage,_,_,_) in stages.items():
        row={'id':identity,'state':'not_executed','claim_scope':stage['claim_scope'],'result':None,'review':None,'exports':{}}
        if identity in runs:
            if stage.get('retained_producer',False):
                data=_accepted(stages[identity],runs[identity],c,_pin(p,c.files[p][1]));observed.append(data)
                _,raw=c.pin(data[2]['result'],data[0]);row.update(state='accepted_scope',result=_json(raw),
                    review=data[3],exports=data[2],rundir=str(data[0]),
                    full_output_inventory=[{'path':str(path),'sha256':science.execution.file_hash(path)} for path in sorted(data[5])],
                    retained_original_delivery=True)
                results[identity]=row
                continue
            rd=science.root(runs[identity]);science.verify_plan(rd,approved=True)
            effective=science.execution_spec(rd)
            _require('resonance_handoff' in effective,'terminal run lacks recipe binding')
            _,hb=c.read(effective['resonance_handoff'],rd);header=_json(hb)
            _require(header['request']==_pin(p,c.files[p][1]) and header['stage_id']==identity,'terminal run belongs to another recipe/stage')
            handoff_inputs(effective,rd)
            packet=science.packet(rd,write=False)
            _require(not packet['errors'], 'changed ordinary output cannot be silently classified')
            state=packet['execution']['status'];_require(state not in ('planned','approved','running'), 'terminal original evidence required')
            row['state']=state
            selected,_,_=science._selected(rd,read_json(rd/science.PLAN))
            _require(len(selected['outputs'])==1,'one ordinary output root required')
            native_root=rd/selected['outputs'][0];members=set();inventory=[]
            if native_root.exists():
                for file in native_root.rglob('*'):
                    _require(not file.is_symlink() and (file.is_file() or file.is_dir()),'ordinary terminal output inventory required')
                    c.ordinary(file,directory=file.is_dir())
                    if file.is_file():
                        pin={'path':str(file),'sha256':science.execution.file_hash(file)}
                        c.stream_pin(pin,rd,allow_empty=True);inventory.append(pin);members.add(file)
                if (native_root/'result.json').is_file():
                    _,rb=c.read(str(native_root/'result.json'),rd);row['result']=_json(rb)
            row['full_output_inventory']=inventory
            terminal.append((rd,effective,native_root,members))
            if state=='succeeded':
                view=physics_review.status(rd)
                if view['state']=='accepted' and view['claim_scope']==stage['claim_scope'] and not view['live_errors']:
                    data=_accepted(stages[identity],rd,c,_pin(p,c.files[p][1]));observed.append(data);row['state']='accepted_scope'
                    _,b=c.pin(data[2]['result'],rd);row['result']=_json(b);row['review']=data[3];row['exports']=data[2]
                else:row['state']='unreviewed_or_held'
            row['rundir']=str(rd)
        results[identity]=row
    records=[]
    for pair in pairs:
        constraints=[results[x] for x in pair['stages'] if stages[x][0]['role']=='constraint']
        # Review acceptance concerns the declared delivery scope, even when a
        # delivered native diagnostic reports failure. It is not an exclusion.
        state='blocked' if pair['blockers'] else ('accepted_scoped_deliveries' if constraints and all(x['state']=='accepted_scope' for x in constraints) else 'incomplete')
        exposed=[]
        for constraint in constraints:
            quantities=[]
            for quantity in stages[constraint['id']][0].get('quantities',[]):
                value=None;availability='unavailable'
                if constraint['result'] is not None:
                    try:value=_pointer(constraint['result'],quantity['pointer'])
                    except (KeyError,IndexError,TypeError,ValueError):pass
                    else:
                        _require(type(value) in (str,int,float,bool) or value is None,'constraint selector must preserve a source scalar, not a partial vector')
                        if type(value) is float:_number(value)
                        availability='returned' if value is not None else 'source_null'
                quantities.append({**quantity,'value':value,'availability':availability})
            exposed.append({'stage':constraint['id'],'state':constraint['state'],'claim_scope':constraint['claim_scope'],
                'result_status':None if constraint['result'] is None else constraint['result'].get('status'),'quantities':quantities})
        records.append({'pair_id':pair['id'],'hypothesis':pair['hypothesis'],'search':pair['search'],'state':state,
            'missing':'; '.join(pair['blockers']) or 'No declared applicability blocker; scientific meaning still requires review.',
            'constraint_states':json.dumps(exposed,sort_keys=True,allow_nan=False),
            'stage_targets':json.dumps(pair['stage_targets'],sort_keys=True,allow_nan=False),
            'scope':'Separate source-scoped constraints; no combined CLs or global resonance exclusion.'})
    if out is None:
        # Completion consumes the same current collection without creating a
        # report or treating a component review as whole-parent acceptance.
        _finish_accepted(observed,c)
        for rd,spec,root,members in terminal:
            science.verify_plan(rd,approved=True)
            _require(science.execution_spec(rd)==spec and {q for q in root.rglob('*') if q.is_file()}==members,'ending terminal study/source/output membership changed')
        c.finish()
        return {'pairs': records, 'stages': list(results.values()), 'parent_task_accepted': False}
    completion={'schema_version':1,'contract':r['parent_contract'],'outcomes':[],'parent_review':None,'report':None}
    completion_pin=_write(out,'task-completion.json',completion,emitted)
    parent_view=task_completion.evaluate(_pin3(out/'task-completion.json',_bytes(completion)),base_dir=p.parent)
    summary={'kind':'whole-resonance-search-intake','schema_version':1,'request':_pin(p,c.files[p][1]),
        'original_request':parent['prompt'],'census_scope':r['census_scope'],'hypotheses':r['hypotheses'],
        'searches':r['searches'],'correlations':r['correlations'],'pairs':records,'stages':list(results.values()),
        'cross_search_combination':None,'parent_completion':parent_view,'parent_task_accepted':False,
        'execution_authorized':False,'physics_validated':False}
    summary_pin=_write(out,'cross-search-summary.json',summary,emitted)
    # Use the real strict artifact/report consumer; missing values are literal
    # status strings, never fabricated zero limits. Full raw results stay above.
    from . import scientific_report
    basis_raw=c.files[p][1];(out/'original-recipe.json').write_bytes(basis_raw)
    emitted.read(str(out/'original-recipe.json'),out,hashlib.sha256(basis_raw).hexdigest())
    relative=Path('original-recipe.json')
    artifact={'schema_version':1,'contract':{'source_scope':'Complete supplied hypothesis/search census, separately scoped ordinary results.',
        'tool_fields':[{'field':'pairs','type':{'type':'array','max_items':32,'items':{'type':'object','properties':{k:'string' for k in records[0]}}},
            'source':{'kind':'direct','tool_id':'summary','pointer':'/pairs'}}],
        'interpretation_fields':[],'unresolved_semantics':[],'max_artifact_bytes':128000},
        'basis':[{'path':str(relative),'sha256':hashlib.sha256(c.files[p][1]).hexdigest(),'size':len(c.files[p][1])}],
        'tools':{'summary':dict(_pin3(out/'cross-search-summary.json',_bytes(summary)),path='cross-search-summary.json')},'interpretation':{}}
    facts=[];report_rows=[]
    for number,row in enumerate(records):
        ids=[]
        for key in ('pair_id','state','missing','constraint_states','stage_targets'):
            identity='p'+str(number)+'_'+key;ids.append(identity)
            facts.append({'id':identity,'selector':{'kind':'record','pointer':'/pairs','id_field':'pair_id','row_id':row['pair_id'],'field':key},
                'quantity_id':None,'context_selector':None,'label':key,'unit':'1','scope':row['scope'],
                'population':r['census_scope'],'limitations':['Declared source applicability is not physics validation; no global combined inference.']})
        report_rows.append({'id':'p'+str(number),'facts':ids})
    recipe={'schema_version':1,'title':'Resonance hypotheses and other-search constraints','artifact_request':artifact,'context':None,'facts':facts,
        'sections':[{'id':'complete_pairs','kind':'table','caption':'Every supplied physical hypothesis × search, including absent and incompatible constraints.',
            'columns':['Hypothesis × search','State','Missing information','Separate constraint states','Actual study targets and source premises'],'rows':report_rows}],
        'interpretation':['No combined likelihood or exclusion is inferred. Explicit shared/unknown correlations prevent a naive union.'],
        'task_completion':_pin3(out/'task-completion.json',_bytes(completion)),'delivery':'progress'}
    report=scientific_report.compose(recipe,base_dir=out)
    _write(out,'report-recipe.json',recipe,emitted);_write(out,'report.json',report,emitted)
    text=report['report_text'].encode();(out/'REPORT.md').write_bytes(text);emitted.read(str(out/'REPORT.md'),out,hashlib.sha256(text).hexdigest())
    _finish_accepted(observed,c)
    for rd,spec,root,members in terminal:
        science.verify_plan(rd,approved=True)
        _require(science.execution_spec(rd)==spec and {q for q in root.rglob('*') if q.is_file()}==members,'ending terminal study/source/output membership changed')
    c.finish();emitted.finish();return summary


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__);sub=parser.add_subparsers(dest='action',required=True)
    for action in ('assess','prepare','collect'):
        p=sub.add_parser(action);p.add_argument('--request',required=True)
        if action!='assess':p.add_argument('--runs',required=True);p.add_argument('--out',required=True)
        if action=='prepare':p.add_argument('--stage',required=True)
    args=parser.parse_args(argv)
    if args.action=='assess':result=assess(args.request)
    else:
        capture=Capture();path,raw=capture.read(args.runs,Path.cwd());runs=_json(raw)
        result=(prepare_stage(args.request,args.stage,runs,args.out) if args.action=='prepare' else collect(args.request,runs,args.out))
        capture.finish()
    print(json.dumps(result,indent=2,allow_nan=False));return 0


if __name__=='__main__':raise SystemExit(main())
