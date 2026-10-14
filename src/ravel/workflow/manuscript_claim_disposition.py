"""Complete source-ordered planned claims, not a scientific truth certificate.

This is a pure contract shared by actual phase and manuscript consumers. The
ordinary producer authenticates the plan/receipts; independent integrity roles
judge the scientific meaning. No model label repairs a method or an experiment.
"""
from copy import deepcopy

from . import candidate_experiments as ce

MAX_CLAIMS = 160
DISPOSITIONS = ('retained', 'merged', 'qualified', 'withdrawn', 'unresolved')


def _text(value):
    if type(value) is not str or not value.strip() or len(value.encode()) > 16000:
        raise ValueError('bounded literal claim disposition text required')


def _ids(value, allowed):
    if type(value) is not list or len(value) > 255 or any(type(i) is not str for i in value) or len(set(value)) != len(value):
        raise ValueError('ordered unique claim disposition identities required')
    for identity in value:
        ce.identity(identity)
        if identity not in allowed:raise ValueError('foreign claim disposition identity')


def schema():
    def obj(p):return {'type':'object','properties':p,'required':list(p),'additionalProperties':False}
    text={'type':'string','minLength':1,'maxLength':16000}
    ids={'type':'array','items':{'type':'string'},'maxItems':255}
    original=obj({'id':{'type':'string'},'text':text,'status':{'type':'string','enum':[
        'supported-in-supplied-record','contradicted','conditional','unknown','proposed']},
        'scope':text,'evidence_ids':ids,'counterevidence_ids':ids,'method_ids':ids,
        'quantity_ids':ids,'citation_ids':ids,'limitations':{'type':'array','items':text,'maxItems':255},'section_ids':ids})
    limit=obj({'index':{'type':'integer','minimum':0},'text':text,'paragraph_ids':ids,'figure_ids':ids})
    row=obj({'planned_claim_id':{'type':'string'},'original':original,
        'disposition':{'type':'string','enum':list(DISPOSITIONS)},'paragraph_ids':ids,'figure_ids':ids,
        'related_claim_ids':ids,'reason':text,'evidence_ids':ids,'counterevidence_ids':ids,'unresolved_evidence_ids':ids,
        'limitations':{'type':'array','items':limit,'maxItems':255}})
    return {'type':'array','items':row,'maxItems':MAX_CLAIMS}


def validate(plan, rows, value, evidence, *, expected_ids=None, final=False, figures=None):
    """Validate all allocated originals and actual target/qualifier locations.

    A source-ordered row is required even for a withdrawal or unresolved claim.
    Final natural prose/captions must carry the literal scope, original limits
    and stated reason. Structural correspondence is not semantic acceptance.
    """
    originals={r['id']:r for r in plan['claim_map']}
    expected=list(originals) if expected_ids is None else list(expected_ids)
    _ids(expected,originals)
    if type(rows) is not list or len(rows)>MAX_CLAIMS or any(type(r) is not dict for r in rows) or [r.get('planned_claim_id') for r in rows]!=expected:
        raise ValueError('complete ordered planned claim disposition census required')
    paragraphs={p['id']:p for p in value['paragraphs']}
    captions={f['id']:f for f in value['figures']}
    if len(paragraphs)!=len(value['paragraphs']) or len(captions)!=len(value['figures']):
        raise ValueError('unique actual disposition targets required')
    by_id={}
    for row in rows:
        ce.keys(row,['planned_claim_id','original','disposition','paragraph_ids','figure_ids',
            'related_claim_ids','reason','evidence_ids','counterevidence_ids','unresolved_evidence_ids','limitations'])
        original=originals[row['planned_claim_id']]
        if row['original']!=original:raise ValueError('original planned status/scope/source/limitation changed')
        if row['disposition'] not in DISPOSITIONS:raise ValueError('typed claim disposition required')
        _text(row['reason']);_ids(row['paragraph_ids'],paragraphs);_ids(row['figure_ids'],captions)
        original_sources=set(original['evidence_ids']+original['counterevidence_ids'])
        allowed=set(evidence)|original_sources if not final else set(evidence)
        _ids(row['related_claim_ids'],originals);_ids(row['evidence_ids'],allowed);_ids(row['counterevidence_ids'],allowed)
        _ids(row['unresolved_evidence_ids'],allowed)
        missing=[i for i in dict.fromkeys(row['evidence_ids']+row['counterevidence_ids']) if i not in evidence]
        if row['unresolved_evidence_ids']!=missing or (final and missing):
            raise ValueError('missing claim sources must remain explicit and cannot supply acquisition credit')
        if not set(original['evidence_ids'])<=set(row['evidence_ids']):raise ValueError('disposition dropped original evidence')
        if not set(original['counterevidence_ids'])<=set(row['counterevidence_ids']):raise ValueError('disposition dropped original counterevidence')
        if row['disposition']=='merged':
            group=[i for i in originals if i in row['related_claim_ids']]
            if len(group)<2 or row['planned_claim_id'] not in group or group!=row['related_claim_ids']:
                raise ValueError('complete source-ordered reciprocal merge group required')
        elif row['related_claim_ids']:raise ValueError('only a declared merge may share a merge group')
        if any(paragraphs[i]['kind']!='claim' for i in row['paragraph_ids']):
            raise ValueError('claim disposition must locate actual scientific/limitations prose')
        if type(row['limitations']) is not list or len(row['limitations'])!=len(original['limitations']):
            raise ValueError('complete indexed literal limitation census required')
        for index,limit in enumerate(row['limitations']):
            ce.keys(limit,['index','text','paragraph_ids','figure_ids'])
            if type(limit['index']) is not int or limit['index']!=index or limit['text']!=original['limitations'][index]:
                raise ValueError('original indexed literal limitation changed')
            _ids(limit['paragraph_ids'],row['paragraph_ids']);_ids(limit['figure_ids'],row['figure_ids'])
            if final and not any(limit['text'] in paragraphs[i]['text'] for i in limit['paragraph_ids']) and not any(limit['text'] in captions[i]['caption'] for i in limit['figure_ids']):
                raise ValueError('original limitation lacks a literal final prose/caption location')
        if final:
            targets=[paragraphs[i]['text'] for i in row['paragraph_ids']]+[captions[i]['caption'] for i in row['figure_ids']]
            if not targets:raise ValueError('withdrawn/unresolved claims also require visible final response prose')
            if not any(original['scope'] in text for text in targets):raise ValueError('original scope lacks a literal final location')
            if not any(row['reason'] in text for text in targets):raise ValueError('disposition reason lacks a literal final location')
            sources=set(i for p in row['paragraph_ids'] for i in paragraphs[p]['evidence_ids'])
            for f in row['figure_ids']:
                if figures is None or f not in figures:raise ValueError('actual source-bound caption required')
                sources.update(figures[f]['evidence_ids'])
            if not set(row['evidence_ids']+row['counterevidence_ids'])<=sources:
                raise ValueError('disposition source/counterevidence not mapped to final targets')
        by_id[row['planned_claim_id']]=row
    for row in rows:
        if row['disposition']!='merged':continue
        for identity in row['related_claim_ids']:
            other=by_id.get(identity)
            if other is None or other['disposition']!='merged' or any(other[k]!=row[k] for k in ('related_claim_ids','paragraph_ids','figure_ids')):
                raise ValueError('merge omitted an original or changed its shared targets')
    return deepcopy(rows)


def located_items(census, request, text, units, evidence):
    """Derive independent audit rows from one authenticated complete census."""
    claims={r['id']:r for r in request['claims']};items=[]
    def locations(literal,identities):
        found=[]
        for identity in identities:
            unit=units[identity];fragment=text[unit['span']['start']:unit['span']['end']]
            offset=fragment.find(literal)
            if offset>=0:
                start=unit['span']['start']+offset
                found.append({'unit_id':identity,'span':{'start':start,'end':start+len(literal),'text':literal}})
        if not found:raise ValueError('literal claim qualifier missing from actual integrity manuscript')
        return found
    for row in census['rows']:
        targets=[]
        for identity in row['paragraph_ids']+['figure-'+i for i in row['figure_ids']]:
            if identity not in units or identity not in claims:raise ValueError('disposition target omitted from integrity claim census')
            unit=units[identity];claim=claims[identity];fragment=text[unit['span']['start']:unit['span']['end']]
            original_target=next((p['text'] for p in census['paragraphs'] if p['id']==identity),None)
            if original_target is None:original_target=next(f['caption'] for f in census['figures'] if 'figure-'+f['id']==identity)
            if claim['statement']!=original_target or original_target not in fragment:
                raise ValueError('integrity target differs from actual final writer prose')
            targets.append({'unit_id':identity,'span':deepcopy(unit['span']),'claim':deepcopy(claim)})
        items.append({'id':'planned-claim.'+row['planned_claim_id'],'kind':'planned-claim-disposition',
            'declared':deepcopy(row),'original':deepcopy(row['original']),'located_final_targets':targets,
            'literal_scope_locations':locations(row['original']['scope'],[t['unit_id'] for t in targets]),
            'reason_locations':locations(row['reason'],[t['unit_id'] for t in targets]),
            'literal_limit_locations':[{'index':limit['index'],'text':limit['text'],
                'locations':locations(limit['text'],limit['paragraph_ids']+['figure-'+i for i in limit['figure_ids']])} for limit in row['limitations']],
            'current_evidence':[deepcopy(evidence[i]['located']) for i in row['evidence_ids']],
            'current_counterevidence':[deepcopy(evidence[i]['located']) for i in row['counterevidence_ids']],
            'source_bindings':deepcopy(census['source_bindings']),
            'original_evidence':[deepcopy(census['original_evidence'][i]['located']) for i in dict.fromkeys(row['original']['evidence_ids']+row['original']['counterevidence_ids']) if i in census['original_evidence']],
            'original_missing_sources':[deepcopy(census['original_missing'][i]) for i in dict.fromkeys(row['original']['evidence_ids']+row['original']['counterevidence_ids']) if i in census['original_missing']],
            'question':'Audit this original planned claim and its complete disposition, literal scope/status, every indexed limitation, counterevidence and final use/withdrawal reason. Does the actual prose preserve all scientific qualifiers and negative results? An author label or rhetorical change cannot requalify a changed method/evidence/result; require the existing objection/protocol/fresh-review path. Honest withdrawal does not require inventing a successful experiment.'})
    return items
