"""Exact released exclusions-row transport; no statistic computation or SDK."""
from copy import deepcopy
from pathlib import Path
import json,sqlite3
import pytest
from ravel.physics import contur_population as cp,contur_import as ci
from test_contur_population import runnable_fixture,native_database

@pytest.fixture(autouse=True)
def no_external(monkeypatch):
 import subprocess,socket,os
 def refuse(*a,**k):raise AssertionError('pure pool transport only')
 monkeypatch.setattr(subprocess,'Popen',refuse);monkeypatch.setattr(socket,'socket',refuse);monkeypatch.setattr(os,'system',refuse)

def prepared(tmp_path,profile='default3'):
 task,d=runnable_fixture(tmp_path,profile);db=tmp_path/'db';work=tmp_path/'work';obs=native_database(db,d,work)
 return d,db,work,obs

def rows(db,d):return ci.decode_database(db,modes=cp.modes(d))

@pytest.mark.parametrize('profile',cp.PROFILES)
@pytest.mark.parametrize('number',[None,0.0,1.25,-2.5])
def test_literal_pool_numeric_and_parameter_values(tmp_path,profile,number):
 d,db,work,obs=prepared(tmp_path,profile)
 with sqlite3.connect(db) as conn:
  conn.execute('UPDATE exclusions SET nll=?,llr=?,mu_lower_limit=?,mu_upper_limit=?,mu_hat=?',(number,number,number,number,number))
 for w in obs['points'].values():
  for mode in cp.modes(d):
   pool=w['native_sorted_blocks'][mode]['pool'];pool.update(NLL=number,LLR=number)
   # Exact source writer projection, including NULL for missing parameter results.
   w['native_parameter_columns'][mode]={'combined':{},'pools':{'pool':{'mu_lower_limit':number,'mu_upper_limit':number,'mu_hat':number}}}
 assert cp.reconcile(rows(db,d),d,work,obs)

@pytest.mark.parametrize('column,value',[('exclusion',.125),('nll',1.25),('llr',2.5),('histos','different_histogram'),('mu_lower_limit',.2),('mu_upper_limit',.7),('mu_hat',.5)])
def test_complete_source_pool_scalar_correspondence(tmp_path,column,value):
 d,db,work,obs=prepared(tmp_path)
 for w in obs['points'].values():
  for mode in cp.modes(d):w['native_parameter_columns'][mode]={'combined':{},'pools':{'pool':{'mu_lower_limit':None,'mu_upper_limit':None,'mu_hat':None}}}
 with sqlite3.connect(db) as conn:conn.execute('UPDATE exclusions SET '+column+'=? WHERE id=11',(value,))
 with pytest.raises(ValueError):cp.reconcile(rows(db,d),d,work,obs)

@pytest.mark.parametrize('column,value',[('pool_name','foreign'),('stat_type','FOREIGN'),('run_id',99)])
def test_pool_dictionary_mode_and_join_identity(tmp_path,column,value):
 d,db,work,obs=prepared(tmp_path)
 with sqlite3.connect(db) as conn:conn.execute('UPDATE exclusions SET '+column+'=? WHERE id=11',(value,))
 with pytest.raises(ValueError):cp.reconcile(rows(db,d),d,work,obs)

@pytest.mark.parametrize('key,value',[('NLL',True),('LLR',float('inf')),('histos',None),('histos',['h'])])
def test_source_pool_values_are_typed_not_coerced(tmp_path,key,value):
 d,db,work,obs=prepared(tmp_path);obs['points']['0000']['native_sorted_blocks'][cp.modes(d)[0]]['pool'][key]=value
 with pytest.raises(ValueError):cp.reconcile(rows(db,d),d,work,obs)

def test_sqlite_generated_identity_is_not_fabricated_native_statistic(tmp_path):
 d,db,work,obs=prepared(tmp_path)
 with sqlite3.connect(db) as conn:conn.execute('UPDATE exclusions SET id=id+100')
 assert cp.reconcile(rows(db,d),d,work,obs)
