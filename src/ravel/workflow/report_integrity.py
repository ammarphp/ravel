"""Complete declared manuscript audits using the existing scientific review path.

Exact spans and execution joins establish what was presented. They never establish bibliographic identity,
method equivalence, scientific correctness or publication acceptance by themselves.
The existing Graph owns calls, and physics_review owns decisions and corrections.
"""
from copy import deepcopy
import hashlib
import json
import os
import stat
import _thread
from pathlib import Path

from . import candidate_experiments as ce, decision_case, execution, state_io

MAX_ITEMS = 255
MAX_UNITS = 2048
MAX_BYTES = 2_000_000
MAX_TOTAL_BYTES = 32_000_000
MAX_CUSTODY_BYTES = 16 * 1024**3
MAX_CUSTODY_FILES = 4096
MAX_OPERATIONAL_FILES = 20000
MAX_OPERATIONAL_METADATA_BYTES = 16 * 1024**2
KINDS = {"claim", "method", "reference", "other"}


class CustodyInputs(dict):
    """Operational and presented inputs share identity, but have distinct byte budgets."""
    def __init__(self):
        super().__init__()
        self.presented = {}


def _text(value, maximum=16000):
    if type(value) is not str or not value.strip() or len(value.encode()) > maximum:
        raise ValueError("bounded explicit manuscript text required")


def _ordinary(path):
    path = Path(path).absolute()
    if any(p.is_symlink() for p in (path, *path.parents)) or not path.is_file():
        raise ValueError("ordinary existing manuscript evidence required")
    return path.resolve(strict=True)


def _artifact_path(pin, base, *, _observation=None):
    p = Path(pin["path"])
    actual = p if p.is_absolute() else Path(base)/p
    if _observation is None:
        return _ordinary(actual)
    _anchored_keywords(_observation)
    return _observation.path(pin['path'] if p.is_absolute() else actual)


def _raw(pin, base, consumed):
    ce.keys(pin, ["path", "sha256", "size"]); ce.sha(pin["sha256"])
    if type(pin["size"]) is not int or not 1 <= pin["size"] <= MAX_BYTES:
        raise ValueError("finite nonempty manuscript evidence required")
    p = _artifact_path(pin, base)
    before = p.stat(); raw = p.read_bytes(); after = p.stat()
    fields = ("st_dev", "st_ino", "st_size", "st_mtime_ns", "st_ctime_ns")
    if (tuple(getattr(before, k) for k in fields) != tuple(getattr(after, k) for k in fields)
            or len(raw) != pin["size"] or hashlib.sha256(raw).hexdigest() != pin["sha256"]):
        raise ValueError("manuscript evidence changed")
    absolute = {"path": str(p), "sha256": pin["sha256"], "size": len(raw)}
    old = consumed.get(str(p))
    if old is not None and old != absolute: raise ValueError("conflicting manuscript source identities")
    consumed[str(p)] = absolute
    if isinstance(consumed, CustodyInputs):
        consumed.presented[str(p)] = absolute
    text_members = consumed.presented if isinstance(consumed, CustodyInputs) else consumed
    if sum(row["size"] for row in text_members.values() if row["size"] <= MAX_BYTES) > MAX_TOTAL_BYTES:
        raise ValueError("complete manuscript evidence exceeds declared bound; no truncation")
    return raw


def custody_limits(value=None):
    """Operational capacity only; scientific text/model-presentation limits stay fixed."""
    defaults = {'max_files': MAX_CUSTODY_FILES, 'max_bytes': MAX_CUSTODY_BYTES,
                'max_metadata_bytes': MAX_BYTES}
    value = defaults if value is None else value
    ce.keys(value, defaults)
    ceilings = {'max_files': MAX_OPERATIONAL_FILES, 'max_bytes': MAX_CUSTODY_BYTES,
                'max_metadata_bytes': MAX_OPERATIONAL_METADATA_BYTES}
    if any(type(value[k]) is not int or not 1 <= value[k] <= ceilings[k] for k in defaults):
        raise ValueError('explicit finite supported operational custody limits required')
    return dict(value)


class CustodyAccumulator:
    """One unique-path union, including ending reads; never a per-leaf budget reset."""
    def __init__(self, limits=None):
        self.limits = custody_limits(limits)
        self.members = {}
        self.total_bytes = 0

    def add(self, pin):
        old = self.members.get(pin['path'])
        if old is not None and old != pin:
            raise ValueError('conflicting operational dependency identity')
        if old is None:
            self.members[pin['path']] = dict(pin)
            self.total_bytes += pin['size']
        if (len(self.members) > self.limits['max_files'] or self.total_bytes > self.limits['max_bytes']):
            raise ValueError('complete operational custody exceeds declared limits; no truncation')


def _operational_json(pin, base, consumed, *, limits=None, accumulator=None, _observation=None):
    """Bound complete metadata before decoding, without raising any prose/context limit."""
    selected = custody_limits(limits)
    ce.keys(pin, ['path', 'sha256', 'size']); ce.sha(pin['sha256'])
    if type(pin['size']) is not int or not 1 <= pin['size'] <= selected['max_metadata_bytes']:
        raise ValueError('bounded complete operational metadata required')
    if _observation is not None:
        _anchored_keywords(_observation)
        _observation.track(pin)
        if limits is not None: _observation.track(limits)
    p = _artifact_path(pin, base, **_anchored_keywords(_observation))
    flags = os.O_RDONLY | getattr(os, 'O_NOFOLLOW', 0) | getattr(os, 'O_NONBLOCK', 0)
    fd = os.open(p, flags) if _observation is None else _observation.open(p, flags)
    try:
        before = os.fstat(fd)
        if not stat.S_ISREG(before.st_mode):
            raise ValueError('regular operational metadata required')
        if before.st_size != pin['size']:
            raise ValueError('operational metadata changed: pinned size differs')
        with os.fdopen(fd, 'rb', closefd=False) as stream:
            raw = stream.read(pin['size'] + 1)
        after = os.fstat(fd)
    finally:
        os.close(fd)
    fields = lambda s: (s.st_dev, s.st_ino, s.st_mode, s.st_size, s.st_mtime_ns, s.st_ctime_ns)
    if (fields(before) != fields(after) or fields(after) != fields(_ordinary(p).stat() if _observation is None else _observation.ending(p)) or
            len(raw) != pin['size'] or hashlib.sha256(raw).hexdigest() != pin['sha256']):
        raise ValueError('operational metadata changed while read')
    absolute = {'path': str(p), 'sha256': pin['sha256'], 'size': len(raw)}
    if str(p) in consumed and consumed[str(p)] != absolute:
        raise ValueError('conflicting operational metadata identity')
    consumed[str(p)] = absolute
    budget = accumulator or CustodyAccumulator(selected)
    if budget.limits != selected: raise ValueError('one exact admitted operational policy required')
    for row in consumed.values(): budget.add(row)
    return _json(raw)


def _dependency(pin, base, consumed, *, limits=None, accumulator=None, _observation=None):
    """Stream a complete executed binary/input leaf without presenting it as text.

    The selected located evidence is still presented in full by _raw. A native
    runtime/input census may contain larger binary leaves; their commitments are
    dependencies, never a claim that a reviewer read those bytes or they loaded.
    """
    ce.keys(pin, ["path", "sha256", "size"]); ce.sha(pin["sha256"])
    selected = custody_limits(limits)
    if type(pin["size"]) is not int or not 0 <= pin["size"] <= selected['max_bytes']:
        raise ValueError("bounded complete stage dependency required")
    if _observation is not None:
        _anchored_keywords(_observation)
        _observation.track(pin)
        if limits is not None: _observation.track(limits)
    p = _artifact_path(pin, base, **_anchored_keywords(_observation)); h = hashlib.sha256(); total=0
    flags=os.O_RDONLY|getattr(os,'O_NOFOLLOW',0)|getattr(os,'O_NONBLOCK',0)
    fd=os.open(p,flags) if _observation is None else _observation.open(p,flags)
    try:
        before=os.fstat(fd)
        if not stat.S_ISREG(before.st_mode):
            raise ValueError('regular operational dependency required')
        if before.st_size!=pin['size']:
            raise ValueError('executed dependency changed: pinned size differs')
        with os.fdopen(fd,'rb',closefd=False) as stream:
            for chunk in iter(lambda:stream.read(1024**2),b''):
                total+=len(chunk)
                if total>pin['size']:raise ValueError('operational dependency grew while read')
                h.update(chunk)
        after=os.fstat(fd)
    finally:os.close(fd)
    ending=_ordinary(p).stat() if _observation is None else _observation.ending(p); fields = ("st_dev", "st_ino", "st_mode", "st_size", "st_mtime_ns", "st_ctime_ns")
    if (tuple(getattr(before, k) for k in fields) != tuple(getattr(after, k) for k in fields)
            or tuple(getattr(after,k) for k in fields)!=tuple(getattr(ending,k) for k in fields)
            or total != pin['size'] or h.hexdigest() != pin['sha256']):
        raise ValueError('executed dependency changed')
    absolute = {'path': str(p), 'sha256': pin['sha256'], 'size': pin['size']}
    if str(p) in consumed and consumed[str(p)] != absolute: raise ValueError('conflicting stage source identity')
    consumed[str(p)] = absolute
    budget = accumulator or CustodyAccumulator(selected)
    if budget.limits != selected: raise ValueError('one exact admitted operational policy required')
    for row in consumed.values(): budget.add(row)
    return absolute


def _operational_new(path, document, *, limits=None, consumed=None, accumulator=None):
    """Fresh complete operational JSON committed before write, with immediate readback.

    This does not change _new or any located scientific/presented-text allowance.
    The caller retains the returned intended pin for its ending observation.
    """
    selected=custody_limits(limits);path=Path(path).absolute()
    if path.exists() or any(q.is_symlink() for q in (path,*path.parents)) or not path.parent.is_dir():
        raise ValueError('fresh regular operational metadata destination required')
    raw=(json.dumps(document,indent=2,allow_nan=False)+'\n').encode()
    if not 1<=len(raw)<=selected['max_metadata_bytes']:
        raise ValueError('complete intended operational metadata exceeds declared capacity')
    intended={'path':str(path),'sha256':hashlib.sha256(raw).hexdigest(),'size':len(raw)}
    observed=CustodyInputs() if consumed is None else consumed
    budget=accumulator or CustodyAccumulator(selected)
    if budget.limits!=selected:raise ValueError('one exact admitted operational policy required')
    state_io.atomic_json(path,deepcopy(document))
    _operational_json(intended,path.parent,observed,limits=selected,accumulator=budget)
    _dependency(intended,path.parent,observed,limits=selected,accumulator=budget)
    return intended


def _json(raw):
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result: raise ValueError("duplicate manuscript JSON field")
            result[key] = value
        return result
    value = json.loads(raw, object_pairs_hook=pairs,
        parse_constant=lambda _: (_ for _ in ()).throw(ValueError("nonfinite manuscript JSON")))
    json.dumps(value, allow_nan=False)
    return value


def _span(text, row):
    ce.keys(row, ["start", "end", "text"])
    if (type(row["start"]) is not int or type(row["end"]) is not int
            or not 0 <= row["start"] < row["end"] <= len(text)
            or type(row["text"]) is not str or text[row["start"]:row["end"]] != row["text"]):
        raise ValueError("exact Unicode-character manuscript/source span required")
    return row["text"]


def _located(row, base, consumed):
    ce.keys(row, ["artifact", "format", "location", "value"])
    raw = _raw(row["artifact"], base, consumed)
    if row["format"] == "json":
        actual = decision_case.pointer(_json(raw), row["location"])
    elif row["format"] == "text":
        actual = _span(raw.decode("utf-8"), row["location"])
    else: raise ValueError("explicit text span or JSON pointer required")
    if ce.digest(actual) != ce.digest(row["value"]):
        raise ValueError("located source value differs")
    return {**deepcopy(row), "value": actual}


def _rows(rows, label, *, empty=True):
    if type(rows) is not list or len(rows) > MAX_ITEMS or (not empty and not rows):
        raise ValueError("complete finite " + label + " census required")
    return rows


def _ids(values, allowed):
    if type(values) is not list or len(values) != len(set(values)) or not set(values) <= set(allowed):
        raise ValueError("complete distinct references to the declared census required")
    return values


def _snapshot_member(record, field, pin):
    path = Path(pin["path"])
    for root, snapshot in record[field].items():
        for leaf in snapshot["files"]:
            candidate = Path(root) if leaf["name"] == "." else Path(root)/leaf["name"]
            if candidate == path and leaf["sha256"] == pin["sha256"] and leaf["size"] == pin["size"]:
                return True
    return False


def _executed(binding, code, results, base, consumed, *, limits=None, accumulator=None, _qualification_scope=None, _observation=None):
    """Current successful stage custody; an input declaration is not a load trace."""
    if binding is None:
        return {"state": "execution_evidence_missing", "runtime_consumption_verified": False}
    ce.keys(binding, ["rundir", "receipt"])
    selected = custody_limits(limits); budget = accumulator or CustodyAccumulator(selected)
    if budget.limits != selected: raise ValueError('one exact admitted operational policy required')
    record = _operational_json(binding['receipt'], base, consumed, limits=selected, accumulator=budget, **_anchored_keywords(_observation))
    rd = Path(binding["rundir"]); rd = rd if rd.is_absolute() else Path(base)/rd
    rd = rd.absolute()
    if any(p.is_symlink() for p in (rd, *rd.parents)): raise ValueError("ordinary execution root required")
    ledger = rd/execution.STATE_NAME
    _operational_json({"path":str(ledger),"sha256":execution.file_hash(ledger),"size":ledger.stat().st_size}, base, consumed, limits=selected, accumulator=budget, **_anchored_keywords(_observation))
    stage = record.get("stage")
    if type(stage) is not str:
        raise ValueError("method must bind its exact current retained stage")
    state = execution.load_execution(rd)
    if state["stages"].get(stage) != record:
        raise ValueError("method must bind its exact current retained stage")
    if execution.resolve_path(rd, record["attempt_record"]) != _artifact_path(binding["receipt"], base):
        raise ValueError("method receipt path differs from actual stage identity")
    if record.get("status") != "succeeded":
        return {"state": "failed_or_incomplete_retained_stage", "status": record.get("status"),
                "stage": stage, "attempt_id": record.get("attempt_id"), "runtime_consumption_verified": False}
    if _qualification_scope is None:
        errors = execution.stage_errors(rd, stage)
    else:
        from . import publication_runtime as pr
        if type(_qualification_scope) is not pr._QualificationScope:
            raise ValueError("exact private publication qualification scope required")
        errors = _qualification_scope.stage_errors(rd, stage, state, record, binding["receipt"], selected, base=base)
    if errors: raise ValueError("method execution custody differs: " + "; ".join(errors))
    for rows, field in ((code, "input_snapshot"), (results, "output_snapshot")):
        for located in rows:
            pin = consumed[str(_artifact_path(located["artifact"], base))]
            if not _snapshot_member(record, field, pin):
                raise ValueError("method source/result is not part of the same stage's declared custody")
    # Every executed leaf is a caller input, not merely the selected source/result.
    for field in ("input_snapshot", "output_snapshot"):
        for root, snapshot in record[field].items():
            for leaf in snapshot["files"]:
                path = Path(root) if leaf["name"] == "." else Path(root)/leaf["name"]
                _dependency({"path": str(path), **{k:leaf[k] for k in ("sha256", "size")}}, base, consumed, limits=selected, accumulator=budget, **_anchored_keywords(_observation))
    return {"state": "current_successful_stage", "stage": stage,
        "attempt_id": record["attempt_id"], "receipt_sha256": record["receipt_sha256"],
        "command": record["command"], "runtime": record["runtime"],
        "declared_stage_input_join_checked": True, "runtime_consumption_verified": False,
        "limitation": "Declared stage inputs/outputs do not prove each source was loaded or the method description was faithful."}


def prepare(request, *, base_dir, _claim_origin=None):
    """Resolve the whole declared manuscript and material audit population."""
    request = deepcopy(request)
    ce.keys(request, ["schema_version", "document_type", "applicability", "author_id", "manuscript",
        "units", "claims", "methods", "citations", "quantitative_report"] + (["formatting"] if "formatting" in request else [])
        + (["blinding_census"] if "blinding_census" in request else [])
        + (["planned_claim_census"] if "planned_claim_census" in request else []))
    if type(request["schema_version"]) is not int or request["schema_version"] != 1:
        raise ValueError("manuscript integrity/v1 required")
    if request["document_type"] not in {"manuscript", "research-report"}:
        raise ValueError("manuscript-specific audit is explicitly applicable; arithmetic reports keep their existing route")
    _text(request["applicability"]); ce.identity(request["author_id"])
    consumed = {}; text = _raw(request["manuscript"], base_dir, consumed).decode("utf-8")
    units = {}; cursor = 0
    if type(request["units"]) is not list or not 1 <= len(request["units"]) <= MAX_UNITS:
        raise ValueError("complete finite manuscript unit census required")
    for row in request["units"]:
        ce.keys(row, ["id", "kind", "span"]); identity = ce.identity(row["id"])
        if identity in units or row["kind"] not in KINDS or row["span"]["start"] != cursor:
            raise ValueError("nonoverlapping ordered full manuscript partition required")
        _span(text, row["span"]); cursor = row["span"]["end"]; units[identity] = deepcopy(row)
    if cursor != len(text): raise ValueError("every manuscript character, including references and prose, must be classified")
    ids = {}; selected = {}
    for kind, field in (("claim", "claims"), ("method", "methods"), ("reference", "citations")):
        selected[kind] = set(); ids[field] = []
        for row in _rows(request[field], field):
            identity = ce.identity(row["id"])
            if identity in ids[field]: raise ValueError("duplicate manuscript audit item")
            ids[field].append(identity)
            members = row["unit_ids"] if kind != "reference" else [row["reference_unit"]]
            _ids(members, units)
            if not members or any(units[u]["kind"] != kind or u in selected[kind] for u in members):
                raise ValueError("each declared scientific/reference unit requires exactly one census owner")
            selected[kind].update(members)
        if selected[kind] != {u for u in units if units[u]["kind"] == kind}:
            raise ValueError("claim/method/bibliography census does not cover its whole manuscript partition")
    items = []
    for row in request["claims"]:
        ce.keys(row, ["id", "unit_ids", "statement", "evidence", "citation_ids", "method_ids", "uncertainties"])
        _text(row["statement"]); _ids(row["citation_ids"], ids["citations"]); _ids(row["method_ids"], ids["methods"])
        for uncertainty in _rows(row["uncertainties"], "claim uncertainties"): _text(uncertainty)
        evidence = [_located(e, base_dir, consumed) for e in _rows(row["evidence"], "claim evidence")]
        items.append({"id": "claim."+row["id"], "kind": "claim", "declared": deepcopy(row), "presented_evidence": evidence,
            "question": "Do these exact sources and actual outcomes support the full claim, scope and uncertainty? Missing evidence stays unresolved."})
    for row in request["methods"]:
        ce.keys(row, ["id", "unit_ids", "description", "operations", "citation_ids", "uncertainties"])
        _text(row["description"]); _ids(row["citation_ids"], ids["citations"])
        for uncertainty in _rows(row["uncertainties"], "method uncertainties"): _text(uncertainty)
        operations = []; seen = set()
        for op in _rows(row["operations"], "method operations", empty=False):
            ce.keys(op, ["id", "description", "code", "execution", "results", "differences"])
            identity = ce.identity(op["id"])
            if identity in seen: raise ValueError("duplicate method operation")
            seen.add(identity); _text(op["description"])
            code = [_located(e, base_dir, consumed) for e in _rows(op["code"], "code evidence")]
            results = [_located(e, base_dir, consumed) for e in _rows(op["results"], "returned evidence")]
            for difference in _rows(op["differences"], "declared concomitant differences"): _text(difference)
            item = {"id": "operation."+row["id"]+"."+identity, "kind": "method-operation", "declared": deepcopy(op),
                "presented_code": code, "presented_results": results, "execution": _executed(op["execution"], code, results, base_dir, consumed),
                "question": "Compare the manuscript operation, actual code/API/options and same-stage returned evidence. Identify omitted/concomitant changes; source identity or AST similarity does not prove causal or scientific equivalence."}
            items.append(item); operations.append(item["id"])
        items.append({"id": "method."+row["id"], "kind": "method", "declared": deepcopy(row), "operations": operations,
            "question": "Does the complete method description match all executed operations and their actual scope? Audit operation census omissions too."})
    for row in request["citations"]:
        ce.keys(row, ["id", "reference_unit", "bibliography", "identity_evidence", "occurrences", "uncertainties"])
        ce.keys(row["bibliography"], ["title", "authors", "year", "identifiers"])
        for key in ("title", "year"): _text(row["bibliography"][key])
        for author in _rows(row["bibliography"]["authors"], "bibliography authors", empty=False): _text(author)
        for identifier in _rows(row["bibliography"]["identifiers"], "bibliography identifiers", empty=False): _text(identifier)
        for uncertainty in _rows(row["uncertainties"], "citation uncertainties"): _text(uncertainty)
        evidence = []
        for e in _rows(row["identity_evidence"], "bibliographic source evidence"):
            ce.keys(e, ["source_role", "source_url", "located"])
            if e["source_role"] not in {"primary-paper", "author-repository", "publisher-metadata", "secondary"}:
                raise ValueError("explicit citation source attribution required")
            _text(e["source_url"]); evidence.append({**deepcopy(e), "located": _located(e["located"], base_dir, consumed)})
        for occurrence in _rows(row["occurrences"], "citation occurrences"):
            ce.keys(occurrence, ["unit_id", "span"])
            if occurrence["unit_id"] not in units: raise ValueError("citation occurrence outside manuscript unit census")
            _span(text, occurrence["span"]); unit = units[occurrence["unit_id"]]["span"]
            if not unit["start"] <= occurrence["span"]["start"] < occurrence["span"]["end"] <= unit["end"]:
                raise ValueError("citation occurrence crosses its declared manuscript unit")
        items.append({"id": "citation."+row["id"], "kind": "bibliography-and-use", "declared": deepcopy(row), "presented_evidence": evidence,
            "question": "Verify title/authors/year/version/identifiers against actual primary content; then whether every located use supports the manuscript claim/method. Metadata matches and valid URLs alone do not establish applicability."})
    quantitative = None
    if request["quantitative_report"] is not None:
        from . import scientific_report
        binding = request["quantitative_report"]; ce.keys(binding, ["request", "span"])
        source_request = _json(_raw(binding["request"], base_dir, consumed))
        quantitative = scientific_report.compose(source_request, base_dir=_artifact_path(binding["request"], base_dir).parent)
        if _span(text, binding["span"]) != quantitative["report_text"]:
            raise ValueError("manuscript quantitative section must be the exact current ordinary report, not selected convenient slots")
        source_base = Path(binding["request"]["path"]); source_base = source_base if source_base.is_absolute() else Path(base_dir)/source_base
        for pin in scientific_report.input_pins(source_request, base_dir=source_base.parent): _raw(pin, source_base.parent, consumed)
    if 'formatting' in request:
        from . import manuscript_format
        binding=request['formatting'];ce.keys(binding,['contract','assessment','template'])
        contract=manuscript_format.load(binding['contract'],base_dir,consumed)
        assessment=_json(_raw(binding['assessment'],base_dir,consumed))
        if [row['rule'] for row in assessment['rules']]!=contract['rules']:
            raise ValueError('formatting audit must cover every exact publisher/challenge/user constraint')
        if binding['template'] is not None:_raw(binding['template'],base_dir,consumed)
        for row in assessment['rules']:
            items.append({'id':'format.'+row['rule']['id'],'kind':'formatting-instruction','declared':deepcopy(row),
                'render':contract['render'],'template':deepcopy(binding['template']),
                'question':'Check the actual instruction origin, venue/stage/article applicability and complete delivered source/PDF. Counts or a class name do not establish visual conformance; unmet template, layout, captions, disclosure and formatting concerns stay material for actual final visual review.'})
    if 'blinding_census' in request:
        census=request['blinding_census'];ce.keys(census,['policy','data','support','machinery','custody_only','complete_inputs','limit'])
        policy=_json(_raw(census['policy'],base_dir,consumed))
        populations={};seen=set()
        for kind in ('data','support','machinery','custody_only'):
            rows=[]
            for pin in _rows(census[kind],'complete manuscript '+kind):
                name=str(_artifact_path(pin,base_dir))
                if kind=='custody_only':
                    _dependency(pin,base_dir,consumed);raw=None
                else:raw=_raw(pin,base_dir,consumed)
                if name in seen:raise ValueError('blinding classification aliases a source across populations')
                seen.add(name)
                # Full support text is presented, including prose in template assets;
                # opaque support stays visible as such rather than silently safe.
                if kind=='custody_only':content={'encoding':'stage-custody-only-not-presented','size':pin['size']}
                else:
                    try:content={'encoding':'utf-8','text':raw.decode('utf-8')}
                    except UnicodeDecodeError:content={'encoding':'hex','text':raw.hex()} if kind=='support' else {'encoding':'binary-machinery','size':len(raw)}
                rows.append({'pin':deepcopy(pin),'content':content if kind!='data' else {'encoding':'public-projection-required','size':len(raw)}})
            populations[kind]=rows
        all_pins={str(_artifact_path(pin,base_dir)) for pin in census['complete_inputs']}
        if seen!=all_pins or len(all_pins)!=len(census['complete_inputs']):raise ValueError('whole source-derived blinding classification must retain every consumed author input')
        for pin in census['complete_inputs']:_dependency(pin,base_dir,consumed)
        items.append({'id':'blinding-source-census','kind':'source-blinding','declared':deepcopy(census),
            'original_policy':policy,'presented_population':populations,
            'question':'Apply the exact original blind-domain policy to the complete actual writer context and delivered prose. Numerical/result/figure inputs must be authenticated public projections. Inspect every support/template/task/publication and machinery classification for hidden data or complement leakage; classify any ambiguity as material send-back. This is an evidential judgment, never a hash/keyword or program noninterference proof.'})
    if 'planned_claim_census' in request:
        items.extend(_planned_claim_items(request,text,units,base_dir,consumed,_origin=_claim_origin))
    if len(items)+1 > decision_case.MAX_NODES: raise ValueError("complete material census exceeds existing decision-case budget")
    result = {"kind": "manuscript_integrity_preparation", "schema_version": 1, "request_sha256": ce.digest(request),
        "implementation_sha256": execution.file_hash(__file__), "manuscript": deepcopy(request["manuscript"]), "manuscript_text": text,
        "units": list(units.values()), "items": items, "quantitative_report": quantitative,
        "complete_declared_character_and_item_census": True, "semantic_census_verified": False,
        "bibliography_verified": False, "method_equivalence_verified": False,
        "scientific_acceptance": False, "execution_authorized": False,
        "input_pins": list(consumed.values()),
        "review_instructions": "Fresh original critic and verifier must inspect every material item and the complete census/classification. Retain missing/private sources and uncertain method applicability. Bind located material findings to ordinary send-back/repair; do not silently rewrite the scientific claim. Recompute scientific outputs if needed; manuscript edits alone cannot repair code/results. Existing decider synthesizes actual reviews; no extra universal manuscript roles."}
    if len(json.dumps(result, allow_nan=False).encode()) > MAX_BYTES:
        raise ValueError("complete presented manuscript exceeds current role-anchor budget; no silent panel truncation")
    for pin in result["input_pins"]: _dependency(pin, base_dir, {})
    return result


def _planned_claim_items(request,text,units,base_dir,consumed,*,_origin=None):
    from . import manuscript_production as mp, manuscript_claim_disposition
    census=_json(_raw(request['planned_claim_census'],base_dir,consumed))
    binding=_json(_raw(census['author_binding'],base_dir,consumed))
    # Reobserve the bounded real writer/complete phase transcript once. Do not
    # call materialize/verify_author here: those legitimately call prepare.
    loaded,receipt,saved,checkpoint,calls=mp._author_state(binding,_origin=_origin)
    presentation=_json(_raw(binding['presentation'],base_dir,consumed))
    context=presentation.get('planned_claim_context')
    if context is None:raise ValueError('planned census cannot borrow a legacy no-plan author')
    expected=mp._claim_census(binding,loaded,receipt['public_value'],context)
    if census!=expected:raise ValueError('planned claim census differs from actual current author/phase receipts')
    for pin in [binding['request'],*loaded['input_pins'],*[r['pin'] for r in calls]]:_dependency(pin,base_dir,consumed)
    for row in census['original_evidence'].values():_located(row['located'],base_dir,consumed)
    for row in census['original_missing'].values():_located(row['located'],base_dir,consumed)
    result=manuscript_claim_disposition.located_items(census,request,text,units,loaded['evidence'])
    # Joint ending observation, not one repeated Graph verification per claim.
    if mp._author_state(binding,_origin=_origin)!=(loaded,receipt,saved,checkpoint,calls):
        raise ValueError('actual planned-claim author changed during integrity observation')
    _raw(request['planned_claim_census'],base_dir,consumed)
    return result


def input_pins(request, *, base_dir):
    return prepare(request, base_dir=base_dir)["input_pins"]


def _new(path, document):
    """Commit intended bytes; never adopt a callback's altered return or file."""
    path = Path(path).absolute()
    if path.exists() or any(p.is_symlink() for p in (path, *path.parents)): raise ValueError("fresh ordinary audit artifact required")
    raw = (json.dumps(document, indent=2, allow_nan=False)+"\n").encode()
    expected = {"path": str(path), "sha256": hashlib.sha256(raw).hexdigest(), "size": len(raw)}
    state_io.atomic_json(path, deepcopy(document))
    if _raw(expected, path.parent, {}) != raw: raise ValueError("generated audit differs from intended bytes")
    return expected


def _case(prepared, request, presentation, request_pin):
    pending = {"reviewer_id": "pending-independent-review", "decision": "unresolved", "reason": "Fresh actual original role required"}
    def anchor(pin, location, value):
        return {"kind": "external_source", "artifact": {k:pin[k] for k in ("path", "sha256")}, "format": "json", "location": location, "value": deepcopy(value)}
    def node(identity, assertion, anchors):
        return {"id": identity, "assertion": assertion, "rationale": prepared["review_instructions"], "material": True,
            "author_id": request["author_id"], "review": deepcopy(pending), "assumptions": [], "unknowns": [], "anchors": anchors}
    nodes = [node("manuscript-integrity", "The complete manuscript census, bibliography/use and methods are supported within their declared scope; this is a proposed evidential judgment, not a scientific truth assertion.", [anchor(presentation, "", prepared), anchor(request_pin, "", request)])]
    edges = []
    for index, item in enumerate(prepared["items"]):
        nodes.append(node(item["id"], item["question"], [anchor(presentation, "/items/"+str(index), item)]))
        edges.append({"parent": "manuscript-integrity", "child": item["id"], "author_id": request["author_id"],
            "rationale": "Every declared item is required for this complete manuscript audit.", "review": deepcopy(pending),
            "request": {"kind": "evidence", "description": "Inspect the exact presented item and sources; request missing evidence or a discriminating/recomputation step if unresolved."}})
    case = {"schema_version": 1, "action": nodes[0]["assertion"], "root": nodes[0]["id"],
        "triggers": [{"kind": "unsupported_step", "reason": "Manuscript prose, citations and method/code relations need independent content review beyond quantitative-slot checks."}],
        "budget": {"max_nodes": len(nodes), "max_depth": 1}, "nodes": nodes, "edges": edges}
    return decision_case.validate_case(case)


def materialize(request, out, *, base_dir):
    """Build full public evidence/claim case for existing fresh review roles."""
    prepared = prepare(request, base_dir=base_dir); out = Path(out).absolute()
    if out.exists(): raise ValueError("fresh manuscript preparation directory required")
    if any(p.is_symlink() for p in (out, *out.parents)): raise ValueError("ordinary manuscript preparation directory required")
    out.mkdir(parents=True)
    presentation = _new(out/"presentation.json", prepared)
    request_pin = _new(out/"request.json", request)
    case = _case(prepared, request, presentation, request_pin)
    decision_case.validate_case(case)
    case_pin = _new(out/"public-case.json", case)
    if prepare(request, base_dir=base_dir) != prepared: raise ValueError("manuscript inputs changed during materialization")
    return {"preparation": presentation, "request": request_pin, "case": case_pin, "request_sha256": prepared["request_sha256"],
        "case_sha256": ce.digest(case), "execution_authorized": False, "scientific_acceptance": False}


def prepare_role(request, out, *, base_dir, rundir, role, actor_id, model, reasoning_effort,
                 max_output_tokens, max_wall_seconds, claim_scope, campaign=None, experiment=None):
    """Use original declared reviewers/budgets; creates no model call or vote."""
    from . import scientific_judgment
    if role not in {"critic", "verifier", "synthesizer"}: raise ValueError("original independent review/synthesis role required")
    if actor_id == request["author_id"]: raise ValueError("manuscript author cannot review their own content")
    prepared = prepare(request, base_dir=base_dir)
    root, _, _, view = scientific_judgment._live(rundir)
    manuscript = _artifact_path(request["manuscript"], base_dir)
    snapshot = next((p for p in view["cycle"]["snapshots"] if p["path"] == scientific_judgment.review._identity(root, manuscript)), None)
    if snapshot is None or snapshot["sha256"] != request["manuscript"]["sha256"]:
        raise ValueError("ordinary cycle must bind the exact manuscript before preparing located reviews/repairs")
    out = Path(out).absolute(); package = materialize(request, out/"manuscript", base_dir=base_dir)
    binding = scientific_judgment.prepare_role(rundir, out/"role", role=role, actor_id=actor_id,
        model=model, reasoning_effort=reasoning_effort, max_output_tokens=max_output_tokens,
        max_wall_seconds=max_wall_seconds, claim_scope=claim_scope, case_pin={k:package["case"][k] for k in ("path", "sha256")},
        campaign=campaign, experiment=experiment,
        case_dependencies=[{k:p[k] for k in ("path", "sha256")} for p in prepared["input_pins"]])
    return {"manuscript": package, "role_binding": binding, "execution_authorized": False}


def _verified(request, binding, base_dir):
    from . import scientific_judgment
    current = prepare(request, base_dir=base_dir)
    verified = scientific_judgment.verify_binding(binding)
    case = scientific_judgment._read_pin(verified["contract"]["case_pin"])
    root = next(n for n in case["nodes"] if n["id"] == case["root"])
    if (case["root"] != "manuscript-integrity" or len(root["anchors"]) != 2
            or root["anchors"][0]["value"] != current or root["anchors"][1]["value"] != request):
        raise ValueError("review must present this exact current complete manuscript census and sources")
    expected = _case(current, request, root["anchors"][0]["artifact"], root["anchors"][1]["artifact"])
    if case != expected:
        raise ValueError("review cannot omit/downgrade/reinterpret any manuscript item, source presentation or support edge")
    required = {(p["path"], p["sha256"]) for p in current["input_pins"]}
    actual = {(p["path"], p["sha256"]) for p in verified["contract"]["source_pins"]}
    if not required <= actual:
        raise ValueError("review must retain every original case evidence dependency through the ordinary consumer")
    if verified["contract"]["actor_id"] == request["author_id"]:
        raise ValueError("fresh manuscript reviewer must be independent of author")
    return current, verified


def consume_role(request, binding, *, base_dir):
    """Located issues go to the original journal/repair path, never auto-correct."""
    from . import scientific_judgment
    _, verified = _verified(request, binding, base_dir)
    return scientific_judgment.consume(verified["contract"]["rundir"], binding)


def assess(request, bindings, *, base_dir):
    """Read fresh actual dispositions; pending/held judgments remain visible."""
    from . import physics_review, scientific_judgment
    prepared = prepare(request, base_dir=base_dir); roles = {}; actors = set(); contracts = []
    for binding in _rows(bindings, "actual manuscript role bindings"):
        _, verified = _verified(request, binding, base_dir); contract = verified["contract"]
        role = contract["role"]
        if role not in {"critic", "verifier", "synthesizer"} or role in roles or contract["actor_id"] in actors:
            raise ValueError("distinct original critic/verifier/decider identities required")
        actors.add(contract["actor_id"]); roles[role] = verified; contracts.append(contract)
    for field in ("rundir", "cycle_id", "cycle_sha256", "claim_scope"):
        if contracts and len({c[field] for c in contracts}) != 1: raise ValueError("same original review cycle/scope required")
    census = [{"id": item["id"], "kind": item["kind"], "dispositions": {
        role: next(row for row in v["value"]["audit"]["nodes"] if row["id"] == item["id"])
        for role, v in roles.items()}} for item in prepared["items"]]
    complete = set(roles) == {"critic", "verifier", "synthesizer"}
    supported = complete and all(v["value"]["kind"] == "scientific_review" and v["value"]["verdict"] == "accept" for v in roles.values())
    ordinary_state = None
    if roles:
        ordinary_state = physics_review.status(contracts[0]["rundir"])
        _, events = physics_review._read(contracts[0]["rundir"])
        journal_reviews = [e for e in events if e["event"] == "review" and e["cycle_id"] == contracts[0]["cycle_id"]]
    if supported:
        if ordinary_state["state"] != "accepted" or ordinary_state["live_errors"] or ordinary_state["claim_scope"] != contracts[0]["claim_scope"]:
            supported = False
        else:
            # Require these actual source-bound decisions, not another accepted
            # cycle or direct fixture votes with coincident actor names.
            for role, verified in roles.items():
                expected = {row["path"]: row["sha256"] for row in verified["supporting_artifacts"]}
                vote = next((v for v in journal_reviews if v["role"] == scientific_judgment.ROLE[role]), None)
                actual = {} if vote is None else {row["path"]: row["sha256"] for row in vote.get("supporting_artifacts", [])}
                if not expected.items() <= actual.items(): supported = False
    if prepare(request, base_dir=base_dir) != prepared: raise ValueError("manuscript changed during review assessment")
    return {"kind": "manuscript_integrity_assessment", "request_sha256": prepared["request_sha256"],
        "manuscript": prepared["manuscript"], "manuscript_text": prepared["manuscript_text"], "item_census": census,
        "complete_actual_independent_roles": complete, "scoped_integrity_review_complete": supported,
        "ordinary_review_state": ordinary_state, "actual_public_judgments": {r:v["value"] for r,v in roles.items()},
        "bibliography_correctness_proven": False, "method_equivalence_proven": False,
        "scientific_acceptance": False, "publication_acceptance": False, "execution_authorized": False}


def assessment_pins(request, bindings, *, base_dir):
    result = input_pins(request, base_dir=base_dir)
    for binding in bindings:
        _, verified = _verified(request, binding, base_dir)
        for row in verified["supporting_artifacts"]:
            path = Path(row["path"]); path = path if path.is_absolute() else Path(verified["contract"]["rundir"])/path
            result.append({"path": str(path), "sha256": row["sha256"], "size": path.stat().st_size})
    return list({row["path"]: row for row in result}.values())


def manuscript(request, *, base_dir, bindings=None, final=False):
    """Deliver draft/audited manuscript without replacing parent/CI3 acceptance."""
    if type(final) is not bool: raise ValueError("explicit draft/final manuscript policy required")
    bindings = [] if bindings is None else bindings
    prepared = prepare(request, base_dir=base_dir)
    assessment = assess(request, bindings, base_dir=base_dir)
    if final and not assessment["scoped_integrity_review_complete"]:
        raise ValueError("final manuscript requires its current complete actual ordinary integrity decisions")
    return {"kind": "scientific_manuscript", "delivery": "reviewed-manuscript" if final else "draft",
        "report_text": prepared["manuscript_text"], "quantitative_report": prepared["quantitative_report"],
        "integrity": assessment, "original_census": prepared,
        "whole_parent_accepted": False, "publication_accepted": False, "physics_validated": False,
        "execution_authorized": False,
        "limits": ["A complete declared census is not automatic semantic completeness.",
            "Fresh evidence-bound reviewer judgments do not prove scientific or bibliographic correctness.",
            "Existing whole-parent completion and CHECK-IN 3 must separately bind the exact final manuscript."]}


class _AnchoredDirectoryCore:
    """Mechanical bounded descriptor registry; never an authority capability.

    Only independently source-gated wrappers may select this core. Each wrapper
    owns its immediate guards, real reads, terminal facts and failure-safe close.
    """
    MAX_DIRECTORY_FDS = 128
    MAX_PATH_RECORDS = 4096

    def __init__(self, session):
        self.session = session
        self.directories = {}
        self.records = {}
        self.acquired = []

    def _directory(self, path, expected, parent_fd=None, *, allow_new=True):
        entry = self.directories.get(path)
        if entry is None:
            if not allow_new or len(self.directories) >= self.MAX_DIRECTORY_FDS:
                return None
            flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
            fd = os.open(path if parent_fd is None else path.name, flags,
                         **({} if parent_fd is None else {'dir_fd': parent_fd}))
            # Register immediately, even if fstat or retaining the fact fails.
            self.acquired.append(fd)
            if _anchored_identity(os.fstat(fd))[:3] != expected:
                raise ValueError('anchored operational directory changed')
            self.session.retain_path_identity(path, expected)
            entry = (fd, expected)
            self.directories[path] = entry
        elif entry[1] != expected:
            raise ValueError('anchored operational directory identity changed')
        if _anchored_identity(os.fstat(entry[0]))[:3] != expected:
            raise ValueError('anchored operational directory descriptor changed')
        return entry[0]


    def _chain(self, record, *, observed=None):
        path, guard, chain, expected = record
        # Every complete absolute prefix is freshly observed. These full names
        # follow the live named root, unlike a detached directory-fd chain.
        for directory in chain:
            current = (_anchored_identity(os.lstat(directory))[:3]
                       if observed is None else observed[directory])
            if not stat.S_ISDIR(current[2]):
                raise ValueError('anchored ordinary directory required')
            if current != self.directories[directory][1]:
                raise ValueError('anchored operational directory identity changed')
        parent_fd, identity = self.directories[path.parent]
        # This is the actual descriptor used for the next relative leaf open.
        if _anchored_identity(os.fstat(parent_fd))[:3] != identity:
            raise ValueError('anchored operational parent descriptor changed')
        return parent_fd

    def close_all(self, closer):
        failures = []
        for fd in self.acquired:
            try:
                closer(fd)
            except BaseException as exc:
                failures.append(exc)
        self.acquired.clear()
        self.directories.clear()
        self.records.clear()
        return failures


class _AnchoredDependencyObservation(_AnchoredDirectoryCore):
    """Explicit worker-local path representation/descriptor reuse, never byte reuse.

    The opt-in scope commits ordinary ancestor identities for its full lifetime.
    The unchanged default reader has no such directory-identity commitment.
    """
    MAX_DIRECTORY_FDS = 128
    MAX_PATH_RECORDS = 4096

    def __init__(self):
        self.active = False
        self.closed = False
        self.context = None
        self.session = None
        _AnchoredDirectoryCore.__init__(self, None)
        self.pending = None
        self.tracked_values = {}
        self.pid = os.getpid()
        self.thread = _thread.get_ident()
        self.bindings = _anchored_bindings()
        self.cleanup = _ANCHORED_CANONICAL_CLEANUP

    def __enter__(self):
        if self.active or self.closed:
            raise ValueError('anchored operational owner cannot be reused')
        self.active = True
        return self

    def bind(self, context):
        from .readonly_preparation import WorkerReadOnlyObservation
        from .validation_io import ValidationSession
        if (type(context) is not WorkerReadOnlyObservation
                or type(context.session) is not ValidationSession
                or context.resources.get(_AnchoredDependencyObservation) is not self):
            raise ValueError('explicit source-owned worker observation required')
        context.require_active()
        if context.descriptor is None or context.draining and self.context is None:
            raise ValueError('selected source-owned read-only adapter required')
        if self.context is not None and self.context is not context:
            raise ValueError('anchored owner cannot cross worker observations')
        if self.context is None:
            self.context = context
            self.session = context.session
        self.readonly_check()
        return self

    def readonly_check(self):
        if (not self.active or self.closed or self.context is None or self.session.closed
                or self.context.session is not self.session
                or self.context.resources.get(_AnchoredDependencyObservation) is not self
                or os.getpid() != self.pid or _thread.get_ident() != self.thread
                or _anchored_bindings is not _ANCHORED_CANONICAL_READER
                or self.cleanup is not _ANCHORED_CANONICAL_CLEANUP
                or self.bindings != _ANCHORED_CANONICAL_BINDINGS
                or _anchored_bindings() != _ANCHORED_CANONICAL_BINDINGS):
            raise ValueError('anchored operational observation ownership changed')
        self.context.require_active()
        if getattr(self, 'frozen', False):
            if (tuple(self.directories.items()) != self.frozen_directories
                    or tuple(self.records.items()) != self.frozen_records
                    or tuple(self.acquired) != self.frozen_acquired):
                raise ValueError('anchored operational roster changed after freeze')

    def track(self, value):
        self.readonly_check()
        key = id(value)
        if key not in self.tracked_values:
            self.session.track(value)
            self.tracked_values[key] = value
        elif self.tracked_values[key] is not value:
            raise ValueError('anchored tracked object identity changed')

    def readonly_sessions(self):
        self.readonly_check()
        # Facts are enrolled in the incumbent worker Session, which is already
        # a participant. Do not duplicate it or create another runtime epoch.
        return ()

    def readonly_freeze(self):
        self.readonly_check()
        if getattr(self, 'frozen', False):
            raise ValueError('anchored operational owner already frozen')
        for path, (fd, expected) in self.directories.items():
            if (_anchored_identity(os.fstat(fd))[:3] != expected
                    or _anchored_identity(os.lstat(path))[:3] != expected):
                raise ValueError('anchored operational descriptor changed before freeze')
        self.frozen = True
        self.frozen_directories = tuple(self.directories.items())
        self.frozen_records = tuple(self.records.items())
        self.frozen_acquired = tuple(self.acquired)



    def _guard(self, record):
        path, guard, chain, expected = record
        observed = {}
        for candidate in guard:
            try:
                value = os.lstat(candidate)
            except OSError:
                return None
            if stat.S_ISLNK(value.st_mode):
                raise ValueError('ordinary existing manuscript evidence required')
            if candidate != path:
                observed[candidate] = _anchored_identity(value)[:3]
        try:
            if not stat.S_ISREG(path.stat().st_mode):
                raise ValueError('ordinary existing manuscript evidence required')
        except OSError:
            return None
        return observed

    def path(self, spelling):
        self.readonly_check()
        if self.pending is not None:
            raise ValueError('one anchored read boundary at a time required')
        p = spelling if isinstance(spelling, Path) else Path(spelling)
        # Explicit capability boundary, not a reduced input allowance.
        # All unsupported paths use the complete unchanged ordinary reader.
        if (os.name != 'posix' or not p.is_absolute() or str(p) != str(spelling)
                or '..' in p.parts or not hasattr(os, 'O_DIRECTORY')
                or not hasattr(os, 'O_NOFOLLOW') or os.open not in os.supports_dir_fd
                or os.stat not in os.supports_dir_fd or os.stat not in os.supports_follow_symlinks):
            actual = _ordinary(spelling)
            self.pending = (actual, None)
            return actual
        if getattr(self, 'disabled', False):
            actual = _ordinary(spelling)
            self.pending = (actual, None)
            return actual
        record = self.records.get(p)
        observed = None
        if record is None:
            actual = _ordinary(p)
            if actual != p or self.context.draining or len(self.records) >= self.MAX_PATH_RECORDS:
                self.pending = (actual, None)
                return actual
            guard = (p, *p.parents)
            chain = tuple(reversed(p.parents))
            missing = sum(directory not in self.directories for directory in chain)
            if len(self.directories) + missing > self.MAX_DIRECTORY_FDS:
                self.pending = (actual, None)
                return actual
            parent_fd = None
            try:
                for directory in chain:
                    current = _anchored_identity(os.lstat(directory))[:3]
                    if not stat.S_ISDIR(current[2]):
                        actual = p.resolve(strict=True)
                        self.pending = (actual, None)
                        return actual
                    parent_fd = self._directory(directory, current, parent_fd,
                                                allow_new=not self.context.draining)
            except OSError:
                # Descriptor optimization exhaustion/errors cannot create a
                # smaller input ceiling. Release every cached fd and use the
                # original reader. Existing Session commitments remain live.
                failures = self.close_all(self.bindings[0])
                self.disabled = True
                if failures:
                    raise failures[0]
                actual = _ordinary(p)
                self.pending = (actual, None)
                return actual
            # The leaf commitment is compared at every later boundary: take it once the
            # stamping clock has passed the leaf's change time (validation_io.settled).
            from .validation_io import settled
            expected = _anchored_identity(settled(lambda: os.lstat(p)))
            self.session.retain_path_identity(p, expected)
            record = (p, guard, chain, expected)
            self.records[p] = record
        else:
            # Leaf-to-root population/order is exact; reuse its actual lstat
            # observations for named-directory correspondence. Predicate errors
            # fall back to the original Path methods and strict resolver.
            observed = self._guard(record)
            if observed is None:
                actual = _ordinary(p)
                self.pending = (actual, None)
                return actual
        try:
            parent_fd = self._chain(record, observed=observed)
        except OSError:
            # Resolver fallback observes current names and original errors.
            actual = p.resolve(strict=True)
            self.pending = (actual, None)
            return actual
        self.pending = (p, parent_fd)
        return p

    def open(self, path, flags):
        self.readonly_check()
        if self.pending is None or self.pending[0] != path:
            raise ValueError('exact immediate anchored read boundary required')
        _, parent_fd = self.pending
        self.pending = None
        if parent_fd is None:
            return os.open(path, flags)
        # _chain has just established complete named-root correspondence.
        # Recheck the fd used by the actual open, without serving an old tree.
        expected = self.directories[path.parent][1]
        if _anchored_identity(os.fstat(parent_fd))[:3] != expected:
            raise ValueError('anchored operational parent descriptor changed')
        return os.open(path.name, flags, dir_fd=parent_fd)

    def ending(self, path):
        self.readonly_check()
        record = self.records.get(path)
        if record is None:
            actual = _ordinary(path)
            result = actual.stat()
            self.session.retain_path_identity(actual, _anchored_identity(result))
            return result
        observed = self._guard(record)
        if observed is None:
            actual = _ordinary(path)
            result = actual.stat()
            self.session.retain_path_identity(actual, _anchored_identity(result))
            return result
        parent_fd = self._chain(record, observed=observed)
        # Named absolute ending retains the legacy current-name observation;
        # the relative leaf separately proves its attached parent-FD binding.
        current = path.stat()
        relative = os.stat(path.name, dir_fd=parent_fd, follow_symlinks=False)
        if _anchored_identity(current) != _anchored_identity(relative):
            raise ValueError('anchored operational leaf correspondence changed')
        self.session.retain_path_identity(path, _anchored_identity(current))
        return current

    def readonly_close(self):
        failures = []
        # Worker.close has already set context.active=False. Still check the
        # local source/process/roster boundary before any PreparedDelivery write.
        try:
            if (_anchored_bindings is not _ANCHORED_CANONICAL_READER
                    or self.cleanup is not _ANCHORED_CANONICAL_CLEANUP
                    or self.bindings != _ANCHORED_CANONICAL_BINDINGS
                    or _anchored_bindings() != _ANCHORED_CANONICAL_BINDINGS
                    or os.getpid() != self.pid or _thread.get_ident() != self.thread):
                failures.append(ValueError('anchored operational owner changed before close'))
            if getattr(self, 'frozen', False) and (
                    tuple(self.directories.items()) != self.frozen_directories
                    or tuple(self.records.items()) != self.frozen_records
                    or tuple(self.acquired) != self.frozen_acquired):
                failures.append(ValueError('anchored operational roster changed before close'))
            for path, (fd, expected) in self.directories.items():
                try:
                    if (_anchored_identity(os.fstat(fd))[:3] != expected
                            or _anchored_identity(os.lstat(path))[:3] != expected):
                        failures.append(ValueError('anchored operational descriptor changed before close'))
                except BaseException as exc:
                    failures.append(exc)
        except BaseException as exc:
            failures.append(exc)
        finally:
            self.active = False
            self.closed = True
            if getattr(self, 'frozen', False):
                # A late roster deletion must not delete the cleanup obligation.
                self.acquired = list(dict.fromkeys((*self.frozen_acquired, *self.acquired)))
            closer = _ANCHORED_CANONICAL_BINDINGS[0]
            # Refusal cannot dispatch a replaced cleanup implementation. Use the
            # original captured core callable even when the live owner changed.
            failures.extend(_ANCHORED_CANONICAL_CLEANUP(self, closer))
            self.pending = None
            if self.context is not None and self.context.session is not self.session:
                try:
                    self.session.close()
                except BaseException as exc:
                    failures.append(exc)
            self.tracked_values.clear()
        if failures:
            failure = failures[0]
            for other in failures[1:]:
                failure.add_note('anchored descriptor cleanup failure: ' + str(other))
            raise failure


def _anchored_identity(value):
    return (value.st_dev, value.st_ino, value.st_mode, value.st_size,
            value.st_mtime_ns, value.st_ctime_ns)


def _anchored_bindings():
    from .readonly_preparation import WorkerReadOnlyObservation
    from .validation_io import ValidationSession
    return (os.close, os.open, os.stat, os.lstat, os.fstat, os.fdopen,
            os.getpid, _thread.get_ident, Path.stat, Path.lstat, Path.is_file,
            Path.is_symlink, Path.resolve, hashlib.sha256, ce.keys, ce.sha, custody_limits,
            WorkerReadOnlyObservation.__init__,
            WorkerReadOnlyObservation.require_active, WorkerReadOnlyObservation.resource,
            WorkerReadOnlyObservation.finish, WorkerReadOnlyObservation.close,
            ValidationSession.close, ValidationSession.retain_path_identity, ValidationSession.readonly_freeze,
            ValidationSession.readonly_drain, ValidationSession.readonly_terminal,
            _anchored_bindings, _anchored_owner, _anchored_keywords,
            _ordinary, _artifact_path, _dependency, _operational_json,
            _anchored_identity, _AnchoredDependencyObservation, _AnchoredDirectoryCore,
            _AnchoredDirectoryCore.MAX_DIRECTORY_FDS, _AnchoredDirectoryCore.MAX_PATH_RECORDS,
            _AnchoredDirectoryCore.__init__, _AnchoredDirectoryCore._directory,
            _AnchoredDirectoryCore._chain, _AnchoredDirectoryCore.close_all,
            *tuple(getattr(_AnchoredDependencyObservation, name, None) for name in
                   ('__init__', '__enter__', 'bind', 'track', 'readonly_check', 'readonly_sessions', 'readonly_freeze',
                    '_directory', '_chain', '_guard', 'path', 'open', 'ending', 'readonly_close')),
            getattr(_AnchoredDependencyObservation, 'MAX_DIRECTORY_FDS', None),
            getattr(_AnchoredDependencyObservation, 'MAX_PATH_RECORDS', None))


def _anchored_owner(context):
    # Injections before selection retain their full original public seam.
    if (_anchored_bindings is not _ANCHORED_CANONICAL_READER
            or _anchored_bindings() != _ANCHORED_CANONICAL_BINDINGS):
        return None
    return context.resource(_AnchoredDependencyObservation).bind(context)


def _anchored_keywords(owner):
    if owner is None:
        return {}
    if type(owner) is not _AnchoredDependencyObservation:
        raise ValueError('exact anchored operational observation required')
    owner.readonly_check()
    return {'_observation': owner}


_ANCHORED_CANONICAL_CLEANUP = _AnchoredDirectoryCore.close_all
_ANCHORED_CANONICAL_READER = _anchored_bindings
_ANCHORED_CANONICAL_BINDINGS = _anchored_bindings()
