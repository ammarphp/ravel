"""Ending custody on every contributing scientific review, no native execution."""
from pathlib import Path
import pytest
from ravel.workflow import task_completion as tc,science,physics_review as pr
from ravel.workflow.state_io import read_json
from test_task_completion import goal,child,write,request,review_run,report_fixture,review_final_artifacts
from test_scientific_judgment import observed_role_boundary
from test_physics_review import late_finding_context,commit_late_hold

# Final delivery of a whole task needs the CHECK-IN 3 final-artifact review of
# its parent run. The fixture registers it through the ordinary review graph.
pytestmark=pytest.mark.usefixtures('observed_role_boundary')


def accepted_parent(base,monkeypatch):
 _,cp=goal(base);out=child(base,cp,state='satisfied');root=Path(out['rundir'])
 evidence=write(root/'inputs/coverage.json',{'synthetic_scientific_scope_evidence':True})
 for row in out['coverage']:row['evidence']=[evidence]
 out['claim_scope']='reproduction'
 review_run(root,[cp['path'],str(root/science.SPEC),evidence['path']],monkeypatch,scope='reproduction')
 recipe=write(base/'recipe.json',report_fixture(base));rp=request(base,cp,[out],report=recipe)
 ready=tc.evaluate(rp,base_dir=base);parent=base/'whole-parent'
 rp=request(base,cp,[out],report=recipe,parent_review={'rundir':str(parent),'claim_scope':'original_task_completion'})
 review_run(parent,[rp['path'],*[p['path'] for p in ready['input_pins'] if p['path']!=rp['path']]],monkeypatch,scope='original_task_completion')
 with pytest.raises(ValueError,match='CHECK-IN 3 final-artifact review'):tc.require_final(rp,base_dir=base)
 review_final_artifacts(parent,rp,read_json(recipe['path']),base,monkeypatch)
 final=tc.require_final(rp,base_dir=base)
 assert final['parent_task_accepted'] and final['final_results_review']['rundir']==str(parent)
 return rp,Path(out['rundir']),parent,recipe


@pytest.mark.parametrize('where,artifact',[('child','inputs/settings.cfg'),('parent','inputs/settings.cfg'),
 ('child',pr.HEAD),('parent',pr.HEAD),('child','outputs/produced.json'),('parent','outputs/produced.json')])
def test_late_contributing_root_mutation_cannot_pass_final_custody(tmp_path,monkeypatch,where,artifact):
 rp,child,parent,_=accepted_parent(tmp_path,monkeypatch);target=({'child':child,'parent':parent}[where])/artifact
 real=tc._Inputs.finish
 def change_at_return(inputs):
  target.write_bytes(target.read_bytes()+b'changed_before_task_return')
  return real(inputs)
 monkeypatch.setattr(tc._Inputs,'finish',change_at_return)
 with pytest.raises(ValueError):tc.require_final(rp,base_dir=tmp_path)
 assert pr.gate_errors(child if where=='child' else parent,'delivery')


@pytest.mark.parametrize('where',['child','parent'])
def test_actual_late_hold_event_cannot_survive_final_custody(tmp_path,monkeypatch,where):
 rp,child,parent,_=accepted_parent(tmp_path,monkeypatch);root=child if where=='child' else parent
 real=tc._Inputs.finish
 def hold_at_return(inputs):
  context,path=late_finding_context(root)
  context['claim_scope']=pr.status(root)['claim_scope']
  write(path,context)
  commit_late_hold(root,context,path)
  return real(inputs)
 monkeypatch.setattr(tc._Inputs,'finish',hold_at_return)
 with pytest.raises(ValueError):tc.require_final(rp,base_dir=tmp_path)
 assert pr.status(root)['state']=='scientific_hold'


def test_sessions_close_on_success_and_failure_and_never_cross_calls(tmp_path,monkeypatch):
 rp,child,parent,_=accepted_parent(tmp_path,monkeypatch)
 made=[];original=tc._Inputs.review_session
 def inspect(inputs,root):
  session=original(inputs,root)
  if all(session is not known for _,known in made):made.append((Path(root).resolve(),session))
  return session
 monkeypatch.setattr(tc._Inputs,'review_session',inspect)
 # The completion evaluation and the final draft that CHECK-IN 3 gates each observe
 # both review roots once, each in its own session.
 both=sorted([child.resolve(),parent.resolve()]*2)
 assert tc.require_final(rp,base_dir=tmp_path)['parent_task_accepted']
 assert sorted(root for root,_ in made)==both and all(s.closed for _,s in made)
 previous=list(made)
 assert tc.require_final(rp,base_dir=tmp_path)['parent_task_accepted']
 assert len(made)==8 and sorted(root for root,_ in made[4:])==both and all(s.closed for _,s in made)
 assert not any(s is old for _,s in made[4:] for _,old in previous)
 (child/'inputs/settings.cfg').write_text('changed after independent successful calls')
 with pytest.raises(ValueError):tc.require_final(rp,base_dir=tmp_path)
 assert all(s.closed for _,s in made)
