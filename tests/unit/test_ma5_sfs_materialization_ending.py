"""Ending source/membership controls; writer and worker authority are synthetic."""
from pathlib import Path
import pytest
from ravel.physics import ma5_sfs_materialization as m, routine_build as rb, reinterpret_db
from ravel.workflow.state_io import read_json
from test_ma5_sfs_materialization import fixture,synthetic_writer,no_ma5_or_native


@pytest.mark.parametrize('asset',m.ASSETS)
def test_every_staged_original_asset_stays_bound_through_writer(tmp_path,monkeypatch,asset):
 task,d,cp=fixture(tmp_path/'inputs');out=tmp_path/'out';out.mkdir()
 def writer(*args):
  result=synthetic_writer(*args);request=read_json(args[0][-1]);p=Path(request['assets'][asset]);p.write_bytes(p.read_bytes()+b'\n# changed copied original\n');return result
 monkeypatch.setattr(reinterpret_db,'execute_native',writer)
 with pytest.raises(ValueError):rb.run(task,cp.parent,out)
 assert not (out/'build-receipt.json').exists()
 assert (out/'writer-execution/native-execution.json').is_file()


@pytest.mark.parametrize('asset',m.ASSETS)
def test_every_staged_asset_stays_bound_through_completion_write(tmp_path,monkeypatch,asset):
 task,d,cp=fixture(tmp_path/'inputs');out=tmp_path/'out';out.mkdir()
 monkeypatch.setattr(reinterpret_db,'execute_native',synthetic_writer);real=m.atomic_json
 def emit(path,value):
  real(path,value)
  if path.name=='build-receipt.json':
   request=read_json(out/'writer-request.json');p=Path(request['assets'][asset]);p.write_bytes(p.read_bytes()+b'\n# late copied-original change\n')
 monkeypatch.setattr(m,'atomic_json',emit)
 with pytest.raises(ValueError):rb.run(task,cp.parent,out)
 assert (out/'build-receipt.json').is_file() # Failed evidence, not successful return.


@pytest.mark.parametrize('member',['late.h','late.sh','late.bin','late-directory'])
def test_ending_job_membership_is_whole_not_suffix_filtered(tmp_path,monkeypatch,member):
 task,d,cp=fixture(tmp_path/'inputs');out=tmp_path/'out';out.mkdir()
 monkeypatch.setattr(reinterpret_db,'execute_native',synthetic_writer);real=m.atomic_json
 def emit(path,value):
  real(path,value)
  if path.name=='build-receipt.json':
   p=out/'job'/member
   if member=='late-directory':p.mkdir()
   else:p.write_bytes(b'late unknown output\n')
 monkeypatch.setattr(m,'atomic_json',emit)
 with pytest.raises(ValueError,match='ending generated job membership'):rb.run(task,cp.parent,out)
 assert (out/'job'/member).exists() and (out/'build-receipt.json').is_file()


def test_current_member_bytes_cannot_change_after_initial_job_inspection(tmp_path,monkeypatch):
 task,d,cp=fixture(tmp_path/'inputs');out=tmp_path/'out';out.mkdir()
 monkeypatch.setattr(reinterpret_db,'execute_native',synthetic_writer);real=m.atomic_json
 def emit(path,value):
  real(path,value)
  if path.name=='build-receipt.json':
   p=out/'job/Build/SampleAnalyzer/User/Analyzer/new_tagger.h';p.write_bytes(p.read_bytes()+b'\n// changed existing source\n')
 monkeypatch.setattr(m,'atomic_json',emit)
 with pytest.raises(ValueError):rb.run(task,cp.parent,out)


def test_whole_membership_and_copied_asset_positive_reuse(tmp_path,monkeypatch):
 task,d,cp=fixture(tmp_path/'inputs');out=tmp_path/'out';out.mkdir();monkeypatch.setattr(reinterpret_db,'execute_native',synthetic_writer)
 receipt=rb.run(task,cp.parent,out);plan=read_json(out/'build-plan.json')
 assert rb.verify_receipt(receipt,plan,cp.parent,out)==receipt
 assert {str(out/'job'/r['relative']) for r in m.job_membership(out/'job') if r['kind']=='file'}=={r['path'] for r in receipt['job_inventory']}


def test_reuse_binds_retained_empty_directories_as_well_as_files(tmp_path,monkeypatch):
 task,d,cp=fixture(tmp_path/'inputs');out=tmp_path/'out';out.mkdir();monkeypatch.setattr(reinterpret_db,'execute_native',synthetic_writer)
 receipt=rb.run(task,cp.parent,out);plan=read_json(out/'build-plan.json');(out/'job/late-empty-directory').mkdir()
 with pytest.raises(ValueError,match='retained generated job membership'):rb.verify_receipt(receipt,plan,cp.parent,out)
