"""Source-only authored controls. Root runs them; source assertions are not truth.

The HTTPS transport is entirely scripted in-process. The two-page PDF is an
own deterministic fixture for root's actual required PDFium extraction; no
provider, remote acquisition, compiler or scientific worker is used here.
"""
from copy import deepcopy
import hashlib
import json
from pathlib import Path

import pytest

from ravel.workflow import agent_graph, agent_host, literature_context as lc
from ravel.workflow import physics_knowledge as pk, research_cycle as cycle
from ravel.workflow import research_tools as tools, research_coordinator_decisions as decisions
from test_research_cycle import contract, write


def pin(path):
    path = path.resolve()
    raw = path.read_bytes()
    return {"path": str(path), "sha256": hashlib.sha256(raw).hexdigest(), "size": len(raw)}


def document(base, identity, text, format="markdown", task_ids=()):
    path = base / (identity + "." + format)
    path.write_bytes(text.encode() if type(text) is str else text)
    return {"id": identity, "pin": pin(path), "citation": "https://papers.example.org/" + identity,
        "version": "Own source fixture; not published physics", "license": "Own test fixture",
        "access": "Supplied exact local source", "format": format, "status": "supplied",
        "reason": None, "parents": [], "extraction": None, "acquisition": None,
        "tags": ["fixture"], "domain": ["source-control"], "conventions": ["Explicit toy convention"],
        "task_ids": list(task_ids)}


def task(identity="missing-citation"):
    return {"obligation_id": identity, "query": "Find the original supported convention.",
        "source_scope": "Public original source only", "claim_ids": ["claim-one"],
        "failure_or_missing": "Citation is unresolved; not permission to invent evidence."}


def request(base, documents, *, tasks=(), root=None):
    scope = None
    if root:
        _, state = cycle._load(root)
        scope = {"root": str(root), "contract_sha256": cycle.ce.digest(state["contract"])}
    return write(base / "literature-request.json", {"schema_version": 1,
        "kind": "literature-context-request", "id": "located-fixture", "cycle_binding": scope,
        "documents": documents, "query": {"text": "fixture source", "tags": ["fixture"],
        "roots": [], "domain": [], "max_nodes": 512}, "annotations": [],
        "hypotheses": [], "edges": [], "acquisition_tasks": list(tasks)})


@pytest.fixture(autouse=True)
def refuse_real_network(monkeypatch):
    def refuse(*args, **kwargs):
        raise AssertionError("A root software control cannot make an external acquisition")
    monkeypatch.setattr(lc.http.client, "HTTPSConnection", refuse)
    monkeypatch.setattr(lc.socket, "getaddrinfo", refuse)


@pytest.mark.parametrize("format,text", [
    ("markdown", "# Method\nA located μ convention.\n\n## Results\n| x | y |\n| 1 | 2 |\n\nFigure 1 retained caption.\n"),
    ("html", "<article><h1>Method</h1><p>A located μ convention.</p><figure><img src='missing.png'><figcaption>Retained caption.</figcaption></figure><table><caption>Table caption.</caption><tr><td>2</td></tr></table><math>x=2</math></article>"),
    ("tex", "\\section{Method}\nA located μ convention.\n\\begin{equation}\nx=2\n\\end{equation}\n\\begin{figure}\n\\caption{Retained caption}\n\\end{figure}\n"),
    ("text", "A located μ convention.\n\nEvery original line survives.\n"),
])
def test_l01_complete_located_forest_and_original_bytes(tmp_path, format, text):
    base = tmp_path.resolve()
    doc = document(base, "paper", text, format)
    req = request(base, [doc])
    result = lc.prepare(req, base / "located", base_dir=base)
    assert lc.consume(result["product"], base_dir=base) == result
    context = result["context"]
    assert context["documents"] == [doc] and not any(context["claims"].values())
    for unit in context["units"]:
        fragment = text[unit["start"]:unit["end"]]
        assert unit["text"] == fragment
        assert text.encode()[unit["byte_start"]:unit["byte_end"]] == fragment.encode()
        assert unit["excerpt_sha256"] == hashlib.sha256(fragment.encode()).hexdigest()
    parents = {unit["parent"] for unit in context["units"]}
    leaves = sorted((u["start"], u["end"]) for u in context["units"] if u["id"] not in parents)
    assert "".join(text[first:last] for first,last in leaves) == text
    assert {p["path"] for p in context["input_pins"]} >= {req["path"], doc["pin"]["path"]}
    knowledge_request = json.loads(Path(result["knowledge_request"]["path"]).read_text())
    packet = pk.retrieve(knowledge_request, base)
    assert not any(packet["claims"].values()) and packet["selection"]["dependency_complete"]


def test_l02_initial_known_and_missing_sources_keep_whole_scout_population(tmp_path):
    base = tmp_path.resolve()
    known = document(base, "known", "The source makes a claim.\n", "text", ["known-task"])
    missing = deepcopy(known)
    missing.update(id="missing", pin=None, status="missing", reason="Original source has not been acquired.", task_ids=["missing-task"])
    tasks = [task("known-task"), task("missing-task"), task("unlinked-task")]
    result = lc.prepare(request(base, [known, missing], tasks=tasks), base / "out", base_dir=base)
    context = result["context"]
    assert context["acquisition_tasks"] == tasks
    assert context["documents"][1] == missing
    assert any(row.get("task", {}).get("obligation_id") == "unlinked-task" for row in context["missing_and_unresolved"])
    assert any(row.get("document") == "missing" for row in context["missing_and_unresolved"])
    assert result["knowledge_request"] is not None
    assert context["extraction_status"] == "partial_or_unresolved"
    assert not any(context["claims"].values())


def test_l02_zero_sources_produces_honest_missing_context_without_dummy_fact(tmp_path):
    base = tmp_path.resolve()
    result = lc.prepare(request(base, [], tasks=[task()]), base / "out", base_dir=base)
    assert result["knowledge_request"] is None
    assert result["context"]["source_assertions"] == []
    assert result["context"]["missing_and_unresolved"][0]["task"] == task()
    assert lc.consume(result["product"], base_dir=base) == result


def test_l03_source_assertion_and_generated_hypothesis_remain_distinct(tmp_path):
    base = tmp_path.resolve()
    req = request(base, [document(base, "claim", "An unverified source says the mass is infinite.\n", "text")])
    value = json.loads(Path(req["path"]).read_text())
    value["hypotheses"] = [{"id": "generated-idea", "statement": "An unsupported generated summary predicts a 10% gain over an unmeasured baseline.",
        "tags": ["fixture"], "domain": ["source-control"], "conventions": [],
        "applicability": "Generated hypothesis, not a measured prediction.", "equations": [], "obligations": []}]
    result = lc.prepare(write(base / "hypothesis-request.json", value), base / "out", base_dir=base)
    assert "mass is infinite" in result["context"]["source_assertions"][0]["statement"]
    assert result["context"]["hypotheses"][0]["kind"] == "hypothesis"
    assert result["context"]["hypotheses"][0]["evidence"] == []
    assert all("10%" not in row["statement"] for row in result["context"]["source_assertions"])
    assert not any(result["context"]["claims"].values())


def test_l04_exact_conflict_and_dependency_closure_not_selected_source_only(tmp_path):
    base = tmp_path.resolve()
    req = request(base, [document(base, "first", "Convention first.\n", "text"),
                         document(base, "second", "Convention second conflicts.\n", "text"),
                         document(base, "unselected", "A separate source still belongs to the whole census.\n", "text")])
    value = json.loads(Path(req["path"]).read_text())
    value["hypotheses"] = [{"id":"idea","statement":"Try a comparison.","tags":[],"domain":[],
        "conventions":[],"applicability":"Speculative only.","equations":[],"obligations":[]}]
    value["edges"] = [
        {"id":"require","kind":"requires","source":"idea","target":"first.u0.n0",
         "statement":"The idea depends on the source convention.","assessment":"exploratory"},
        {"id":"conflict","kind":"contradicts","source":"first.u0.n0","target":"second.u0.n0",
         "statement":"Keep the conflicting original source.","assessment":"located_source_conflict"}]
    value["query"].update(tags=[], text="absent", roots=["idea"], max_nodes=3)
    result = lc.prepare(write(base / "closure-request.json", value), base / "out", base_dir=base)
    packet = pk.retrieve(json.loads(Path(result["knowledge_request"]["path"]).read_text()), base)
    assert set(packet["selection"]["selected_ids"]) == {"idea","first.u0.n0","second.u0.n0"}
    assert packet["contradictions"][0]["id"] == "conflict"
    assert packet["selection"]["dependency_complete"]
    assert packet["selection"]["omitted"] == [{"id":"unselected.u0.n0","reason":"not_task_selected"}]
    assert {Path(p["path"]).name for p in pk.input_pins(json.loads(Path(result["knowledge_request"]["path"]).read_text()),base)} >= {"first.text","second.text","unselected.text"}


@pytest.mark.parametrize("max_nodes",[1,2])
def test_original_l03_l04_two_versions_keep_incompatible_units_and_full_conflict(tmp_path,max_nodes):
    base=tmp_path.resolve()
    first=document(base,'first','This version defines Y=Q-T3.\n','text')
    second=document(base,'second','This version defines Y=2*(Q-T3).\n','text')
    first.update(version='Exact own version1',conventions=['Y=Q-T3'])
    second.update(version='Exact own version2',conventions=['Y=2*(Q-T3)'])
    req=request(base,[first,second]);value=json.loads(Path(req['path']).read_text())
    value['query'].update(tags=[],text='no match',roots=['first.u0.n0'],max_nodes=max_nodes)
    value['edges']=[{'id':'normalization-conflict','kind':'contradicts','source':'first.u0.n0',
        'target':'second.u0.n0','statement':'Different supplied normalization definitions are unresolved.',
        'assessment':'located_source_conflict'}]
    req=write(base/'normalization-request.json',value)
    if max_nodes==1:
        with pytest.raises(ValueError,match='cannot discard'):
            lc.prepare(req,base/'out',base_dir=base)
    else:
        result=lc.prepare(req,base/'out',base_dir=base)
        packet=pk.retrieve(json.loads(Path(result['knowledge_request']['path']).read_text()),base)
        assert result['context']['documents']==[first,second]
        assert {tuple(n['conventions']) for n in packet['nodes']}=={('Y=Q-T3',),('Y=2*(Q-T3)',)}
        assert set(packet['selection']['selected_ids'])=={'first.u0.n0','second.u0.n0'}
        assert packet['contradictions'][0]['id']=='normalization-conflict'
        assert not any(packet['claims'].values())


@pytest.mark.parametrize("fault", ["unknown-parent","parent-cycle","unknown-task","duplicate-task",
                                  "source-alias","unknown-root","invented-equation","generated-as-fact"])
def test_source_request_refusals_preserve_generic_knowledge_guards(tmp_path, fault):
    base=tmp_path.resolve()
    doc=document(base,"paper","Located x=2.\n","text")
    req=request(base,[doc],tasks=[task()])
    value=json.loads(Path(req["path"]).read_text())
    if fault=="unknown-parent":value["documents"][0]["parents"]=["absent"]
    elif fault=="parent-cycle":value["documents"][0]["parents"]=["paper"]
    elif fault=="unknown-task":value["documents"][0]["task_ids"]=["absent"]
    elif fault=="duplicate-task":value["acquisition_tasks"]*=2
    elif fault=="source-alias":
        alias=deepcopy(doc);alias["id"]="alias";value["documents"].append(alias)
    elif fault=="unknown-root":value["query"]["roots"]=["absent"]
    else:
        annotation={"id":"paper.u0.n0","kind":"fact","tags":[],"domain":[],"conventions":[],
            "applicability":"Caller annotation.","equations":[],"obligations":[]}
        if fault=="invented-equation":annotation["equations"]=[{"expression":"invented=99","bindings":{}}]
        else:annotation["kind"]="hypothesis"
        value["annotations"]=[annotation]
    with pytest.raises(ValueError):
        lc.prepare(write(base/"invalid.json",value),base/"out",base_dir=base)


@pytest.mark.parametrize("fault",["source","derived","foreign-member","replacement","symlink"])
def test_l05_full_current_source_and_generated_membership_refusal(tmp_path,fault):
    base=tmp_path.resolve()
    doc=document(base,"paper","Original located evidence.\n","text")
    result=lc.prepare(request(base,[doc]),base/"out",base_dir=base)
    original=Path(doc["pin"]["path"])
    if fault=="source":original.write_text("Altered original evidence.\n")
    elif fault=="derived":(base/"out/paper.txt").write_text("Foreign derived evidence.\n")
    elif fault=="foreign-member":(base/"out/foreign.txt").write_text("Not part of the committed population.\n")
    elif fault=="replacement":
        copy=base/"copy.text";copy.write_bytes(b"Replacement source bytes.\n");copy.replace(original)
    else:
        original.rename(base/"real.text");original.symlink_to(base/"real.text")
    with pytest.raises(ValueError):
        lc.consume(result["product"],base_dir=base)


def test_l05_generated_known_bytes_are_bound_before_first_read(tmp_path,monkeypatch):
    base=tmp_path.resolve()
    req=request(base,[document(base,"paper","Exact source assertion.\n","text")])
    actual=lc._emit
    def mutate(path,raw,reader):
        retained=actual(path,raw,reader)
        if path.name=="paper.txt":path.write_text("Different generated assertion.\n")
        return retained
    monkeypatch.setattr(lc,"_emit",mutate)
    with pytest.raises(ValueError):
        lc.prepare(req,base/"out",base_dir=base)


def test_l05_byte_identical_source_replacement_during_preparation_refuses(tmp_path,monkeypatch):
    base=tmp_path.resolve();doc=document(base,"paper","Exact source assertion.\n","text")
    req=request(base,[doc]);original=Path(doc['pin']['path']);actual=lc._emit;replaced=False
    def replace(path,raw,reader):
        nonlocal replaced
        retained=actual(path,raw,reader)
        if not replaced:
            replacement=base/'replacement.text';replacement.write_bytes(original.read_bytes());replacement.replace(original)
            replaced=True
        return retained
    monkeypatch.setattr(lc,'_emit',replace)
    with pytest.raises(ValueError):lc.prepare(req,base/'out',base_dir=base)


def test_l05_rebound_derived_index_cannot_override_original_manifest(tmp_path):
    base=tmp_path.resolve()
    result=lc.prepare(request(base,[document(base,'paper','Actual source statement.\n','text')]),base/'out',base_dir=base)
    knowledge_request=json.loads(Path(result['knowledge_request']['path']).read_text())
    path=Path(knowledge_request['knowledge']['path']);index=json.loads(path.read_text())
    index['nodes'][0]['statement']='A different invented conclusion with the old evidence pin.'
    knowledge_request['knowledge']=write(path,index)
    with pytest.raises(ValueError):pk.retrieve(knowledge_request,base)


def test_l01_unsupported_structure_is_retained_with_exact_failure_locations(tmp_path):
    base=tmp_path.resolve();source="<section><p>Original incomplete markup.<table>Unclosed table."
    result=lc.prepare(request(base,[document(base,'paper',source,'html')]),base/'out',base_dir=base)
    assert result['context']['units'][0]['text']==source
    assert any(row['kind']=='parse' and row['reason']=='unclosed structural HTML element'
               for row in result['context']['missing_and_unresolved'])
    assert any(row['kind']=='table' and row['status']=='unresolved'
               for row in result['context']['missing_and_unresolved'])
    assert not any(result['context']['claims'].values())


def test_l06_large_original_pdf_is_custody_not_extracted_or_presented(tmp_path):
    base=tmp_path.resolve()
    doc=document(base,"large",b"%PDF-1.4\n"+b"0"*(3*1024*1024),"pdf")
    known=document(base,'known','Known source convention.\n','text')
    result=lc.prepare(request(base,[doc,known]),base/"out",base_dir=base)
    assert result["knowledge_request"] is not None
    assert result["context"]["documents"][0]["pin"]==doc["pin"]
    assert any(row["kind"]=="extraction" and row["status"]=="missing" for row in result["context"]["missing_and_unresolved"])
    assert not any(result["context"]["claims"].values())
    assert lc.consume(result["product"],base_dir=base)==result
    assert doc['pin'] in pk.input_pins(json.loads(Path(result['knowledge_request']['path']).read_text()),base)
    # The generic kernel still rejects this same oversized original as inline text.
    with pytest.raises(ValueError):
        pk._snapshot(doc["pin"],base)


def test_l06_campaign_literature_binding_retains_complete_original_goal(tmp_path):
    base=tmp_path.resolve();root=base/"campaign"
    initial=contract(base);cycle.create(root,initial,base_dir=base, evaluation_harness=True)
    doc=document(base,"paper","This source convention is a premise, not a review vote.\n","text")
    req=request(base,[doc],root=root)
    result=tools.prepare_literature_context(root,req,root/"located",
        premise_map={"paper.u0.n0":"located-premise"},reason="Bind the complete source assertion.")
    _,state=cycle._load(root)
    assert state["contract"]["question"]==initial["question"]
    assert state["knowledge_bindings"][-1]["source_assertions_only"] is True
    assert state["knowledge_bindings"][-1]["scientific_acceptance"] is False
    assert state["knowledge_bindings"][-1]["premise_map"]=={"paper.u0.n0":"located-premise"}
    assert result["context"]["assignment"]["budget"]==state["contract"]["budget"]
    assert not state["experiments"] and not any(result["context"]["claims"].values())


def scripted_transport(monkeypatch, body, status=200, headers=None, failure=None, address="93.184.216.34"):
    calls=[]
    class Sock:
        def getpeername(self):return (address,443)
        def settimeout(self,seconds):assert seconds>0
    class Response:
        def __init__(self):self.offset=0;self.status=status
        def getheader(self,key):return (headers or {}).get(key)
        def read(self,n):
            if failure:raise failure
            part=body[self.offset:self.offset+n];self.offset+=len(part);return part
    class Connection:
        def __init__(self,host,port,timeout,context):
            calls.append({"host":host,"port":port,"timeout":timeout});self.sock=Sock()
        def connect(self):pass
        def request(self,method,target,headers):
            calls[-1].update(method=method,target=target,headers=headers)
        def getresponse(self):
            self.sock=None  # genuine HTTPConnection close-response shape
            return Response()
        def close(self):pass
    monkeypatch.setattr(lc.http.client,"HTTPSConnection",Connection)
    monkeypatch.setattr(lc.socket,"getaddrinfo",
        lambda *a,**k:[(2,1,6,"",(address,443))])
    return calls


def acquisition_request(base, *, format="text", tasks=None, max_bytes=200000, expected=None):
    return write(base/"acquisition-request.json",{"schema_version":1,"kind":"literature-acquisition",
        "url":"https://papers.example.org/original?version=1","format":format,"expected_sha256":expected,
        "max_bytes":max_bytes,"max_seconds":20,"tasks":[task()] if tasks is None else tasks})


def acquired_document(binding,result,format="text"):
    doc={"id":"acquired","pin":result["source_artifact"],"citation":"https://papers.example.org/original?version=1",
         "version":"Actual scripted response fixture; no real source acquisition",
         "license":"Unknown source license, not invented","access":"Public configured source",
         "format":format,"status":"supplied" if result["status"]=="acquired" else "failed",
         "reason":None if result["status"]=="acquired" else "Actual retained request failed.",
         "parents":[],"extraction":None,"acquisition":binding,"tags":["fixture"],"domain":[],
         "conventions":[],"task_ids":["missing-citation"]}
    return doc


def test_actual_ordinary_acquisition_full_data_and_context_caller(tmp_path,monkeypatch):
    base=tmp_path.resolve();root=base/"campaign";cycle.create(root,contract(base),base_dir=base, evaluation_harness=True)
    body=("Original μ convention.\n"*4000).encode()
    calls=scripted_transport(monkeypatch,body)
    req=acquisition_request(base,expected=hashlib.sha256(body).hexdigest())
    host=agent_host.AgentHost(timeout_seconds=30,literature_origins=["https://papers.example.org"])
    result=tools.acquire_literature(root,req,root/"acquisition",host,max_wall_seconds=30)
    actual=lc.consume_acquisition(result["binding"],base_dir=base)
    assert Path(actual["source_artifact"]["path"]).read_bytes()==body
    assert actual["request_value"]["tasks"]==[task()] and actual["source_artifact"]["size"]==len(body)
    assert calls[0]["method"]=="GET" and calls[0]["target"]=="/original?version=1"
    assert set(calls[0]["headers"])=={"User-Agent","Accept","Accept-Encoding"}
    context=tools.prepare_literature_context(root,
        request(base,[acquired_document(result["binding"],result)],tasks=[task()],root=root),
        root/"located",reason="Retain source response and full scout task.")
    assert context["context"]["acquisition_tasks"]==[task()]
    assert context["context"]["documents"][0]["acquisition_outcome"]==actual
    assert not any(context["context"]["claims"].values())
    _,state=cycle._load(root)
    assert state["graphs"][0]["usage"]["calls"]==1


@pytest.mark.parametrize("fault",["redirect","http-error","truncated","wrong-hash","private-peer","timeout","encoded"])
def test_actual_acquisition_failure_is_retained_without_source_success(tmp_path,monkeypatch,fault):
    base=tmp_path.resolve();root=base/"campaign";cycle.create(root,contract(base),base_dir=base, evaluation_harness=True)
    body=b"Retained response bytes.\n";options={};maximum=1000;expected=None
    if fault=="redirect":options={"status":302,"headers":{"Location":"https://foreign.example.org/"}}
    elif fault=="http-error":options={"status":404}
    elif fault=="truncated":maximum=5
    elif fault=="wrong-hash":expected="f"*64
    elif fault=="private-peer":options={"address":"127.0.0.1"}
    elif fault=="timeout":options={"failure":TimeoutError("Scripted read timeout")}
    else:options={"headers":{"Content-Encoding":"gzip"}}
    calls=scripted_transport(monkeypatch,body,**options)
    result=tools.acquire_literature(root,acquisition_request(base,max_bytes=maximum,expected=expected),
        root/"acquisition",agent_host.AgentHost(timeout_seconds=30,literature_origins=["https://papers.example.org"]),
        max_wall_seconds=30)
    actual=lc.consume_acquisition(result["binding"],base_dir=base)
    assert result["status"]=="failed" and result["source_artifact"] is None and actual["failure"]
    assert not any(actual["claims"].values()) and len(calls)<=1
    context=tools.prepare_literature_context(root,
        request(base,[acquired_document(result["binding"],result)],tasks=[task()],root=root),
        root/"located",reason="Keep actual failed acquisition.")
    assert context["knowledge_request"] is None and context["context"]["documents"][0]["status"]=="failed"
    assert context["context"]["acquisition_tasks"]==[task()]


@pytest.mark.parametrize("fault",["unconfigured","local-only","credentials","http","loopback"])
def test_acquisition_policy_refusal_before_dispatch(tmp_path,fault):
    base=tmp_path.resolve();req=acquisition_request(base);value=json.loads(Path(req["path"]).read_text())
    allowed=["https://papers.example.org"];privacy="configured"
    if fault=="unconfigured":allowed=[]
    elif fault=="local-only":privacy="local_only"
    elif fault=="credentials":value["url"]="https://user:secret@papers.example.org/"
    elif fault=="http":value["url"]="http://papers.example.org/"
    else:value["url"]="https://127.0.0.1/"
    req=write(base/"policy-request.json",value)
    with pytest.raises(ValueError):
        lc.acquire(req,base/"out",base_dir=base,configured_origins=allowed,privacy=privacy)


def two_page_pdf():
    text=b"BT /F1 12 Tf 20 150 Td (Located mass convention.) Tj ET\n"
    image_only=b"0 0 0 rg 20 20 50 50 re f\n"
    objects=[b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R 4 0 R] /Count 2 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 200 200] /Resources << /Font << /F1 7 0 R >> >> /Contents 5 0 R >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 200 200] /Resources << >> /Contents 6 0 R >>",
        b"<< /Length "+str(len(text)).encode()+b" >>\nstream\n"+text+b"endstream",
        b"<< /Length "+str(len(image_only)).encode()+b" >>\nstream\n"+image_only+b"endstream",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>"]
    raw=b"%PDF-1.4\n";offsets=[]
    for i,obj in enumerate(objects,1):
        offsets.append(len(raw));raw+=str(i).encode()+b" 0 obj\n"+obj+b"\nendobj\n"
    xref=len(raw);raw+=b"xref\n0 8\n0000000000 65535 f \n"
    raw+=b"".join(("%010d 00000 n \n"%n).encode() for n in offsets)
    return raw+b"trailer\n<< /Size 8 /Root 1 0 R >>\nstartxref\n"+str(xref).encode()+b"\n%%EOF\n"


def test_actual_pdf_tool_full_pages_empty_text_and_knowledge_source(tmp_path):
    base=tmp_path.resolve();root=base/"campaign";cycle.create(root,contract(base),base_dir=base, evaluation_harness=True)
    doc=document(base,"paper",two_page_pdf(),"pdf")
    req=write(base/"pdf-request.json",{"schema_version":1,"kind":"literature-pdf-extraction",
        "source":doc["pin"],"max_pages":2,"max_text_bytes":20000,"max_seconds":20})
    result=tools.extract_literature_pdf(root,req,root/"extraction",agent_host.AgentHost(timeout_seconds=30),max_wall_seconds=30)
    actual=lc.consume_pdf(result["binding"],base_dir=base)
    assert actual["page_count"]==2 and [p["page_index"] for p in actual["pages"]]==[0,1]
    assert "Located mass convention." in actual["pages"][0]["text"]
    assert actual["pages"][1]["status"]=="empty_text" and actual["pages"][1]["text"]==""
    assert all(p["visual_status"]=="unobserved" and p["ocr_status"]=="not_performed" for p in actual["pages"])
    doc["extraction"]=result["binding"]
    context=tools.prepare_literature_context(root,request(base,[doc],root=root),root/"located",
        reason="Retain every original PDF page and native text unknown.")
    assert {u["page_index"] for u in context["context"]["units"] if u["kind"]=="page"}=={0,1}
    assert len([row for row in context["context"]["missing_and_unresolved"] if row["kind"]=="visual"])==2
    assert any(row["kind"]=="text" and row["page_index"]==1 for row in context["context"]["missing_and_unresolved"])
    assert doc["pin"] in pk.input_pins(json.loads(Path(context["knowledge_request"]["path"]).read_text()),base)
    assert not any(context["context"]["claims"].values())


def test_forged_pdf_page_roster_is_not_an_ordinary_extraction(tmp_path):
    base=tmp_path.resolve()
    doc=document(base,"paper",two_page_pdf(),"pdf")
    doc["extraction"]=write(base/"forged.json",{"schema_version":1,"kind":"literature-pdf-extraction-result","pages":[]})
    with pytest.raises(ValueError):
        lc.prepare(request(base,[doc]),base/"out",base_dir=base)


def test_actual_pdf_whole_page_budget_failure_preserves_original_not_subset(tmp_path):
    base=tmp_path.resolve();root=base/'campaign';cycle.create(root,contract(base),base_dir=base, evaluation_harness=True)
    doc=document(base,'paper',two_page_pdf(),'pdf')
    req=write(base/'pdf-request.json',{'schema_version':1,'kind':'literature-pdf-extraction',
        'source':doc['pin'],'max_pages':1,'max_text_bytes':20000,'max_seconds':20})
    result=tools.extract_literature_pdf(root,req,root/'extraction',agent_host.AgentHost(timeout_seconds=30),max_wall_seconds=30)
    actual=lc.consume_pdf(result['binding'],base_dir=base)
    assert actual['status']=='failed' and actual['page_count']==2 and actual['pages']==[]
    doc['extraction']=result['binding']
    context=tools.prepare_literature_context(root,request(base,[doc],root=root),root/'located',
        reason='Retain the entire rejected PDF page population.')
    assert context['knowledge_request'] is None
    assert context['context']['documents'][0]['pin']==doc['pin']
    assert context['context']['missing_and_unresolved'][0]['reported_page_count']==2
    assert not any(context['context']['claims'].values())


def test_actual_host_refuses_missing_acquisition_helper_input(tmp_path,monkeypatch):
    base=tmp_path.resolve();root=base/"campaign";cycle.create(root,contract(base),base_dir=base, evaluation_harness=True)
    req=acquisition_request(base);calls=scripted_transport(monkeypatch,b"Original evidence.\n")
    spec=tools._tool_spec("missing-helper","literature-acquire",
        [{"id":"request","path":req["path"],"sha256":req["sha256"]}],
        {"request_input":"request","output_dir":str(root/"output")},30,node_id="acquire")
    spec["nodes"][0]["role"]="executor"
    result=cycle.execute_graph(root,root/"graph",spec,
        agent_host.AgentHost(timeout_seconds=30,literature_origins=["https://papers.example.org"]))
    assert not result["complete"] and not calls and not (root/"output").exists()


def test_source_substitution_after_actual_acquisition_does_not_rebind_origin(tmp_path,monkeypatch):
    base=tmp_path.resolve();root=base/"campaign";cycle.create(root,contract(base),base_dir=base, evaluation_harness=True)
    scripted_transport(monkeypatch,b"Original convention.\n")
    result=tools.acquire_literature(root,acquisition_request(base),root/"acquisition",
        agent_host.AgentHost(timeout_seconds=30,literature_origins=["https://papers.example.org"]),max_wall_seconds=30)
    Path(result["source_artifact"]["path"]).write_bytes(b"Foreign convention.\n")
    with pytest.raises(ValueError):
        lc.consume_acquisition(result["binding"],base_dir=base)


def test_coordinator_catalogue_uses_actual_finite_literature_services():
    for action,function in [("literature-context","prepare_literature_context"),
                            ("literature-pdf","extract_literature_pdf"),("literature-acquire","acquire_literature")]:
        assert decisions.EXTENSIONS[action]==("ravel.workflow.research_tools",function)
        assert function in tools.__dict__ and action in decisions.EXTENSION_TRANSPORT
    assert pk.MAX_DOCUMENT_BYTES==2*1024*1024 and pk.MAX_NODES==512


@pytest.mark.parametrize("fault",[None,"unrelated-data","model-kind","non-executor","stale-source"])
def test_large_pdf_operational_pin_is_exact_named_custody_not_generic_cap_bypass(tmp_path,fault):
    base=tmp_path.resolve()
    doc=document(base,"large",b"%PDF-1.4\n"+b"0"*(3*1024*1024),"pdf")
    req=write(base/"extract-request.json",{"schema_version":1,"kind":"literature-pdf-extraction",
        "source":doc["pin"],"max_pages":2,"max_text_bytes":20000,"max_seconds":20})
    inputs=[{"id":"request","path":req["path"],"sha256":req["sha256"]},
            {"id":"pdf","path":doc["pin"]["path"],"sha256":doc["pin"]["sha256"]}]
    node={"id":"extract","kind":"tool","role":"executor","action":"literature-pdf-extract",
          "max_attempts":1,"parameters":{"request_input":"request","output_dir":str(base/"out")},"inputs":inputs}
    host=agent_host.AgentHost()
    if fault=="unrelated-data":
        other=document(base,"other",b"%PDF-1.4\n"+b"1"*(3*1024*1024),"pdf")
        inputs.append({"id":"other","path":other["pin"]["path"],"sha256":other["pin"]["sha256"]})
    elif fault=="model-kind":node["kind"]="model"
    elif fault=="non-executor":node["role"]="designer"
    elif fault=="stale-source":Path(doc["pin"]["path"]).write_bytes(b"%PDF-1.4\nChanged original.")
    if fault is None:
        assert host._pins(node,{"input_artifacts":inputs})["pdf"]==(Path(doc["pin"]["path"]),doc["pin"]["sha256"])
        assert host.max_request==2_000_000
    else:
        with pytest.raises(agent_host.HostFailure):
            host._pins(node,{"input_artifacts":inputs})
