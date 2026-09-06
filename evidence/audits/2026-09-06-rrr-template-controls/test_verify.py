"""Portable public-admission controls. No private originals or inference runtime."""
from pathlib import Path
import copy,gzip,hashlib,json,os,runpy,shutil,subprocess,sys
import pytest
HERE=Path(__file__).resolve().parent
v=runpy.run_path(str(HERE/'verify.py'))
def read(name):return v['decode']((HERE/name).read_bytes())
def refresh(a):
 data={'schema_version':1,'files':{str(p.relative_to(a)):hashlib.sha256(p.read_bytes()).hexdigest()for p in a.rglob('*')if p.is_file()and p!=a/'manifest.json'}};(a/'manifest.json').write_text(json.dumps(data))

def test_public_standalone_no_site_or_source_dependency(tmp_path):
 a=tmp_path/'bundle';shutil.copytree(HERE,a);env=dict(os.environ);env.pop('PYTHONPATH',None);env['PYTHONDONTWRITEBYTECODE']='1'
 x=subprocess.run([sys.executable,'-B','-S',str(a/'verify.py')],cwd=tmp_path,env=env,capture_output=True,text=True)
 assert x.returncode==0,x.stderr;assert json.loads(x.stdout)['root_values']==18

@pytest.mark.parametrize('mutation',['drop_role','role_hash','role_path','extra_role','duplicate','projection','missing','extra','symlink'])
def test_transport_rehash_does_not_authorize_changed_source_or_projection(tmp_path,mutation):
 a=tmp_path/'audit';shutil.copytree(HERE,a);p=a/'sources.json';d=read('sources.json')
 if mutation=='drop_role':d['original_roles'].pop('baseline_result')
 elif mutation=='role_hash':d['original_roles']['baseline_result']['sha256']='0'*64
 elif mutation=='role_path':d['original_roles']['baseline_result']['path']='../escape'
 elif mutation=='extra_role':d['original_roles']['invented']=copy.deepcopy(d['original_roles']['baseline_result'])
 elif mutation=='duplicate':p.write_text('{"schema_version":1,"schema_version":2}')
 elif mutation=='projection':
  q=a/'results.json';x=read('results.json');x['models']['baseline']['mu']['observed']*=2;q.write_text(json.dumps(x))
 elif mutation=='missing':(a/'baseline_patch.json').unlink()
 elif mutation=='extra':(a/'surprise.json').write_text('{}')
 elif mutation=='symlink':
  (a/'precision.json').unlink();(a/'precision.json').symlink_to(HERE/'precision.json')
 if mutation in('drop_role','role_hash','role_path','extra_role'):p.write_text(json.dumps(d))
 if mutation!='extra':refresh(a)
 with pytest.raises((ValueError,FileNotFoundError)):v['verify'](a)

@pytest.mark.parametrize('mutation',['nan','boolean','scope','quantile','order','root','bracket','parameter','checks','portfolio','nesting','descending','ratio','baseline_portfolio','inference'])
def test_numerical_semantics_independent_of_transport(mutation):
 d=read('results.json');m=d['models']['signal_mc_off'];f=m['final_fresh_evaluations']
 if mutation=='nan':m['mu']['observed']=float('nan')
 elif mutation=='boolean':m['mu']['observed']=True
 elif mutation=='scope':d['physics_certified']=True
 elif mutation=='quantile':m['mu'].pop('expected_plus2')
 elif mutation=='order':m['mu']['expected_minus2']=1.
 elif mutation=='root':m['root_checks'][0]['recorded_cls']=.1
 elif mutation=='bracket':m['root_checks'][0]['bracket']=[0.,.01]
 elif mutation=='parameter':m['n_parameters']=207
 elif mutation=='checks':m['recorded_fresh_checks']=True
 elif mutation=='portfolio':f.pop()
 elif mutation=='nesting':f[-1]['profile_consistency']['twice_nll']['free_data']=1e9
 elif mutation=='descending':f[0],f[1]=f[1],f[0]
 elif mutation=='ratio':d['rows'][0]['mc_off_over_baseline']=1.
 elif mutation=='baseline_portfolio':d['models']['baseline']['final_fresh_evaluations']=f
 elif mutation=='inference':m['inference']['coverage_validated']=True
 with pytest.raises((ValueError,KeyError)):v['check_results'](d)

@pytest.mark.parametrize('mutation',['counts','zero','moment','denominator','union','floor'])
def test_original_exposure_and_precision_semantics(mutation):
 p=read('precision.json');z=next(r for r in p['channels']if r['selected_events']==0);r=next(r for r in p['channels']if r['selected_events']>0)
 if mutation=='counts':r['selected_events']=True
 elif mutation=='zero':z['histogram_relative_mc']=0.
 elif mutation=='moment':r['sumw2_pb2']*=2
 elif mutation=='denominator':p['SR_unions'][0]['original_denominator']=59
 elif mutation=='union':p['SR_unions'][0]['selected_events']+=1
 elif mutation=='floor':r['diagnostic_5percent']='within_target'
 with pytest.raises(ValueError):v['check_precision'](p)

@pytest.mark.parametrize('mutation',['central','CR','background_poi','compiled','append','moment_modifier'])
def test_exact_signal_only_modification(mutation):
 bg=v['decode'](gzip.decompress((HERE/'background.json.gz').read_bytes()));ps={a:read(a+'_patch.json')for a in v['ARMS']};change=read('model_changes.json');compiled=read('compiled.json')
 if mutation=='central':ps['signal_mc_off'][0]['value']['data'][0]+=.1
 elif mutation=='CR':ps['signal_mc_and_CR_off'].append(ps['signal_mc_off'][0])
 elif mutation=='background_poi':bg['channels'][0]['samples'][0]['modifiers'].append({'name':'mu_SIG','type':'normfactor','data':None})
 elif mutation=='compiled':compiled['signal_mc_off']['n_parameters']=207
 elif mutation=='append':ps['baseline'][0]['path']='/channels/0/samples/999'
 elif mutation=='moment_modifier':change['removed_signal_shapesys'].pop()
 with pytest.raises(ValueError):v['check_models'](bg,ps,change,compiled)

@pytest.mark.parametrize('name',['../x','/etc/passwd','a/../x','./x','a//x','a\\x'])
def test_relative_path_rejections(tmp_path,name):
 with pytest.raises(ValueError):v['file'](tmp_path,name)

@pytest.mark.parametrize('change',['boolean','extra'])
def test_manifest_schema_cannot_be_reinterpreted(tmp_path,change):
 a=tmp_path/'audit';shutil.copytree(HERE,a);p=a/'manifest.json';d=read('manifest.json')
 if change=='boolean':d['schema_version']=True
 else:d['override_scope']='physics certified'
 p.write_text(json.dumps(d))
 with pytest.raises(ValueError,match='transport schema'):v['verify'](a)


def test_nested_manifest_is_an_extra_artifact(tmp_path):
 a=tmp_path/'audit';shutil.copytree(HERE,a);(a/'nested').mkdir();(a/'nested/manifest.json').write_text('{}')
 with pytest.raises(ValueError,match='Transport inventory'):v['verify'](a)


def differently_encoded_projection(encoding,*,corrupt=False):
 import io
 outputs={n:(HERE/n).read_bytes()for n in v['PROJECTION_SHA256']}
 original=gzip.decompress(outputs['background.json.gz'])
 if corrupt:original+=b'\n'
 if encoding=='timestamp':encoded=gzip.compress(original,mtime=1234567)
 elif encoding=='level':encoded=gzip.compress(original,compresslevel=1,mtime=0)
 else:
  stream=io.BytesIO()
  with gzip.GzipFile(filename='same_background_different_header.json',mode='wb',fileobj=stream,mtime=0)as f:f.write(original)
  encoded=stream.getvalue()
 assert encoded!=outputs['background.json.gz']
 old=v['PROJECTION_SHA256']['background.json.gz'];new=hashlib.sha256(encoded).hexdigest()
 token=('"background.json.gz": "'+old+'"').encode();replacement=('"background.json.gz": "'+new+'"').encode()
 assert outputs['sources.json'].count(token)==1
 outputs['sources.json']=outputs['sources.json'].replace(token,replacement,1);outputs['background.json.gz']=encoded
 return outputs

@pytest.mark.parametrize('encoding',['timestamp','filename','level'])
def test_valid_local_encoder_difference_passes_source_check(monkeypatch,tmp_path,encoding):
 outputs=differently_encoded_projection(encoding);original=v['runpy'].run_path
 def alternate(path,*a,**kw):
  if Path(path)==HERE/'curate.py':return {'projections':lambda root:outputs}
  return original(path,*a,**kw)
 monkeypatch.setattr(v['runpy'],'run_path',alternate)
 assert v['verify']()['source_rederivation']is False
 assert v['verify'](source_root=tmp_path)['source_rederivation']is True


def test_corrupted_decoded_recuration_rejected():
 outputs=differently_encoded_projection('timestamp',corrupt=True)
 with pytest.raises(ValueError,match='decompressed background'):v['check_regenerated'](HERE,outputs)


def test_valid_alternative_shipped_gzip_still_needs_exact_committed_transport(tmp_path):
 a=tmp_path/'audit';shutil.copytree(HERE,a);outputs=differently_encoded_projection('filename');(a/'background.json.gz').write_bytes(outputs['background.json.gz']);refresh(a)
 with pytest.raises(ValueError,match='Source-authenticated projection'):v['verify'](a)

@pytest.mark.parametrize('change',['other_source_map_field','source_map_format','numerical_json'])
def test_encoder_exception_does_not_relax_other_json(change):
 outputs=differently_encoded_projection('level')
 if change=='other_source_map_field':outputs['sources.json']=outputs['sources.json'].replace(b'"raw_event_payloads_included": false',b'"raw_event_payloads_included": true')
 elif change=='source_map_format':outputs['sources.json']+=b'\n'
 else:outputs['results.json']+=b'\n'
 with pytest.raises(ValueError):v['check_regenerated'](HERE,outputs)
