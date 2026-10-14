"""Complete returned LHE/analysis observations to the existing SFitter extractor.

This is a bin-observation consumer and a callable exporter protocol, not a new
analysis, generator, optimizer or detector model. Sampling and normalization
premises remain explicit. Every generator event, weight and declared group is
retained; source authentication does not prove the exporter executed honestly.
"""
from copy import deepcopy
import hashlib
import json
import math
from pathlib import Path
import tempfile

from ravel.physics import model_event_weights as weights
from ravel.physics import marked_response
from ravel.physics.ma5_saf import Capture as _Capture
from ravel.workflow import agent_graph, sfitter_workflow as workflow

SCOPE = 'sfitter_observed_event_rate_delivery'
MAX_PRODUCTS = 2_000_000
LIMITS = [
    'Authenticated source bytes and exact original-event joins do not prove native exporter execution or detector/selection validity.',
    'IID group sampling, group membership and independent-cohort relationships are explicit source-bound premises, not inferred from filenames or event counts.',
    'Fixed-N centered sample covariance and uncentered Poissonized group covariance are different estimators; neither supplies a finite-MC likelihood.',
    'Observed denominators use the existing extractor first-order ratio delta map; no exact ratio error law or interval calibration is claimed.',
    'Every held-out/training/shared-event cross-product is retained; withholding chronology, EFT applicability and physical basis equivalence remain unqualified.',
    'This protocol requires actual analysis weights equal the joined original LHE weights. Transformed shower/detector weight maps require separately supported explicit provenance.',
    'The bounded complete population refuses over-budget inputs; it never trims events, weights, points, bins or groups.',
]


def need(ok, message):
    if not ok: raise ValueError(message)


def keys(obj, expected, label):
    workflow._closed(obj, expected, label)


def text(value, label):
    workflow.sfitter_native._text(value, label)
    return value


def number(value):
    if type(value) is str:
        original=weights.number(value);value=float(original)
        need(original==0 or value!=0, 'nonzero decimal underflow cannot acquire binary64 group semantics')
    need(type(value) in (int, float) and math.isfinite(value), 'finite scalar required')
    return float(value)


def vector(value, n):
    need(type(value) is list and len(value) == n, 'complete ordered finite vector required')
    return [number(x) for x in value]


def decode(raw):
    return workflow._strict_document(raw)


def pins(capture):
    return [{'path':str(p), 'sha256':hashlib.sha256(raw).hexdigest()}
            for p, (_, raw) in sorted(capture.files.items())]


class Capture(_Capture):
    """Capture complete replay membership, rather than a suffix-selected subset."""
    def census(self, root):
        self.ordinary(root, directory=True)
        members=list(root.rglob('*'))
        need(len(members)<=32, 'bounded complete IR replay membership required')
        names=set()
        for p in members:
            self.ordinary(p, directory=p.is_dir())
            names.add(p.relative_to(root).as_posix())
        self.ordinary(root, directory=True)
        return names

    def bind_output_tree(self, root):
        """Close membership against committed outputs, never a new disk baseline."""
        root=Path(root).absolute();names=set()
        for path in self.files:
            if path.is_relative_to(root):
                names.add(path.relative_to(root).as_posix())
                for parent in path.parents:
                    if parent==root:break
                    names.add(parent.relative_to(root).as_posix())
        self.roots[root]=names


class StreamCapture:
    """Bounded streaming raw LHE identity, without loading a file into JSON memory."""
    def __init__(self): self.files = {}

    def pin(self, pin, base):
        keys(pin, ('path', 'sha256'), 'LHE source pin')
        p = Path(pin['path']); p = p if p.is_absolute() else Path(base).absolute()/p
        before = weights.regular_stream(p)
        need(0 < p.stat().st_size <= 64*1024**2, 'raw LHE size ceiling exceeded')
        digest = weights.raw_hash(p)
        need(weights.regular_stream(p) == before and digest == pin['sha256'], 'raw LHE pin/identity differs')
        old = self.files.get(p)
        need(old is None or old == (before, digest), 'conflicting original stream identity')
        self.files[p] = (before, digest)
        return p

    def finish(self):
        for p, (before, digest) in self.files.items():
            need(weights.raw_hash(p) == digest and weights.regular_stream(p) == before, 'ending original LHE changed')


class ObservationWriter:
    """Callable analysis-exporter sink; emit actual fills, full weights and vetoes.

    A caller must provide a row for every original event, including no-fill
    events. This helper does not perform an analysis or authenticate the caller.
    It commits each known serialized byte before writing and never recaptures
    changed output as an original commitment.
    """
    def __init__(self, path, header):
        self.path = Path(path).absolute(); self.capture = Capture()
        self.capture.ordinary(self.path.parent, directory=True)
        need(not self.path.exists(), 'fresh observation trace required')
        self.expected = bytearray(); self.count = 0
        self.stream = self.path.open('x+b')
        self._append(header)

    def _append(self, value):
        raw = (json.dumps(value, sort_keys=True, allow_nan=False, separators=(',', ':'))+'\n').encode()
        need(len(self.expected)+len(raw) <= 8*1024**2, 'complete observation trace exceeds byte ceiling')
        offset = len(self.expected); self.expected.extend(raw)
        self.stream.seek(0, 2)
        need(self.stream.tell() == offset, 'observation stream membership changed')
        self.stream.write(raw); self.stream.flush(); self.stream.seek(offset)
        need(self.stream.read(len(raw)+1) == raw, 'immediate emitted observation bytes differ')

    def _check(self):
        c = Capture(); _, raw = c.read(self.path, self.path.parent)
        need(raw == bytes(self.expected), 'emitted observation bytes differ'); c.finish()

    def record(self, row):
        need(type(row) is dict and row.get('ordinal') == self.count, 'complete ordered original event rows required')
        self._append(row); self.count += 1

    def finish(self, expected_events):
        try:
            need(type(expected_events) is int and self.count == expected_events, 'complete exporter event denominator required')
            self._check(); self.capture.ordinary(self.path.parent, directory=True)
            return {'path':str(self.path), 'sha256':hashlib.sha256(bytes(self.expected)).hexdigest()}
        finally:
            self.stream.close()


def ir_inputs(configuration, base):
    """The optional existing analysis-ir producer's complete original join graph."""
    keys(configuration, ('schema_version','generator','original_join','bins','region_bins','sources','response_weight_policy'), 'IR observation producer')
    need(type(configuration['schema_version']) is int and configuration['schema_version']==1, 'IR observation schema1 required')
    cap=Capture(); streams=StreamCapture(); gen=configuration['generator']
    keys(gen, ('lhe','events','weight_groups','maximum_decoded_bytes'), 'IR original generator')
    lp=streams.pin(gen['lhe'],base)
    jp,raw=cap.pin(configuration['original_join'],base);join=decode(raw)
    keys(join,('schema_version','lhe_sha256','records','sources'),'complete original join')
    need(type(join['sources']) is list and join['sources'], 'complete join provenance sources required')
    for pin in join['sources']:cap.pin(pin,jp.parent)
    cap.pin(configuration['bins'],base)
    need(type(configuration['sources']) is list and configuration['sources'], 'explicit reconstruction/join/source premises required')
    for pin in configuration['sources']: cap.pin(pin,base)
    policy=configuration['response_weight_policy']; keys(policy,('kind','source','description'),'explicit response weight premise')
    need(policy['kind']=='weight_invariant_same_objects', 'varying point response requires separate complete analysis bundles')
    text(policy['description'],'response premise');cap.pin(policy['source'],base)
    cap.finish();streams.finish()
    return pins(cap)+[{'path':str(lp),'sha256':gen['lhe']['sha256']}]


def emit_ir(result, configuration, base, output, *, program_pin, witness, _generated=None):
    """Use actual existing IR selection decisions; never recreate its analysis.

    The explicit original_join source supplies original ordinal/content and
    reconstructed object identity. A file-order coincidence is not a join.
    Region bins may overlap; their same-event cross-products are retained.
    """
    ir_inputs(configuration,base);cap=Capture();streams=StreamCapture()
    cap.pin(program_pin,base)
    _,raw=cap.pin(configuration['bins'],base);bins=decode(raw)
    need(type(bins) is list and bins, 'complete source bins required')
    mapping=configuration['region_bins']
    need(type(mapping) is list and len(mapping)==len(bins), 'one source region per ordered bin required')
    regions=[text(name,'region-bin mapping') for name in mapping]
    need(set(regions)==set(result['region_names']), 'full source region population must survive into bins')
    jp,raw=cap.pin(configuration['original_join'],base);join=decode(raw)
    keys(join, ('schema_version','lhe_sha256','records','sources'), 'complete reconstructed/original join')
    gen=configuration['generator'];lp=streams.pin(gen['lhe'],base)
    need(type(join['schema_version']) is int and join['schema_version']==1 and join['lhe_sha256']==gen['lhe']['sha256'], 'joined original stream must match')
    for pin in [*configuration['sources'],*join['sources']]:cap.pin(pin,base if pin in configuration['sources'] else jp.parent)
    with tempfile.TemporaryDirectory(prefix='sfitter-ir-join-') as tmp:
        journal=Path(tmp)/'original.jsonl'
        census=weights.scan(lp,expected_events=gen['events'],expected_groups=gen['weight_groups'],maximum_bytes=gen['maximum_decoded_bytes'],journal_path=journal)
        original=[decode(line) for line in journal.read_bytes().splitlines()]
    need(census['raw_sha256']==join['lhe_sha256'] and len(join['records'])==len(original)==len(result['decisions']), 'every original/reconstructed/decision event must join')
    names=['nominal',*[name for group in gen['weight_groups'] for name in group['ids']]]
    need(result['weight_names'] and all(name in names for name in result['weight_names']) and
         result['weight_names']==[name for name in names if name in result['weight_names']], 'IR observed streams must retain their source order')
    cap.pin(configuration['response_weight_policy']['source'],base)
    writer=ObservationWriter(output,{'schema_version':1,'kind':'sfitter-bin-observations/v1','lhe_sha256':gen['lhe']['sha256'],
                              'analysis_source_sha256':program_pin['sha256'],'bins':bins,'weight_ids':names})
    seen=set()
    try:
        for old, identity, decision, event in zip(original,join['records'],result['decisions'],result['inputs']['events']):
            keys(identity, ('event_id','ordinal','canonical_event_sha256','reconstructed_event_sha256'), 'explicit original-object identity')
            need(identity['event_id']==decision['event_id']==event['event_id'] and identity['event_id'] not in seen and
                 type(identity['ordinal']) is int and identity['ordinal']==old['ordinal'] and
                 identity['canonical_event_sha256']==old['canonical_event_sha256'] and
                 identity['reconstructed_event_sha256']==agent_graph.digest(event), 'explicit whole content join differs')
            seen.add(identity['event_id'])
            actual=[{'id':'nominal','value':old['nominal']},*old['weights']]
            for weight in actual:
                if weight['id'] not in result['weight_names']:continue
                got=event['weights'][weight['id']];want=number(weight['value'])
                need(got==want and (want!=0 or math.copysign(1.,got)==math.copysign(1.,want)), 'IR input weights must match original; transformed joins unsupported')
            writer.record({'ordinal':old['ordinal'],'canonical_event_sha256':old['canonical_event_sha256'],'weights':actual,
                 'vetoed':False,'fills':[{'bin_index':i,'fractions':[1.]*len(names)} for i,name in enumerate(regions) if name in decision['regions']]})
        pin=writer.finish(len(original))
        if _generated is not None:_generated.pin(pin,Path(output).parent)
        cap.finish();streams.finish()
        return {'trace':pin,'bins':configuration['bins'],'original_join':configuration['original_join'],
                'producer':'existing_analysis_ir_complete_decisions','generator':gen,'source':program_pin,
                'analysis_witness':witness,'region_bins':configuration['region_bins'],'response_weight_policy':configuration['response_weight_policy'],'analysis_consumed_weights':result['weight_names'],'emitted_full_original_weights':names,
                'physics_validated':False,'native_calls':0,'original_lhe_to_reconstructed_join_verified':'exact_supplied_content_join; provenance/response qualification separate'}
    finally:
        writer.stream.close()


def validate(task):
    keys(task, ('request',), 'observed-event bridge task'); text(task['request'], 'request pathname')
    return deepcopy(task)


def validate_scope(spec):
    policy = spec.get('review_policy', {}).get('policy', {})
    scopes = policy.get('claim_scopes', {})
    need(spec.get('schema_version') == 2 and spec.get('max_attempts') == 1 and
         policy.get('max_redos') == 0 and 0 < spec.get('max_seconds', 61) <= 60 and
         set(scopes) == {SCOPE} and scopes[SCOPE].get('actions') == ['delivery'],
         'one-attempt source-bound event-rate delivery scope required')


def _context(template, base, cap):
    from ravel.physics import sfitter_scan_extraction as extraction
    keys(template, ('schema_version','id','workflow','scan_definition','coupling_sanity_evidence','criteria'), 'extractor template')
    need(type(template['schema_version']) is int and template['schema_version'] == 1, 'template schema1 required')
    wp, raw = cap.pin(template['workflow'], base); wf = decode(raw); workflow.validate(wf)
    need(set(wf['handoffs']) == {'extraction','sm_template'}, 'full extraction and separate SM-template handoffs required')
    docs = {}
    for phase in ('extraction', 'sm_template'):
        hp, raw = cap.pin(wf['handoffs'][phase], wp.parent); doc = decode(raw)
        for pin in workflow._refs(doc): cap.pin(pin, hp.parent)
        workflow._handoff(wf, doc, hp.parent, phase); docs[phase] = doc
    for pin in workflow.input_pins(wf, wp.parent): cap.pin(pin, wp.parent)
    root, _ = workflow._knowledge(wf, wp.parent, 'parameterization')
    for relative in extraction.METHODS:
        cap.pin({'path':str(root/relative), 'sha256':workflow._known()[relative]}, root)
    cap.pin(template['coupling_sanity_evidence'], base)
    dp, raw = cap.pin(template['scan_definition'], base); definition = decode(raw)
    keys(definition, ('schema_version','target_sha256','points','sources'), 'source scan definition')
    need(type(definition['schema_version']) is int and definition['schema_version'] == 1 and
         definition['target_sha256'] == agent_graph.digest(wf['target']), 'exact source-defined target required')
    need(type(definition['points']) is list and 2 <= len(definition['points']) <= 512 and
         type(definition['sources']) is list and definition['sources'], 'complete original scan population and source required')
    for pin in definition['sources']: cap.pin(pin, dp.parent)
    ids = []
    for row in definition['points']:
        keys(row, ('id','component','role','values','selected_weight','weight_ids'), 'source-defined point')
        ids.append(text(row['id'], 'point identity'))
        need(set(row['values']) == set(wf['target']['eft']['basis']), 'complete Wilson basis required')
        for value in row['values'].values(): extraction._coordinate(value)
        need(row['selected_weight'] in row['weight_ids'] and len(set(row['weight_ids'])) == len(row['weight_ids']), 'complete named point weight census required')
    need(len(set(ids)) == len(ids), 'unique complete point identities required')
    bins = []
    for ob, ext in zip(wf['target']['observables'], docs['extraction']['payload']['rows']):
        for ident, width in zip(ob['bins'], ext['bin_widths']):
            bins.append({'observable_id':ob['ID'], 'bin_id':ident, 'unit':ob['unit'],
                         'representation':ob['representation'], 'bin_width':width})
    return wf, definition, bins


def _ir_evidence(document, base, analysis, cap):
    """Reverify the actual existing replay bundle, not supplier-written decisions."""
    from ravel.validation import analysis_witness
    keys(document, ('trace','bins','original_join','producer','generator','source','analysis_witness','region_bins',
                    'response_weight_policy','analysis_consumed_weights','emitted_full_original_weights',
                    'physics_validated','native_calls','original_lhe_to_reconstructed_join_verified'), 'IR producer delivery')
    need(document['producer']=='existing_analysis_ir_complete_decisions' and document['physics_validated'] is False and document['native_calls']==0,
         'source-object producer cannot acquire native/physics authority')
    need(document['trace']==analysis['trace'] and document['bins']==analysis['bin_definition'] and document['source']==analysis['source'],
         'analysis producer trace/bin/program commitments differ')
    witness=document['analysis_witness'];keys(witness, ('manifest',), 'actual IR replay witness')
    mp,raw=cap.pin(witness['manifest'],base);manifest=decode(raw)
    keys(manifest, ('schema_version','files'), 'actual IR manifest')
    expected={'program.json','contract.json','events.json','trace.json','result.json','verify.py'}
    need(type(manifest['files']) is dict and set(manifest['files'])==expected, 'whole IR witness population required')
    root=mp.parent; members=cap.census(root)
    need(members==expected|{'manifest.json','verification.json'}, 'complete original replay membership differs')
    cap.roots[root]=members
    cap.read(root/'verification.json',root)
    for name,sha in manifest['files'].items():cap.pin({'path':str(mp.parent/name),'sha256':sha},mp.parent)
    verification=analysis_witness.verify_bundle(mp.parent,witness['manifest']['sha256'])
    need(verification['passed'], 'actual IR independent replay refused')
    program=decode(cap.files[mp.parent/'program.json'][1]);events=decode(cap.files[mp.parent/'events.json'][1]);decisions=decode(cap.files[mp.parent/'trace.json'][1])
    contract=decode(cap.files[mp.parent/'contract.json'][1])
    need(document['analysis_consumed_weights']==contract['weight_names'], 'actual analysis stream order differs')
    need(manifest['files']['program.json']==analysis['source']['sha256'], 'actual IR program source differs')
    jp,raw=cap.pin(document['original_join'],base);join=decode(raw)
    keys(join, ('schema_version','lhe_sha256','records','sources'), 'whole replay original join')
    need(type(join['sources']) is list and join['sources'] and type(join['records']) is list and len(join['records'])==len(events), 'complete source-object join graph required')
    for pin in join['sources']:cap.pin(pin,jp.parent)
    policy=document['response_weight_policy'];keys(policy, ('kind','source','description'), 'source response premise')
    need(policy['kind']=='weight_invariant_same_objects', 'unsupported varying-point response');cap.pin(policy['source'],base)
    need(set(document['region_bins'])=={r['name'] for r in program['regions']}, 'complete source region/bin mapping required')
    cap.finish()
    return document,join,events,decisions


def _ir_row(evidence, row, original, names, group):
    document,join,events,decisions=evidence;i=row['ordinal']
    need(i<len(events), 'source-object decision ordinal outside full bundle')
    event,decision,ident=events[i],decisions[i],join['records'][i]
    keys(ident, ('event_id','ordinal','canonical_event_sha256','reconstructed_event_sha256'), 'source-object original identity')
    need(join['lhe_sha256']==document['generator']['lhe']['sha256'] and ident['ordinal']==i and
         ident['canonical_event_sha256']==original['canonical_event_sha256'] and ident['event_id']==event['event_id']==decision['event_id'] and
         ident['reconstructed_event_sha256']==agent_graph.digest(event), 'whole replay content join differs')
    need(event['group_id']==decision['group_id']==group, 'source/replay/group partition differs')
    need(document['emitted_full_original_weights']==names and set(document['analysis_consumed_weights'])==set(event['weights']) and
         set(event['weights'])==set(decision['weights']), 'original/replayed source weights differ')
    oldweights={'nominal':original['nominal'],**{r['id']:r['value'] for r in original['weights']}}
    for name,value in event['weights'].items():
        want=number(oldweights[name]);need(value==want and (want!=0 or math.copysign(1.,value)==math.copysign(1.,want)), 'actual replay weights differ from original')
    wanted=[{'bin_index':j,'fractions':[1.]*len(names)} for j,region in enumerate(document['region_bins']) if region in decision['regions']]
    need(row['fills']==wanted and row['vetoed'] is False, 'observation differs from actual complete source decisions')


def _load(request, base):
    keys(request, ('schema_version','id','extractor_template','cohorts','relationships','normalization'), 'event-rate request')
    need(type(request['schema_version']) is int and request['schema_version'] == 1, 'event-rate schema1 required')
    text(request['id'], 'delivery identity'); cap = Capture(); streams = StreamCapture()
    tp, raw = cap.pin(request['extractor_template'], base); template = decode(raw)
    wf, definition, bins = _context(template, tp.parent, cap)
    b = len(bins); points = definition['points']; q = len(points)*b
    need(1 <= q <= 256, 'complete rate/denominator coordinate ceiling exceeded')
    relation = request['relationships']; keys(relation, ('kind','description','source'), 'cohort relationship')
    need(relation['kind'] in ('one_shared_reweight_cohort','declared_independent_cohorts'), 'cross-cohort dependence must be explicitly supported')
    text(relation['description'], 'relationship premise'); cap.pin(relation['source'], base)
    cohorts = request['cohorts']
    need(type(cohorts) is list and 1 <= len(cohorts) <= 64 and
         (relation['kind'] != 'one_shared_reweight_cohort' or len(cohorts) == 1), 'bounded explicit complete cohorts required')
    owner = {}; loaded = []; cohort_ids = set(); cohort_hashes = set()
    for cohort in cohorts:
        keys(cohort, ('id','point_ids','generator','analysis','grouping','sampling'), 'observed cohort')
        ident = text(cohort['id'], 'cohort identity'); need(ident not in cohort_ids, 'duplicate cohort'); cohort_ids.add(ident)
        need(type(cohort['point_ids']) is list and cohort['point_ids'], 'explicit complete cohort point map required')
        for point in cohort['point_ids']:
            need(point in [p['id'] for p in points] and point not in owner, 'point missing/duplicate/unknown across cohorts'); owner[point] = ident
        sampling = cohort['sampling']; keys(sampling, ('law','description','source'), 'group sampling premise')
        need(sampling['law'] in ('fixed_N_IID_groups','poissonized_independent_groups'), 'no inferred group sampling law')
        text(sampling['description'], 'sampling premise'); cap.pin(sampling['source'], base)
        gen = cohort['generator']; keys(gen, ('lhe','events','weight_groups','maximum_decoded_bytes','sources'), 'original returned generator')
        need(type(gen['events']) is int and 1 <= gen['events'] <= 20000 and
             type(gen['maximum_decoded_bytes']) is int and 0 < gen['maximum_decoded_bytes'] <= 64*1024**2 and
             type(gen['sources']) is list and gen['sources'], 'complete bounded original exposure and source required')
        for pin in gen['sources']: cap.pin(pin, base)
        lp = streams.pin(gen['lhe'], base)
        need(gen['lhe']['sha256'] not in cohort_hashes, 'independent cohorts cannot reuse an identical original event stream'); cohort_hashes.add(gen['lhe']['sha256'])
        with tempfile.TemporaryDirectory(prefix='sfitter-observed-') as tmp:
            journal = Path(tmp)/'weights.jsonl'
            census = weights.scan(lp, expected_events=gen['events'], expected_groups=gen['weight_groups'],
                                  maximum_bytes=gen['maximum_decoded_bytes'], journal_path=journal)
            original = [decode(line) for line in journal.read_bytes().splitlines()]
        need(census['raw_sha256'] == gen['lhe']['sha256'], 'parser original source differs')
        names = ['nominal', *[w for group in gen['weight_groups'] for w in group['ids']]]
        for point in points:
            if point['id'] in cohort['point_ids']:
                need(point['weight_ids'] == names, 'all original named weights/order must match each point')
        gp, raw = cap.pin(cohort['grouping'], base); grouping = decode(raw)
        keys(grouping, ('schema_version','lhe_sha256','group_ids','description','sources'), 'complete correlation grouping')
        need(type(grouping['schema_version']) is int and grouping['schema_version'] == 1 and grouping['lhe_sha256'] == gen['lhe']['sha256'] and
             type(grouping['group_ids']) is list and len(grouping['group_ids']) == gen['events'], 'every original ordinal requires a source-declared group')
        text(grouping['description'], 'group interpretation'); need(type(grouping['sources']) is list and grouping['sources'], 'group provenance required')
        for pin in grouping['sources']: cap.pin(pin, gp.parent)
        group_order = []; last = None
        for group in grouping['group_ids']:
            text(group, 'group identity')
            if group != last:
                need(group not in group_order, 'noncontiguous group reappearance refuses'); group_order.append(group); last = group
        need(sampling['law'] != 'fixed_N_IID_groups' or len(group_order) > 1, 'one fixed-N group has unavailable covariance')
        analysis = cohort['analysis']; keys(analysis, ('trace','source','execution_evidence','bin_definition','producer_kind'), 'actual analysis observation')
        source, raw = cap.pin(analysis['source'], base)
        evidence_path,evidence_raw=cap.pin(analysis['execution_evidence'], base)
        need(analysis['producer_kind'] in ('analysis_ir_complete_decisions','supplied_observations'), 'explicit observation producer scope required')
        ir_evidence=None
        if analysis['producer_kind']=='analysis_ir_complete_decisions':
            ir_evidence=_ir_evidence(decode(evidence_raw),evidence_path.parent,analysis,cap)
            need(ir_evidence[0]['generator']=={k:v for k,v in gen.items() if k!='sources'}, 'actual producer original generator differs')
        _, raw = cap.pin(analysis['bin_definition'], base); need(decode(raw) == bins, 'analysis bin definition differs from exact whole target')
        tracep, raw = cap.pin(analysis['trace'], base); lines = raw.splitlines()
        need(len(lines) == gen['events']+1, 'trace must include every event/veto/no-fill and EOF')
        header = decode(lines[0]); keys(header, ('schema_version','kind','lhe_sha256','analysis_source_sha256','bins','weight_ids'), 'observation header')
        need(type(header['schema_version']) is int and header['schema_version'] == 1 and header['kind'] == 'sfitter-bin-observations/v1' and
             header['lhe_sha256'] == gen['lhe']['sha256'] and header['analysis_source_sha256'] == analysis['source']['sha256'] and
             header['bins'] == bins and header['weight_ids'] == names, 'actual original source/bin/full-weight header differs')
        observations = []; population = {name:[] for name in names}
        for old, line in zip(original, lines[1:]):
            row = decode(line); keys(row, ('ordinal','canonical_event_sha256','weights','vetoed','fills'), 'complete observed event row')
            need(type(row['ordinal']) is int and row['ordinal'] == old['ordinal'] and row['canonical_event_sha256'] == old['canonical_event_sha256'], 'exact original event ordinal/content join required')
            original_weights = [{'id':'nominal','value':old['nominal']}, *old['weights']]
            need(type(row['weights']) is list and len(row['weights']) == len(names), 'complete actual analysis weight vector required')
            for got, expected in zip(row['weights'], original_weights):
                keys(got, ('id','value'), 'actual observed weight')
                need(got['id'] == expected['id'] and type(got['value']) is str and weights.number(got['value']) == weights.number(expected['value']) and
                     (weights.number(expected['value'])!=0 or weights.number(got['value']).is_signed()==weights.number(expected['value']).is_signed()), 'original signed event weight join differs')
                population[got['id']].append(number(got['value']))
            need(type(row['vetoed']) is bool and type(row['fills']) is list and len(row['fills']) <= 1024 and
                 (not row['vetoed'] or not row['fills']), 'explicit veto/full fill population required')
            fractions = [[] for _ in range(b)]
            for fill in row['fills']:
                keys(fill, ('bin_index','fractions'), 'actual source bin fill')
                need(type(fill['bin_index']) is int and 0 <= fill['bin_index'] < b, 'unknown/flow bin requires explicit target coordinate')
                vals = vector(fill['fractions'], len(names))
                fractions[fill['bin_index']].append(vals)
            values = {name:[math.fsum(f[k] for f in fills)*population[name][-1] for fills in fractions]
                      for k, name in enumerate(names)}
            need(all(math.isfinite(v) for vals in values.values() for v in vals), 'actual bin sum/product overflows')
            if ir_evidence is not None:
                _ir_row(ir_evidence,row,old,names,grouping['group_ids'][row['ordinal']])
            observations.append(values)
        selected = [p for p in points if p['id'] in cohort['point_ids']]
        group_rows = []; members = {group:[] for group in group_order}
        for i, group in enumerate(grouping['group_ids']): members[group].append(i)
        for group in group_order:
            idx = members[group]
            rate = [math.fsum(observations[i][point['selected_weight']][k] for i in idx) for point in selected for k in range(b)]
            den = [math.fsum(population[next(r['denominator']['weight_id'] for r in request['normalization'] if r['point_id']==point['id']) or point['selected_weight']][i] for i in idx) for point in selected for k in range(b)]
            need(all(math.isfinite(v) for v in rate+den), 'group accumulation overflows'); group_rows.append(rate+den)
        need((2*len(selected)*b)**2*len(group_rows) <= MAX_PRODUCTS, 'complete event/group covariance budget exceeded')
        loaded.append({'cohort':cohort, 'points':selected, 'group_order':group_order, 'group_rows':group_rows,
                       'population':population, 'census':census, 'original':original, 'trace_header':header})
    need(set(owner) == {p['id'] for p in points}, 'all training/SM/single/mixed/held-out points required')
    normalization = request['normalization']; need(type(normalization) is list and [r.get('point_id') for r in normalization] == [p['id'] for p in points], 'complete original-order point normalization required')
    modes = set()
    for row in normalization:
        keys(row, ('point_id','scale','scale_uncertainty','denominator','description','source'), 'normalization contract')
        need(row['scale_uncertainty']=='conditional_fixed', 'uncertain normalization scale requires a supported joint extension')
        cap.pin(row['source'], base); text(row['description'], 'normalization definition')
        vector(row['scale'], b); d = row['denominator']; keys(d, ('kind','values','weight_id'), 'denominator rule')
        need(d['kind'] in ('fixed_external','observed_weight_sum'), 'explicit fixed or observed denominator required')
        need((d['kind'] == 'observed_weight_sum' and d['values'] is None and d['weight_id'] in next(a['population'] for a in loaded if row['point_id'] in a['cohort']['point_ids'])) or
             (d['kind'] == 'fixed_external' and d['weight_id'] is None and all(v != 0 for v in vector(d['values'], b))), 'literal fixed/observed denominator differs')
        modes.add(d['kind'])
    # The extractor has one closed denominator policy; mixed modes need a later typed extension.
    need(len(modes) == 1, 'mixed fixed/random denominator policies require explicit supported extension')
    need(len(cap.files)+len(streams.files)<=1024 and sum(len(raw) for _,raw in cap.files.values())+sum(p.stat().st_size for p in streams.files)<=128*1024**2, 'complete source census/aggregate byte ceiling exceeded')
    need(all(p.stat().st_size<=8*1024**2 for p in (*cap.files,*streams.files)), 'existing extractor per-source capture ceiling exceeded')
    cap.finish(); streams.finish()
    return cap, streams, template, tp.parent, wf, definition, bins, loaded


def input_pins(request, base):
    cap, streams, *_ = _load(request, base)
    return pins(cap)+[{'path':str(p),'sha256':digest} for p, (_, digest) in streams.files.items()]


def inputs(task, base, *, _session=None):
    validate(task); cap = Capture(); p, raw = cap.read(task['request'], base)
    result = [p, *[Path(pin['path']) for pin in input_pins(decode(raw), p.parent)]]; cap.finish()
    return result


def acquire(request, base):
    from ravel.physics import group_arithmetic
    cap, streams, template, template_base, wf, definition, bins, loaded = _load(request, base)
    points = definition['points']; b = len(bins); q = len(points)*b
    C = [[0.]* (2*q) for _ in range(2*q)]; sums = {}; populations = {}; diagnostics = []
    for arm in loaded:
        rows = arm['group_rows']; m = len(arm['points'])*b; n = len(rows)
        total = [math.fsum(r[i] for r in rows) for i in range(2*m)]
        if arm['cohort']['sampling']['law'] == 'fixed_N_IID_groups':
            moment = marked_response.empirical_group_mean(rows)
            covariance = [[n*n*v for v in row] for row in moment['covariance']]
            arithmetic = {'scope':'existing centered empirical group mean covariance scaled by N^2 for raw sums', 'forward_error_enclosure':None}
        else:
            gram = group_arithmetic.gram(list(map(list, zip(*rows))), maximum_pair_products=MAX_PRODUCTS)
            covariance = gram['matrix']; arithmetic = {k:v for k,v in gram.items() if k != 'matrix'}
        indices = [points.index(p)*b+k for p in arm['points'] for k in range(b)]
        indices += [q+i for i in indices]
        for i, target in enumerate(indices):
            for j, other in enumerate(indices): C[target][other] = covariance[i][j]
        for i, point in enumerate(arm['points']):
            sums[point['id']] = (total[i*b:(i+1)*b], total[m+i*b:m+(i+1)*b])
            pop = []
            for name, vals in arm['population'].items():
                original=[weights.number(row['nominal'] if name=='nominal' else next(w['value'] for w in row['weights'] if w['id']==name)) for row in arm['original']]
                pop.append({'id':name, 'events':len(original), 'positive':sum(v>0 for v in original), 'negative':sum(v<0 for v in original),
                            'zero':sum(v==0 for v in original), **arm['census']['weight_moments'][name]})
            populations[point['id']] = pop
        diagnostics.append({'cohort_id':arm['cohort']['id'], 'group_ids':arm['group_order'], 'group_vectors':rows,
                            'generator_census':arm['census'], 'original_event_population':arm['original'],
                            'sampling':arm['cohort']['sampling'], 'covariance_arithmetic':arithmetic,
                            'weight_population_scope':'Original Decimal token signs and 80-digit parser transport moments; bin covariance uses admitted binary64 values',
                            'acquisition':{'producer_kind':arm['cohort']['analysis']['producer_kind'],
                              'analysis_decisions_replayed':arm['cohort']['analysis']['producer_kind']=='analysis_ir_complete_decisions',
                              'ordinary_execution_verified':False,'native_transport_qualified':False}})
    uncertain = request['normalization'][0]['denominator']['kind'] == 'observed_weight_sum'
    all_sources = pins(cap)+[{'path':str(p),'sha256':digest} for p, (_, digest) in streams.files.items()]
    # The existing extractor's Capture admits <=8MiB source files. Do not falsely claim a larger graph can be consumed.
    need(all(Path(pin['path']).stat().st_size <= 8*1024**2 for pin in all_sources), 'existing extractor source capture ceiling exceeded; full files remain untrimmed')
    need(len(all_sources) <= 1024, 'existing extractor complete raw-source pin ceiling exceeded')
    outpoints = []
    for point, norm in zip(points, request['normalization']):
        rate, den = sums[point['id']]
        denom = den if uncertain else vector(norm['denominator']['values'], b)
        need(all(v != 0 and math.isfinite(v) for v in denom), 'observed normalization denominator is zero/nonfinite')
        arm=next(a for a in loaded if point['id'] in a['cohort']['point_ids']);cohort=arm['cohort']
        # The global census retains every transitive source. Each point locates
        # its contributing cohort instead of duplicating unrelated cohorts.
        direct=[cohort['generator']['lhe'],cohort['grouping'],norm['source'],*cohort['analysis'].values()]
        point_sources=[]
        for source in direct:
            if type(source) is not dict:continue
            p=Path(source['path']);p=p if p.is_absolute() else Path(base).absolute()/p
            pinned={'path':str(p),'sha256':source['sha256']}
            need(pinned in all_sources,'point source must belong to full authenticated population')
            if pinned not in point_sources:point_sources.append(pinned)
        outpoints.append({**{k:point[k] for k in ('id','component','role','values','selected_weight')}, 'rates':rate,
            'normalization':{'scale':vector(norm['scale'], b), 'denominator':denom,
                             'divide_by_bin_width':[v['representation']=='differential' for v in bins], 'description':norm['description']},
            'weight_population':populations[point['id']], 'sources':point_sources,
            'independence':{'declared':all(len(arm['points'])==1 for arm in loaded) and len(loaded)>1, 'basis':request['relationships']['description']}})
    order = [{'point_id':p['id'],'observable_id':x['observable_id'],'bin_id':x['bin_id'],'quantity':'rate'} for p in points for x in bins]
    deck = {'schema_version':1,'kind':'supplied_observed_scan_rates','target_sha256':agent_graph.digest(wf['target']),
            'eft':deepcopy(wf['target']['eft']), 'process':wf['target']['process'], 'perturbative_order':wf['target']['perturbative_order'],
            'bins':bins,'points':outpoints,'joint_covariance':{'coordinates':order+([{**x,'quantity':'denominator'} for x in order] if uncertain else []),
              'matrix':C if uncertain else [row[:q] for row in C[:q]], 'provenance':'Full source-declared original group estimator; '+request['relationships']['description']},
            'sampling':{'law':'supplied_joint_covariance','description':'Derived only under the explicit per-cohort group sampling laws recorded in event-rate diagnostics',
                        'source_relationships':request['relationships']['description']},'sources':all_sources,
            'normalization_uncertainty':'joint_delta_denominators' if uncertain else 'conditional_fixed_denominators'}
    report = {'schema_version':1,'kind':'sfitter_observed_event_rate_delivery','status':'passed','status_scope':SCOPE,
              'rate_deck':deck,'cohorts':diagnostics,'relationships':request['relationships'],'source_population':all_sources,
              'physics_validated':False,'execution_authorized':False,'native_fit_completed':False,'native_calls':0,
              'sampling_law_validated':False,'independence_proven':False,'limits':LIMITS}
    cap.finish(); streams.finish()
    return report, template, template_base, cap, streams


def _write(path, document, generated):
    raw = (json.dumps(document, sort_keys=True, indent=2, allow_nan=False)+'\n').encode()
    need(len(raw) <= 8*1024**2, 'complete emitted file exceeds capture ceiling')
    expected = hashlib.sha256(raw).hexdigest()
    with path.open('xb') as output: output.write(raw)
    generated.read(path, path.parent, expected)
    return {'path':str(path), 'sha256':expected}


def materialize(request_pin, base, output, *, _approved_output=False):
    from ravel.physics import sfitter_scan_extraction as extraction
    cap = Capture(); rp, raw = cap.pin(request_pin, base); request = decode(raw)
    report, template, template_base, original, streams = acquire(request, rp.parent)
    out = Path(output).absolute()
    need('..' not in out.parts and not any(p.is_symlink() for p in (out,*out.parents)) and
         (not out.exists() or (_approved_output and out.is_dir() and not list(out.iterdir()))) and
         not any(out.is_relative_to(p.parent) for p in (rp,*original.files,*streams.files)), 'fresh non-overlapping original-preserving output required')
    out.mkdir(parents=True, exist_ok=_approved_output); generated = Capture()
    deck = _write(out/'observed-scan-rates.json', report['rate_deck'], generated)
    next_request = workflow._absolute_pins(template, template_base); next_request['rates'] = deck
    req = _write(out/'scan-extraction-request.json', next_request, generated)
    # Exact existing loader is the final seam: no duplicate extractor or relaxed schema.
    admitted, *_ = extraction._load(next_request, out); admitted.finish()
    diagnostic = _write(out/'event-rate-diagnostics.json', report, generated)
    receipt = {'schema_version':1,'kind':'sfitter-observed-event-materialization','rates':deck,'extraction_request':req,
               'diagnostics':diagnostic,'physics_validated':False,'execution_authorized':False,'native_fit_completed':False}
    _write(out/'event-rate-receipt.json', receipt, generated)
    need({p.relative_to(out).as_posix() for p in out.rglob('*')} == {'observed-scan-rates.json','scan-extraction-request.json','event-rate-diagnostics.json','event-rate-receipt.json'}, 'closed complete output population differs')
    original.finish(); streams.finish(); cap.finish(); generated.finish()
    return receipt


def graph(request, base, request_pin):
    allpins = list({p['path']:p for p in [request_pin,*input_pins(request,base)]}.values())
    need(len(allpins) <= 128, 'full event-source Graph population exceeds bound')
    return agent_graph.validate({'schema_version':1,'graph_id':request['id']+'_events',
      'budget':{'max_nodes':1,'max_calls':1,'max_output_tokens':1,'max_wall_seconds':60,'max_reworks':0},
      'nodes':[{'id':'events','kind':'tool','role':'designer','depends_on':[],
        'inputs':[{'id':'request' if p['path']==request_pin['path'] else 'source'+str(i),**p} for i,p in enumerate(allpins)],
        'packet':None,'action':'sfitter-observed-events','parameters':{'request_input':'request'},'max_attempts':1}]})


def run(task, base, output):
    from ravel.workflow import science
    validate(task); out = Path(output).absolute(); plan = None
    for rd in (out,*out.parents):
        if (rd/'inputs/science-plan.json').is_file():
            plan = science.verify_worker(rd); spec = science.execution_spec(rd); validate_scope(spec)
            need(spec['mode']=='sfitter-observed-events' and spec['task']==task and out==(rd/plan['output_directory']).resolve(), 'exact approved event-rate task/output required')
            break
    need(plan is not None, 'ordinary approved event-rate worker required')
    cap=Capture(); rp,raw=cap.read(task['request'],base)
    receipt=materialize({'path':str(rp),'sha256':hashlib.sha256(raw).hexdigest()},base,out,_approved_output=True)
    returned=Capture(); _,raw=returned.pin(receipt['diagnostics'],out); result=decode(raw)
    cap.finish(); returned.finish(); return result


def main(argv=None):
    import argparse
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--request',required=True);parser.add_argument('--output',required=True)
    args=parser.parse_args(argv);cap=Capture();rp,raw=cap.read(args.request,Path.cwd())
    materialize({'path':str(rp),'sha256':hashlib.sha256(raw).hexdigest()},Path.cwd(),args.output);cap.finish();return 0


if __name__ == '__main__': raise SystemExit(main())
