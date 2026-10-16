"""Opt-in user delegation. Machine assent is never a physicist's decision.

The declaration and user text are ordinary approval inputs. Source commitments
establish retained provenance, not authenticated human identity. Revocation,
changed inputs, a scientific hold and exhausted bounds all stop new decisions.
"""
from __future__ import annotations
from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
from . import execution, review_context

ACTIONS = {'approve_plan','checkin2_go', 'accept_recommendation'}
REVOCATION = 'inputs/autonomy-revoked.json'
TRANSITION = 'inputs/autonomy-transition.json'
CI1_RESPONSE = 'inputs/checkin1-response.txt'


def _document(pin, base, *, max_bytes=2*1024**2):
    if type(pin) is not dict or set(pin) != {'path','sha256'}:
        raise ValueError('autonomy requires an exact source pin')
    path = Path(pin['path']); path = path if path.is_absolute() else Path(base)/path
    path = review_context._safe_path(path)
    from .validation_io import identity
    before = identity(path.stat())
    if not path.is_file() or not 0 < before[3] <= max_bytes:
        raise ValueError('bounded nonempty delegation source required')
    with path.open('rb') as stream:
        if identity(os.fstat(stream.fileno())) != before: raise ValueError('delegation source changed before read')
        raw = stream.read(before[3]+1)
        if identity(os.fstat(stream.fileno())) != before: raise ValueError('delegation source changed during read')
    if (identity(path.stat()) != before or len(raw) != before[3]
            or hashlib.sha256(raw).hexdigest() != pin['sha256']):
        raise ValueError('delegation consumed source differs from its commitment')
    return path, raw


def objective(document):
    """No change to any scientific/resource field is hidden by delegation."""
    return execution.digest({k:v for k,v in document.items() if k != 'autonomy'})


def delegation_intent(full_text):
    """Locate one affirmative authority clause in the retained whole message.

    Scientific conditions and notation elsewhere do not create or revoke
    authority. Quoted/source/example/conditional authority and conflicting
    autonomy instructions require clarification. No identity is inferred.
    """
    import re
    if type(full_text) is not str or not full_text.strip():return None
    mentions=list(re.finditer(r'\brun\s+autonomously\b',full_text,re.I))
    if len(mentions)!=1:return None
    hit=mentions[0]
    # Lex the retained prefix, not a sentence fragment. Paired typography and
    # ASCII/code quotations keep their scope across punctuation and new lines.
    # Contents of an open quotation cannot act as user instructions. A prime or
    # apostrophe after a word is notation, not an opening ASCII single quote.
    pairs={'"':'"', "'":"'", '`':'`', '“':'”', '‘':'’', '«':'»', '‹':'›'}
    closing=None;clause_start=0
    for index,char in enumerate(full_text[:hit.start()]):
        if closing is not None:
            escape_count=0;previous=index-1
            while previous>=0 and full_text[previous]=='\\':escape_count+=1;previous-=1
            if char==closing and escape_count%2==0:
                closing=None
                # Terminal punctuation inside a completed prior quotation
                # ends that source sentence. Start the outside authority
                # clause after its closing mark, not before it.
                prior=full_text[:index].rstrip()
                if prior and prior[-1] in '.!?;':clause_start=index+1
        elif char in pairs:
            if char=="'" and index and (full_text[index-1].isalnum() or full_text[index-1] in "_'"):continue
            closing=pairs[char]
        elif char in '.!?\n;':clause_start=index+1
    if closing is not None:return None
    # A colon introduces a heading scope. Subordinate headings and body lines
    # cannot discharge an earlier conditional/source/approval prerequisite.
    # Such a message needs an independent explicit authority confirmation;
    # sentence or blank-line formatting is not evidence that it was revoked.
    headings=[line.strip() for line in full_text[:hit.start()].splitlines()
        if line.rstrip().endswith(':')]
    if any(re.search(r'\b(?:if|unless|only|after|until|once|provided|when|approval|approve|confirmation|permission|example|quotation|source|manual|citation|excerpt)\b',header,re.I) for header in headings):return None
    if re.search(r'\b(?:do\s+not|don.t|never|not|revoke|cancel|stop)\b[^\n.!?]*\b(?:autonom|delegat)',full_text,re.I):return None
    # Heading form at the start of the message or a line: "Run autonomously:"
    # or "Run autonomously -". The rest of the message is its scope, so a
    # question or instruction after the heading is the delegated task itself.
    heading_line=full_text.rfind('\n',0,hit.start())+1
    heading=re.match(r'[ \t]*(?:please\s+)?(?P<command>run\s+autonomously)[ \t]*(?::|--?|–|—)(?=\s|$)',
                     full_text[heading_line:],re.I)
    if heading and heading_line+heading.start('command')==hit.start():
        scope=full_text[heading_line+heading.end():]
        prior=full_text[:heading_line]
        if (not scope.strip() or prior.count('```')%2 or prior.count('~~~')%2
                or full_text[heading_line:].lstrip().startswith('>')
                or re.search(r'\b(?:example|quotation|quoted|citation|excerpt|illustration|source)\s*[:=]\s*$',prior,re.I)
                or re.match(r'\s*(?:only\s+)?(?:if|unless|whether|when|after|once|provided|until)\b',scope,re.I)):
            return None
        span_start=heading_line+len(heading.group(0))-len(heading.group(0).lstrip())
        span_end=heading_line+heading.end()
        return {'start':span_start,'end':span_end,'text':full_text[span_start:span_end]}
    # Bound the actual instruction by sentence/line separators. Apostrophes in
    # physical notation in earlier sentences are not quotation delimiters.
    start=clause_start
    ends=[full_text.find(c,hit.end()) for c in ('.','!','?','\n',';')]
    end=min((x for x in ends if x>=0),default=len(full_text))
    clause=full_text[start:end];before=full_text[start:hit.start()];after=full_text[hit.end():end]
    line_start=full_text.rfind('\n',0,hit.start())+1
    line_end=full_text.find('\n',hit.end());line_end=len(full_text) if line_end<0 else line_end
    line=full_text[line_start:line_end]
    prefix_text=full_text[:start]
    if (full_text[:hit.start()].count('```')%2 or full_text[:hit.start()].count('~~~')%2
            or line.lstrip().startswith('>') or any(c in clause for c in ('"',"'",'`'))
            or (end<len(full_text) and full_text[end]=='?')):return None
    if re.search(r'\b(?:example|quotation|quoted|citation|excerpt|illustration|source)\s*[:=]\s*$',prefix_text,re.I):return None
    if re.search(r'\b(?:if|unless|whether|might|could|would|example|quoted|quotation|citation|excerpt|illustration)\b',clause,re.I):return None
    suffix=re.fullmatch(r'\s*|\s+(?:within|for|on|with|using|while|under|until)\b[^\n.!?]*',after,re.I)
    if not suffix:return None
    prefix=re.fullmatch(r'\s*(?:please\s+)?',before,re.I)
    compound=re.fullmatch(r'\s*(?:calculate|compute|evaluate|simplify|study|investigate|analyse|analyze|reproduce|reinterpret|perform|construct)\b[^\n?]*?(?P<join>\s+(?:and|then)\s+(?:please\s+)?)',before,re.I)
    if prefix:span_start=start+len(before)-len(before.lstrip())
    elif compound:span_start=start+compound.start('join')
    else:return None
    span_end=end
    if end<len(full_text) and full_text[end] in '.!':span_end+=1
    return {'start':span_start,'end':span_end,'text':full_text[span_start:span_end]}


def _affirmative_span(text, quote):
    span=delegation_intent(text)
    if span is None or type(quote) is not str or not quote.strip():
        raise ValueError('no unique unquoted affirmative delegation instruction; use CI1 confirmation')
    # The retained quote can be the exact directive or its entire original line.
    # Both are reconstructed from the complete message rather than trusted flags.
    line_start=text.rfind('\n',0,span['start'])+1
    line_end=text.find('\n',span['end']);line_end=len(text) if line_end<0 else line_end
    if quote.strip() not in (span['text'].strip(),text[line_start:line_end].strip(),text.strip()):
        raise ValueError('delegation quote differs from the actual actionable user span')
    return span


def _original_prompt(document,base,read):
    """Read the actual whole-task prompt, not an unrelated origin-labeled file."""
    if 'prompt' in document:
        contract=document;source=None
    else:
        binding=document.get('goal_binding')
        if document.get('schema_version')==1 and document.get('mode')=='literal-calculation':
            source=document.get('task',{}).get('parent_contract')
        elif type(binding) is dict and set(binding)=={'contract','assignment_id'}:
            source=binding['contract']
        else:
            raise ValueError('delegated scientific child requires the actual original-task binding')
        if type(source) is not dict or set(source)!={'path','sha256','size'}:
            raise ValueError('complete original-task source pin required')
        _,raw=read({k:source[k] for k in ('path','sha256')},base)
        if type(source['size']) is not int or len(raw)!=source['size']:
            raise ValueError('original task source size differs')
        contract=review_context._strict_json_bytes(raw)
    prompt=contract.get('prompt');requirements=contract.get('task_requirements')
    if type(prompt) is not str or not prompt.strip() or type(requirements) is not dict:
        raise ValueError('retained whole original task prompt/obligations required')
    prompt_sha=hashlib.sha256(prompt.encode('utf8')).hexdigest()
    if requirements.get('prompt_sha256')!=prompt_sha:
        raise ValueError('delegation original task prompt correspondence differs')
    return prompt,source,contract


def effective_document(document,base,*,sources=None):
    """Existing-run CI1 authority is opt-in sidecar, never a scientific-spec rewrite."""
    if 'autonomy' in document:return document
    path=Path(base)/TRANSITION
    if sources is None:
        if not path.exists():return document
        transition_pin={'path':str(path),'sha256':execution.file_hash(path)}
        _,raw=_document(transition_pin,base)
    else:
        raw=sources.get(str(path))
        if raw is None:return document
        transition_pin={'path':str(path),'sha256':hashlib.sha256(raw).hexdigest()}
        _,raw=_retained_document(transition_pin,base,sources)
    record=review_context._strict_json_bytes(raw)
    if (type(record) is not dict or set(record)!={'schema_version','kind','objective_sha256','declaration','source_binding'}
            or type(record['schema_version']) is not int or record['schema_version']!=1
            or record['kind']!='checkin1_delegation_transition' or record['objective_sha256']!=objective(document)):
        raise ValueError('CI1 authority transition differs from the original scientific document')
    read=lambda pin,where:_document(pin,where) if sources is None else _retained_document(pin,where,sources)
    _,declaration_raw=read(record['declaration'],base)
    value=review_context._strict_json_bytes(declaration_raw)
    if value.get('source_binding')!=record['source_binding'] or value.get('origin')!='checkin1_response':
        raise ValueError('CI1 transition declaration/source correspondence differs')
    return {**deepcopy(document),'autonomy':deepcopy(record['declaration'])}


def _plan_pinned_contract(document):
    return 'prompt' in document and 'task_mode' in document and type(document.get('request_plan')) is dict


def _source_binding(document,base,value,read):
    prompt,source,contract=_original_prompt(document,base,read)
    prompt_sha=hashlib.sha256(prompt.encode('utf8')).hexdigest()
    if document.get('schema_version')==1 and not _plan_pinned_contract(document):
        # A task contract that pins a request plan is reviewed at plan level by
        # plan_preauthorization before any machine approval; other version-1
        # documents keep their refusal.
        if document.get('mode')!='literal-calculation':raise ValueError('broader legacy scientific delegation requires schema2 review')
        from ravel.physics.literal_calculation import validate_parent
        numerical=validate_parent(document['task'],base)
        if numerical['original_request']!=prompt or numerical['parent_contract']!=source:
            raise ValueError('literal operation differs from authenticated original calculation')
    binding=value['source_binding']
    if value['origin']=='initial_prompt':
        expected={'kind':'original_task_prompt','task_contract':source,'prompt_sha256':prompt_sha}
        if binding!=expected:raise ValueError('initial delegation does not bind the actual original task')
    else:
        if type(binding) is not dict or set(binding)!={'kind','rundir','task_document','plan','checkin','prompt_sha256'} or binding['kind']!='checkin1_response':
            raise ValueError('exact existing-plan CI1 response binding required')
        root=Path(binding['rundir'])
        if not root.is_absolute() or root!=Path(base):raise ValueError('CI1 response belongs to another run')
        from . import science
        original_path=root/science.SPEC if (sources_plan:=binding['plan']['path'])==str(root/science.PLAN) else root/'inputs/task_contract.json'
        if binding['task_document']['path']!=str(original_path):raise ValueError('CI1 original task document path differs')
        permitted_plans={str(root/science.PLAN),str(root/'inputs/native_execution_plan.json')}
        if sources_plan not in permitted_plans or binding['checkin']['path']!=str(root/'inputs/checkin1.json'):
            raise ValueError('CI1 source is not the current ordinary plan/checkin')
        for name in ('task_document','plan','checkin'):
            _,raw=read(binding[name],root)
            if name=='task_document' and review_context._strict_json_bytes(raw)!={k:v for k,v in document.items() if k!='autonomy'}:
                raise ValueError('CI1 response cannot alter original scientific spec or ceilings')
        if binding['prompt_sha256']!=prompt_sha or value['user_text']['path']!=str(root/CI1_RESPONSE):
            raise ValueError('CI1 response must be the retained current run message for the actual task')
    return contract


def declaration(document, base, *, _sources=None):
    document=effective_document(document,base,sources=_sources)
    if 'autonomy' not in document: return None
    if not Path(document['autonomy']['path']).is_absolute():raise ValueError('delegation pin must preserve its absolute source identity')
    read=lambda pin,where:_document(pin,where) if _sources is None else _retained_document(pin,where,_sources)
    path, raw = read(document['autonomy'],base)
    value = review_context._strict_json_bytes(raw)
    fields={'schema_version','kind','origin','user_text','quote','delegate_actor','objective_sha256','actions','bounds','task_class','blinding_policy','source_binding','command_span'}
    if type(value) is not dict or set(value)!=fields or type(value['schema_version']) is not int or value['schema_version']!=2 or value['kind']!='user_delegated_autonomy':
        raise ValueError('closed explicit user-delegation schema required')
    if value['origin'] not in {'initial_prompt','checkin1_response'}:
        raise ValueError('autonomy must originate in supplied user text')
    user_path,user_raw=read(value['user_text'],path.parent)
    try: text=user_raw.decode('utf8')
    except UnicodeError: raise ValueError('user-delegation text must be UTF8') from None
    quote=value['quote']
    span=_affirmative_span(text,quote)
    if span!=value['command_span']:raise ValueError('delegation actionable span differs from complete retained user text')
    contract=_source_binding(document,base,value,read)
    if value['origin']=='initial_prompt' and text!=contract['prompt']:
        raise ValueError('initial delegation message is not the actual full original task request')
    if type(value['delegate_actor']) is not str or not value['delegate_actor'].strip():
        raise ValueError('named machine delegate required')
    actions=value['actions']
    if type(actions) is not list or not actions or len(actions)!=len(set(actions)) or not set(actions)<=ACTIONS:
        raise ValueError('explicit finite delegated decisions required')
    if value['objective_sha256']!=objective(document):
        raise ValueError('delegation cannot change the original objective or resource contract')
    bounds=value['bounds']
    if type(bounds) is not dict or set(bounds)-{'aggregate'}!={'compute_plans','allowed_changed_paths','allowed_stages','max_redos'}:
        raise ValueError('explicit original intervention bounds required')
    if 'aggregate' in bounds:
        from .completion_budget import validate_limits
        validate_limits(bounds['aggregate'])
    for k in ('compute_plans','allowed_changed_paths','allowed_stages'):
        rows=bounds[k]
        if type(rows) is not list or len(rows)>256 or len(rows)!=len(set(rows)) or any(type(r) is not str or not r.strip() for r in rows):
            raise ValueError('finite distinct delegated bounds required')
    if type(bounds['max_redos']) is not int or bounds['max_redos']<0:
        raise ValueError('finite redo limit required')
    if value['task_class'] not in {'deterministic_calculation','research_analysis'}:
        raise ValueError('explicit task classification required')
    if value['task_class']=='deterministic_calculation':
        if document.get('schema_version')!=1 or document.get('mode')!='literal-calculation':
            raise ValueError('only the validated literal calculation can be exempt from research CI3')
        from ravel.physics.literal_calculation import validate_parent
        validate_parent(document['task'],base)
    if value['blinding_policy'] is not None:
        if not Path(value['blinding_policy']['path']).is_absolute():raise ValueError('blinding policy must preserve absolute source identity')
        read(value['blinding_policy'],path.parent)
    return {'value':deepcopy(value),'declaration_path':str(path),'user_text_path':str(user_path),
            'authority_label':'machine_under_user_delegation','human_identity_authenticated':False}


def input_paths(document,base,*,sources=None):
    d=declaration(document,base,_sources=sources)
    if d is None:return []
    if 'derived_input_paths' in d:return list(d['derived_input_paths'])
    paths=[d['declaration_path'],d['user_text_path']]
    binding=d['value']['source_binding']
    if binding['kind']=='original_task_prompt' and binding['task_contract'] is not None:
        paths.append(binding['task_contract']['path'])
    if binding['kind']=='checkin1_response':
        paths.extend([str(Path(base)/TRANSITION),*[binding[k]['path'] for k in ('task_document','plan','checkin')]])
    if d['value']['blinding_policy'] is not None:
        read=lambda pin,b:_document(pin,b) if sources is None else _retained_document(pin,b,sources)
        path,_=read(d['value']['blinding_policy'],Path(d['declaration_path']).parent);paths.append(str(path))
    return paths


def _run_document(root):
    from . import science
    root=review_context._safe_path(root)
    path=root/science.SPEC if (root/science.PLAN).is_file() else root/'inputs/task_contract.json'
    committed={'path':str(path),'sha256':execution.file_hash(path)}
    _,raw=_document(committed,root)
    return root,effective_document(review_context._strict_json_bytes(raw),root)


def observed_run_document(root):
    """Legacy direct journal controls need not invent a task or delegation.

    Present task documents are always authenticated; only genuinely absent
    documents select legacy human steering. Existing review custody independently
    refuses deletion of any originally bound task document.
    """
    from . import science
    root=review_context._safe_path(root)
    if not (root/science.SPEC).exists() and not (root/'inputs/task_contract.json').exists():
        return root,{}
    return _run_document(root)


def authorize(root,action):
    """Current opt-in and original approval; no automatic scientific acceptance."""
    root,document=_run_document(root)
    d=declaration(document,root)
    if d is None:raise ValueError('human steering mode: no explicit delegation')
    if (root/REVOCATION).exists():raise ValueError('user delegation revoked; explicit escalation required')
    if action not in d['value']['actions']:raise ValueError('decision outside explicit delegation')
    from . import science,workflow_state,physics_review
    errors=(science.verify_approval_envelope(root) if (root/science.PLAN).is_file() else workflow_state.verify_approval(str(root)))
    if errors:raise ValueError('original approval/access requires escalation: '+'; '.join(errors))
    if physics_review.registered(root):
        reg,events=physics_review._read(root);physics_review._base_live(root,reg)
        view=physics_review._view(reg,events);physics_review._judgments_live(root,view)
        if view['state'] in {'stopped','scientific_hold','escalated'}:raise ValueError('scientific hold or stop cannot be delegated away')
        p=reg['policy'];b=d['value']['bounds']
        if (not set(b['allowed_changed_paths'])<=set(p['allowed_changed_paths'])
                or not set(b['allowed_stages'])<=set(p['allowed_stages']) or b['max_redos']>p['max_redos']):
            raise ValueError('delegation exceeds original approved correction authority')
    # Revalidate consumed declarations after approval/policy reads; do not return
    # an authority assembled from substituted, no-longer-current source bytes.
    if declaration(document,root)!=d:raise ValueError('delegated authority changed during admission')
    _,current=_run_document(root)
    if current!=document:raise ValueError('original task changed during delegated admission')
    if (root/REVOCATION).exists():raise ValueError('delegation revoked before decision return')
    return d


def revoke(root, *, user_text, quote):
    """Exclusive retained user steering receipt; never relabel as scientific vote."""
    root,document=_run_document(root);d=declaration(document,root)
    if d is None:raise ValueError('no delegated mode to revoke')
    path,raw=_document(user_text,root)
    if type(quote) is not str or not quote.strip() or quote not in raw.decode('utf8'):
        raise ValueError('revocation needs exact retained user text')
    record={'schema_version':1,'kind':'user_delegation_revoked','delegation':document['autonomy'],
            'user_text':deepcopy(user_text),'quote':quote,'human_identity_authenticated':False,'execution_authorized':False}
    target=root/REVOCATION
    with target.open('x',encoding='utf8') as stream:
        json.dump(record,stream,indent=2,allow_nan=False);stream.write('\n');stream.flush();os.fsync(stream.fileno())
    return record


def correction_authority(root, proposal):
    """Accept only the exact scientifically reviewed intervention inside user bounds."""
    d=authorize(root,'accept_recommendation');b=d['value']['bounds']
    from . import physics_review as review
    root=review._root(root);reg,events=review._read(root);view=review._view(reg,events)
    if (not set(proposal['changed_paths'])<=set(b['allowed_changed_paths'])
            or not set(proposal['stages'])<=set(b['allowed_stages'])
            or view['redos_used']>=b['max_redos']):
        reason = 'Reviewed correction exceeds delegated paths/stages/redo authority.'
        event = review.escalate(root, reason=reason, needed='Review the qualified ending or supply explicit revised authority.')
        ending = event['qualified_ending']
        if ending['status'] != 'recorded':
            raise ValueError(reason + ' Escalated; qualified ending requires repair: ' + ending['reason'])
        raise ValueError(reason + ' Escalated; qualified ending recorded without new authority.')
    return d


def notify_waiting(root, *, command=None):
    """Run an explicitly supplied argv with only run path and one-line reason.

    There is no default command, shell, inherited stdin or network operation.
    This reports a wait; it never approves or resumes the run.
    """
    if command is None:
        return {'status': 'disabled', 'execution_authorized': False}
    if (type(command) is not list or not command or len(command) > 32
            or any(type(v) is not str or not v or '\0' in v for v in command)
            or sum(len(v.encode()) for v in command) > 8192):
        raise ValueError('notification command must be an explicit bounded argv list')
    from . import physics_review
    root = review_context._safe_path(root)
    current = physics_review.status(root)
    if current['state'] == 'invalid':
        raise ValueError('notification requires intact review status')
    waiting = current['waiting_for_human']
    if waiting is None:
        return {'status': 'not_waiting', 'execution_authorized': False}
    reason = ' '.join(waiting['reason'].split())[:4096]
    import subprocess
    try:
        completed = subprocess.run([*command, str(root), reason], shell=False, timeout=10,
            stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            cwd=root, env={key: os.environ[key] for key in ('PATH', 'LANG') if key in os.environ}, check=False)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {'status': 'failed', 'error': type(exc).__name__, 'execution_authorized': False}
    return {'status': 'sent' if completed.returncode == 0 else 'failed',
            'returncode': completed.returncode, 'execution_authorized': False}


def prepare_declaration(document, out, *, user_text, quote, origin, delegate_actor,
                        actions, bounds, task_class, blinding_policy=None, base_dir):
    """Bind an explicit whole initial-prompt choice before plan approval.

    Returns a prospective document; never mutates an existing run/approval.
    The coordinator supplies the original finite bounds for the user to review.
    """
    out=review_context._safe_path(out)
    if out.exists():raise ValueError('fresh delegation source path required')
    if 'autonomy' in document:raise ValueError('existing delegation must remain immutable')
    path,user_raw=_document(user_text,base_dir)
    if origin!='initial_prompt':raise ValueError('existing CI1 response uses record_checkin1_delegation, not a fresh renamed plan')
    read=lambda pin,where:_document(pin,where)
    prompt,task_source,contract=_original_prompt(document,base_dir,read)
    if user_raw.decode('utf8')!=prompt:raise ValueError('initial user source must be the entire actual original task prompt')
    command_span=_affirmative_span(prompt,quote)
    source_binding={'kind':'original_task_prompt','task_contract':task_source,'prompt_sha256':hashlib.sha256(prompt.encode('utf8')).hexdigest()}
    if blinding_policy is not None:
        policy_path,_=_document(blinding_policy,base_dir)
        blinding_policy={'path':str(policy_path),'sha256':blinding_policy['sha256']}
    value={'schema_version':2,'kind':'user_delegated_autonomy','origin':origin,
        'user_text':{'path':str(path),'sha256':user_text['sha256']},'quote':quote,
        'delegate_actor':delegate_actor,'objective_sha256':objective(document),
        'actions':deepcopy(actions),'bounds':deepcopy(bounds),'task_class':task_class,
        'blinding_policy':deepcopy(blinding_policy),'source_binding':source_binding,'command_span':command_span}
    raw=(json.dumps(value,indent=2,sort_keys=True,allow_nan=False)+'\n').encode()
    prospective={**deepcopy(document),'autonomy':{'path':str(out),'sha256':hashlib.sha256(raw).hexdigest()}}
    # Refusal leaves no declaration that could be mistaken for admitted authority.
    import tempfile
    with tempfile.TemporaryDirectory(dir=out.parent) as temporary:
        staged=Path(temporary)/'declaration.json';staged.write_bytes(raw)
        staged_document={**prospective,'autonomy':{**prospective['autonomy'],'path':str(staged)}}
        declaration(staged_document,base_dir)
    with out.open('xb') as stream:stream.write(raw);stream.flush();os.fsync(stream.fileno())
    declaration(prospective,base_dir)
    return {'document':prospective,'delegation':deepcopy(value),'execution_authorized':False,
            'approval_required':True,'human_identity_authenticated':False}


def _retained_document(pin,base,sources):
    """Historical launch observation only; never used for current action authority."""
    if type(pin) is not dict or set(pin)!={'path','sha256'}:raise ValueError('exact retained delegation pin required')
    path=Path(pin['path']);path=path if path.is_absolute() else Path(base)/path
    raw=sources.get(str(path))
    if type(raw) is not bytes or not 0<len(raw)<=2*1024**2 or hashlib.sha256(raw).hexdigest()!=pin['sha256']:
        raise ValueError('retained user/delegation source commitment mismatch')
    return path,raw


# --------------------------------------------------------------------------- #
#  plan-level pre-authorization of a delegated CHECK-IN 1 (intake architecture §2.9, S1-08)
# --------------------------------------------------------------------------- #

SIGNATURES_PATH = Path(__file__).resolve().parents[1] / 'data' / 'operation_signatures.json'
PREAUTHORIZATION_CONDITIONS = (
    'pinned_records_invalid',            # the reading, plan or justification record does not verify
    'physics_critical_ambiguity_open',   # a physics-critical ambiguity row not decided by user text
    'inferred_physics_critical_fact',    # a physics-critical fact with inferred authority
    'statistic_differs_from_prescription',
    'boundary_not_user_chosen',
    'alternative_claim_not_user_chosen',
    'agent_inferred_critical_field',     # a physics-critical node field the agent inferred
    'adapter_default_unjustified',       # a physics-critical adapter default without an anchored justification
    'waypoint_none_delegated',           # waypoint none is approved only by a human
)
_STATISTIC_KINDS = ('exclusion', 'estimate', 'significance')
_MIN_JUSTIFICATION_WORDS = 8


def _critical_fields():
    """Operation -> critical field pointers, from the signature registry when it exists."""
    try:
        raw = SIGNATURES_PATH.read_bytes()
    except OSError:
        return {}
    registry = review_context._strict_json_bytes(raw)
    return {name: set(entry.get('critical_fields') or ()) for name, entry in registry.items()
            if isinstance(entry, dict)} if isinstance(registry, dict) else {}


def _span_key(span):
    return (span['start'], span['end'], span['text'])


def _user_decided(row, root):
    """A ledger row resolved by the user's own text: a request span or a pinned CHECK-IN answer."""
    resolution = row.get('resolution')
    if row.get('status') != 'resolved' or type(resolution) is not dict or resolution.get('by') != 'user':
        return False
    evidence = resolution.get('evidence')
    if type(evidence) is dict and set(evidence) == {'path', 'sha256'}:
        from ravel.validation import validate_task_contract
        try:
            validate_task_contract.read_pinned(str(root), evidence, 'user resolution')
        except ValueError:
            return False
    return True


def _anchor_errors(anchor, root):
    if anchor['kind'] == 'registered_invariant':
        from ravel.validation import validate_run_state
        if anchor['invariant'] not in {name for name, _, _ in validate_run_state.INVARIANTS}:
            return [f"invariant {anchor['invariant']!r} is not registered"]
    if anchor['kind'] == 'authoritative_practice' and anchor['source'] is not None:
        from ravel.validation import validate_task_contract
        try:
            validate_task_contract.read_pinned(str(root), anchor['source'], 'practice source')
        except ValueError as exc:
            return [str(exc)]
    return []  # a user_span anchor was already checked against the request bytes


def plan_preauthorization(root, document):
    """Rows that refuse a delegated approval of the pinned plan, and the defaults it adopts.

    Applies only to a task contract that pins a request plan. Each refusal names its
    condition and row. A physics-critical adapter default is not refused when a
    justification anchored in user text, a registered invariant or an authoritative-
    practice reference is recorded; it is returned in adopted_defaults for CHECK-IN 3.
    A human approval of the same plan is unaffected.
    """
    from ravel.validation import intake_records, validate_task_contract
    result = {'applies': False, 'refusals': [], 'adopted_defaults': []}
    if type(document) is not dict or 'request_plan' not in document:
        return result
    result['applies'] = True
    refuse = lambda condition, row, detail: result['refusals'].append(
        {'condition': condition, 'row': row, 'detail': detail})
    root = Path(root)
    errors = validate_task_contract.validate_pins(str(root), document)
    if errors:
        refuse('pinned_records_invalid', 'request_plan', '; '.join(errors)[:1000])
        return result
    reading = validate_task_contract.load_pinned(str(root), document, 'reading')
    plan = validate_task_contract.load_pinned(str(root), document, 'request_plan')
    justifications, errors = intake_records.load_delegated_defaults(str(root), document)
    if errors:
        refuse('pinned_records_invalid', intake_records.DELEGATED_DEFAULTS_PATH, '; '.join(errors)[:1000])
        justifications = None
    ambiguities = reading['ambiguities']
    decided = set()
    for row in ambiguities:
        if _user_decided(row, root):
            decided.update(row['blocks'])
        elif row['physics_critical']:
            # Never delegable: open, withdrawn, or decided by the delegate or an agent.
            refuse('physics_critical_ambiguity_open', row['id'], row['issue'])
    for fact in reading['facts']:
        if fact['physics_critical'] and fact['authority'] == 'inferred':
            refuse('inferred_physics_critical_fact', fact['id'], f"{fact['type']} has inferred authority")
    prescribed = [k for k in reading['constraints'] if k['type'] == 'prescribed_statistic']
    spans = {_span_key(span) for k in prescribed for span in k['evidence']}
    for claim in plan['claims']:
        statistic = claim['statistic']
        if statistic['source'] == 'prescribed':
            if not statistic['evidence'] or any(_span_key(s) not in spans for s in statistic['evidence']):
                refuse('statistic_differs_from_prescription', claim['id'],
                       'a prescribed statistic must cite the request span that prescribes it')
        elif prescribed and claim['kind'] in _STATISTIC_KINDS:
            refuse('statistic_differs_from_prescription', claim['id'],
                   f"the request prescribes a statistic; the claim uses {statistic['source']}")
    boundaries = {b['id']: b for b in reading['boundaries']}
    for bid in plan['boundaries']:
        row = boundaries.get(bid)
        if row is not None and row['class'] == 'control_bypass_request':
            continue  # a refused sentence is policy, not a choice the user makes
        if bid not in decided:
            refuse('boundary_not_user_chosen', bid, 'a boundary closes an obligation only on user text')
    offered = [b for b in reading['boundaries'] if b['class'] == 'unsupportable_claim']
    for claim in plan['claims']:
        weaker = [b['id'] for b in offered if set(b['obligation_ids']) & set(claim['obligation_ids'])]
        if weaker and claim['id'] not in decided and not any(b in decided for b in weaker):
            refuse('alternative_claim_not_user_chosen', claim['id'],
                   f"offered in place of an unsupportable claim ({', '.join(weaker)}); needs user text")
    for waypoint in plan['waypoints']:
        if waypoint['kind'] == 'none':
            refuse('waypoint_none_delegated', waypoint['id'], 'waypoint none is approved only by a human')
    critical = _critical_fields()
    entries = {(e['node'], e['pointer']): e for e in (justifications or {}).get('entries', ())}
    for node in plan['nodes']:
        known = critical.get(node['operation']) if node['operation'] is not None else None
        for field in node['fields']:
            # An operation without a signature cannot show a field is not physics-critical.
            if known is not None and field['pointer'] not in known:
                continue
            row = f"{node['id']}{field['pointer']}"
            if field['authority'] == 'agent_inference':
                # adopted only with an authorizing, externally anchored RDJ receipt
                # for exactly this value on an epoch-two run.
                from . import gate_wiring
                value = {'name': row, 'value': deepcopy(field['value']), 'origin': 'agent_inferred',
                         'critical': True, 'node_id': node['id']}
                phys = gate_wiring.physics_value_errors(root, value, delegated=True)
                if phys or not gate_wiring.epoch_two(root):
                    detail = '; '.join(f'{e.provider}:{e.code}' for e in phys) or 'no epoch-two PHYS-RDJ receipt'
                    refuse('agent_inferred_critical_field', row, f'an agent-inferred physics-critical value ({detail})')
            if field['authority'] != 'adapter_default':
                continue
            entry = entries.get((node['id'], field['pointer']))
            problems = []
            if entry is None:
                problems.append('no recorded justification')
            else:
                if entry['value'] != field['value']:
                    problems.append('the justification names a different value')
                if len(entry['justification'].split()) < _MIN_JUSTIFICATION_WORDS:
                    problems.append(f'the justification needs at least {_MIN_JUSTIFICATION_WORDS} words')
                problems += _anchor_errors(entry['anchor'], root)
                # The plan field's own anchor reference (the plan check's form) must name the same anchor.
                problems += intake_records.anchor_reference_errors(entry['anchor'], field['evidence'], reading)
            if problems:
                refuse('adapter_default_unjustified', row, '; '.join(problems))
            else:
                result['adopted_defaults'].append({'id': entry['id'], 'node': node['id'],
                    'pointer': field['pointer'], 'value': deepcopy(field['value']),
                    'anchor': deepcopy(entry['anchor']), 'justification': entry['justification']})
    return result


def adopted_defaults(root):
    """Physics-critical adapter defaults a delegated plan adopts, for listing at CHECK-IN 3.

    This is the seam the later decision-control record replaces; callers depend only
    on the returned rows {id, node, pointer, value, anchor, justification}.
    """
    root, document = _run_document(root)
    target = preauthorization_target(root, document)
    return [] if target is None else plan_preauthorization(*target)['adopted_defaults']


def preauthorization_target(root, document):
    """(root, contract) of the pinned plan that governs a delegated decision, or None.

    The run's own task contract when it pins a plan; otherwise the parent contract a
    goal-bound child or a literal calculation binds, when that parent pins a plan.
    """
    if type(document) is not dict:
        return None
    if 'request_plan' in document:
        return Path(root), document
    binding = document.get('goal_binding')
    source = binding.get('contract') if type(binding) is dict else None
    if source is None and document.get('mode') == 'literal-calculation':
        source = (document.get('task') or {}).get('parent_contract')
    if type(source) is not dict or not {'path', 'sha256'} <= set(source):
        return None
    path, raw = _document({k: source[k] for k in ('path', 'sha256')}, root)
    contract = review_context._strict_json_bytes(raw)
    if type(contract) is not dict or 'request_plan' not in contract:
        return None
    parent = path.parent.parent if path.parent.name == 'inputs' else path.parent
    return parent, contract


def preauthorization_errors(root, document):
    """One message per refusal row; empty when a delegated plan approval may proceed."""
    target = preauthorization_target(root, document)
    if target is None:
        return []
    return [f"{r['condition']} {r['row']}: {r['detail']}"
            for r in plan_preauthorization(*target)['refusals']]


def plan_authority(root, *, required_plan=None):
    """The initial user delegation admits a recommendation, not a native launch.

    Current complete plan/schema/cost validation is still performed by the
    ordinary approval command. This avoids circularly requiring a human CI1
    receipt before a machine may record the explicitly delegated CI1 decision.
    """
    root,document=_run_document(root);d=declaration(document,root)
    if d is None or 'approve_plan' not in d['value']['actions']:raise ValueError('initial/CI1 user plan delegation required')
    if (root/REVOCATION).exists():raise ValueError('user delegation revoked before plan approval')
    if required_plan is not None and required_plan not in d['value']['bounds']['compute_plans']:
        raise ValueError('recommended compute plan exceeds delegated finite choices')
    refusals = preauthorization_errors(root, document)
    if refusals:
        raise ValueError('delegated pre-authorization refused; a human approval of this plan is still '
                         'possible: ' + '; '.join(refusals))
    return d


def verify_decision(document,receipt,base,*,sources=None,action='approve_plan'):
    document=effective_document(document,base,sources=sources)
    d=declaration(document,base,_sources=sources)
    if (d is None or action not in d['value']['actions']
            or receipt.get('authority') not in ('machine_under_user_delegation', 'delegated_machine')
            or receipt.get('delegation')!=document.get('autonomy')
            or receipt.get('delegate_actor')!=d['value']['delegate_actor']
            or receipt.get('quote')!=d['value']['quote']):
        raise ValueError('machine plan/GO decision contradicts actual user delegation')
    if action == 'approve_plan':
        from .completion_budget import reserve_delegated
        reserve_delegated(document, d, base, check_only=True)
    return d


def record_checkin1_delegation(root,*,user_text,quote,delegate_actor,actions,bounds,
                               task_class,blinding_policy=None):
    """Retain the actual response and opt in at this existing, unapproved CI1.

    Called by the authorized coordinator on the supplied CI1 response. It does
    not ask for another human reply, rename/reinitialize the run, modify plan
    bytes, issue an approval, or claim OS authentication of the user.
    """
    from . import science
    root=review_context._safe_path(root)
    if (root/REVOCATION).exists():raise ValueError('revoked delegation cannot be recovered by a new CI1 message')
    if (root/science.APPROVAL).exists() or (root/'inputs/checkin1_approval.json').exists():
        raise ValueError('CI1 opt-in transition belongs before the existing approval; preserve prior receipts')
    if (root/TRANSITION).exists() or (root/CI1_RESPONSE).exists():raise ValueError('existing CI1 authority/message must remain immutable')
    _,document=_run_document(root)
    if 'autonomy' in document:raise ValueError('prior autonomy declaration must remain immutable')
    original=root/science.SPEC if (root/science.PLAN).is_file() else root/'inputs/task_contract.json'
    plan=root/science.PLAN if (root/science.PLAN).is_file() else root/'inputs/native_execution_plan.json'
    checkin=root/'inputs/checkin1.json'
    if plan.name==Path(science.PLAN).name:science.verify_plan(root)
    original_pins={k:{'path':str(p),'sha256':execution.file_hash(p)} for k,p in [('task_document',original),('plan',plan),('checkin',checkin)]}
    for pin in original_pins.values():_document(pin,root)
    _,response=_document(user_text,root);text=response.decode('utf8');span=_affirmative_span(text,quote)
    prompt,task_source,contract=_original_prompt(document,root,lambda p,b:_document(p,b))
    if blinding_policy is not None:
        bp,_=_document(blinding_policy,root);blinding_policy={'path':str(bp),'sha256':blinding_policy['sha256']}
    binding={'kind':'checkin1_response','rundir':str(root),**original_pins,'prompt_sha256':hashlib.sha256(prompt.encode()).hexdigest()}
    message_pin={'path':str(root/CI1_RESPONSE),'sha256':hashlib.sha256(response).hexdigest()}
    value={'schema_version':2,'kind':'user_delegated_autonomy','origin':'checkin1_response',
        'user_text':message_pin,'quote':quote,'delegate_actor':delegate_actor,
        'objective_sha256':objective(document),'actions':deepcopy(actions),'bounds':deepcopy(bounds),
        'task_class':task_class,'blinding_policy':deepcopy(blinding_policy),'source_binding':binding,'command_span':span}
    raw=(json.dumps(value,indent=2,sort_keys=True,allow_nan=False)+'\n').encode()
    declaration_path=root/'inputs/checkin1-delegation.json'
    declaration_pin={'path':str(declaration_path),'sha256':hashlib.sha256(raw).hexdigest()}
    transition={'schema_version':1,'kind':'checkin1_delegation_transition','objective_sha256':objective(document),
        'declaration':declaration_pin,'source_binding':binding}
    transition_raw=(json.dumps(transition,indent=2,sort_keys=True,allow_nan=False)+'\n').encode()
    # Validate the complete prospective authority before publishing anything.
    sources={str(root/CI1_RESPONSE):response,str(declaration_path):raw,
        str(root/TRANSITION):transition_raw,**{p['path']:_document(p,root)[1] for p in original_pins.values()}}
    if task_source is not None:
        sources[task_source['path']]=_document({k:task_source[k] for k in ('path','sha256')},root)[1]
    if blinding_policy is not None:sources[blinding_policy['path']]=_document(blinding_policy,root)[1]
    declaration(document,root,_sources=sources)
    for path,data in [(root/CI1_RESPONSE,response),(declaration_path,raw),(root/TRANSITION,transition_raw)]:
        with path.open('xb') as stream:stream.write(data);stream.flush();os.fsync(stream.fileno())
    d=declaration(document,root)
    for pin in original_pins.values():_document(pin,root)
    if (root/REVOCATION).exists():raise ValueError('CI1 delegation revoked before transition return')
    return {'delegation':d,'plan_unchanged':True,'approval_required':True,'execution_authorized':False,
        'human_identity_authenticated':False,'original_inputs':original_pins}
