"""Generated-source commitments; fabricated actor returns, no science calls."""
import hashlib,json
from pathlib import Path
import pytest
from ravel.workflow import sfitter_application as a
from test_sfitter_application import fixture,fork_request,cycle_fixture,advice,SuppliedHost,read_json

@pytest.mark.parametrize('moment',['write','pin','after_pin'])
def test_json_initial_bytes_not_late_recapture(tmp_path,monkeypatch,moment):
 p=tmp_path/'receipt.json';changed=[];original=a._pin
 if moment=='write':
  atomic=a.atomic_json
  def mutate(path,value):
   atomic(path,value);Path(path).write_text('{"execution_authorized":true}\n');changed.append(moment)
  monkeypatch.setattr(a,'atomic_json',mutate)
 else:
  def mutate(path):
   observed=original(path)
   Path(path).write_text('{"execution_authorized":true}\n');changed.append(moment)
   return original(path) if moment=='pin' else observed
  monkeypatch.setattr(a,'_pin',mutate)
 with pytest.raises(ValueError):a._write(p,{'execution_authorized':False})
 assert changed


def test_json_normal_write_commits_serialized_intent(tmp_path):
 p=tmp_path/'receipt.json';value={'execution_authorized':False,'text':'Exact ordinary output'}
 result=a._write(p,value)
 expected=(json.dumps(value,indent=2,allow_nan=False)+'\n').encode()
 assert p.read_bytes()==expected
 assert result=={'path':str(p),'sha256':hashlib.sha256(expected).hexdigest()}


def test_cold_copied_member_change_refuses(tmp_path,monkeypatch):
 # fixture calls actual create; exact released source remains unchanged.
 original=Path.write_bytes;changed=[]
 def mutate(path,raw):
  if path==tmp_path/'session/.claude/skills/sf-deep-verify/SKILL.md':
   changed.append(str(path));return original(path,raw+b'\nUNAUTHORIZED\n')
  return original(path,raw)
 monkeypatch.setattr(Path,'write_bytes',mutate)
 with pytest.raises(ValueError):fixture(tmp_path)
 assert changed


def test_later_metadata_write_cannot_change_copied_member(tmp_path,monkeypatch):
 _,_,wp,goal,session=fixture(tmp_path);out=tmp_path/'late';atomic=a.atomic_json;changed=[]
 def mutate(path,value):
  atomic(path,value)
  if Path(path)==out/'ravel-session.json':
   (out/'docs/README.md').write_text('late altered source');changed.append(str(path))
 monkeypatch.setattr(a,'atomic_json',mutate)
 with pytest.raises(ValueError):a.create(fork_request(tmp_path,wp,goal,session),tmp_path,out)
 assert changed


@pytest.mark.parametrize('target',['page','slate','ending_page'])
def test_actual_actor_generated_wiki_bytes_refuse_change(tmp_path,monkeypatch,target):
 wf,_,_,goal,session=fixture(tmp_path);cycle_root=cycle_fixture(tmp_path,goal)
 gp=a.skill_graph(session,tmp_path,tmp_path/'advice-plan',actors=['lead'],skill='sf-deep-verify',graph_id='advice',max_wall_seconds=30)
 host=SuppliedHost(advice('lead',wf));gr=tmp_path/'graph'
 assert a.execute_skill_graph(session,tmp_path,cycle_root,gr,gp,host)['complete']
 context=read_json(tmp_path/'advice-plan/lead.json');source=next(iter(context['sources'].values()))
 citation={'pin':source['pin'],'line':1,'text':source['text'].splitlines()[0]}
 out=tmp_path/'learned';page=out/'agent_wikis/lead/complete-population.md';slate=out/'.claude/lead-memory/MEMORY.md'
 changed=[]
 if target!='ending_page':
  original=Path.write_bytes
  def mutate(path,raw):
   if path==(page if target=='page' else slate) and (target=='page' or b'complete-population' in raw):
    changed.append(str(path));return original(path,raw+b'\nUNAUTHORIZED GENERATED TEXT\n')
   return original(path,raw)
  monkeypatch.setattr(Path,'write_bytes',mutate)
 else:
  atomic=a.atomic_json
  def mutate(path,value):
   atomic(path,value)
   if Path(path)==out/'ravel-session.json' and value.get('notes'):
    page.write_bytes(page.read_bytes()+b'\nLATE GENERATED TEXT\n');changed.append(str(path))
  monkeypatch.setattr(a,'atomic_json',mutate)
 with pytest.raises(ValueError):
  a.add_note(session,tmp_path,out,actor='lead',graph_root=gr,node_id='lead',slug='complete-population',text=host.value['text'],citations=[citation])
 assert changed


def test_later_graph_write_cannot_change_prepared_actor_context(tmp_path,monkeypatch):
 _,_,_,_,session=fixture(tmp_path);out=tmp_path/'plan';atomic=a.atomic_json;changed=[]
 def mutate(path,value):
  atomic(path,value)
  if Path(path)==out/'graph.json':
   data=json.loads((out/'lead.json').read_bytes());data['execution_authorized']=True
   (out/'lead.json').write_text(json.dumps(data,indent=2)+'\n');changed.append(str(path))
 monkeypatch.setattr(a,'atomic_json',mutate)
 with pytest.raises(ValueError):a.skill_graph(session,tmp_path,out,actors=['lead'],skill='sf-deep-verify',graph_id='changed-context',max_wall_seconds=30)
 assert changed
