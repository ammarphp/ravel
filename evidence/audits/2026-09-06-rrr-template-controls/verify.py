"""Portable standard-library checks of fixed source projections and arithmetic.

No optimizer, model recompilation, event payload or private environment required.
"""
from pathlib import Path,PurePosixPath
import argparse,csv,gzip,hashlib,io,json,math,runpy
HERE=Path(__file__).resolve().parent
ORIGINAL_SOURCES=runpy.run_path(str(HERE/'source_roles.py'))['ORIGINAL_SOURCES']
PROJECTION_SHA256 = {'results.json': 'a50c09e3f652edb6a73487396e0ee7434557280cbf336b0da666fae0c6df832a', 'precision.json': 'f20720cefeff7db2dbc46b0df003d3675c20d1cf7c2d5960c7adb6e8422d6ff9', 'compiled.json': 'f58aabb206bce767804b4750319b2352d0762059704916aef4f02147a0b811dd', 'model_changes.json': 'c04dd60fb443b2576fba59ca899ac687554ef65755f87398b123e33c8c0923ab', 'independent_review.json': '51d5ee6f6a6e8d467b46d91be36be2c14c704e5b6551268bc35d618ed21ce6b8', 'background.json.gz': 'c251c38af3994a413b1497d0d1d815541691761801e978e1621835061e694142', 'baseline_patch.json': '20e717223a3d4329b8e68b7a3ec2d6719484950104ee586358c9e68dc5d1be5d', 'signal_mc_off_patch.json': '515fb855d421e3a5115b5962e1401a1b6ff0e2839f3672e9c3d686a734df10c7', 'signal_mc_and_CR_off_patch.json': '2234fa7412882068bbbbdc761ccbc0f87638fbda5a6b0fe6817ab983f968e553', 'limits_and_ratios.csv': '6a869e72fa8a63d371abb978b53041d409059aad0a462692f9feb67a9baab253', 'sources.json': '74cd1e0452258e1e2ffe2c2ebd97429b6955fefc19b58a7f09ffd9f0c3cb6f56'}
ARMS=('baseline','signal_mc_off','signal_mc_and_CR_off')
QUANTILES=('observed','expected_minus2','expected_minus1','expected_median','expected_plus1','expected_plus2')
CR={f'CR{k}_MT2_{met}_cuts'for k in('VV','tau','top')for met in('hghmet','lowmet')}

def require(x,m):
 if not x:raise ValueError(m)
def canonical(x):return json.dumps(x,sort_keys=True,separators=(',',':'),allow_nan=False)
def same(a,b):return canonical(a)==canonical(b)
def decode(b):
 def unique(rows):
  out={}
  for k,v in rows:require(k not in out,'Duplicate JSON key');out[k]=v
  return out
 d=json.loads(b,object_pairs_hook=unique);canonical(d);return d
def sha(b):return hashlib.sha256(b).hexdigest()
def number(x):require(type(x)in(int,float)and math.isfinite(x),'Finite numeric required');return float(x)
def near(a,b,tol=1e-12):require(math.isclose(number(a),number(b),rel_tol=0,abs_tol=tol),'Arithmetic differs')
def rel(a,b):require(math.isclose(number(a),number(b),rel_tol=2e-6,abs_tol=1e-14),'Moment arithmetic differs')
def file(root,name):
 require(type(name)is str and name and '\\'not in name and PurePosixPath(name).as_posix()==name and not PurePosixPath(name).is_absolute()and '..'not in PurePosixPath(name).parts,'Portable relative path required')
 p=Path(root)/name;require(p.is_file()and not p.is_symlink()and not any(x.is_symlink()for x in p.parents),'Missing/aliased artifact');return p

def check_results(d):
 require(d['schema_version']==1 and d['status']=='completed_diagnostic_projection'and set(d['models'])==set(ARMS),'Exact diagnostic/model population')
 require(same(d['point'],{'parent_GeV':100,'lsp_GeV':98,'delta_m_GeV':2,'produced_abs_pdgs':[1000011,1000013,2000011,2000013],'original_events':20000})and d['units']=='dimensionless signal strength mu','Point/model/exposure units')
 require(d['root_count']==18 and d['recorded_fresh_checks']==48 and d['baseline_full_portfolio_available']is False and all(d[k]is False for k in('physics_certified','coverage_validated','global_optimum_proven'))and d['new_events']==d['new_fits']==0,'Diagnostic scope')
 maxerror=0.;nesting=0
 for a in ARMS:
  m=d['models'][a];mu=m['mu'];require(set(mu)==set(QUANTILES)and all(number(x)>0 for x in mu.values()),'Six positive limits');expected=[mu[q]for q in QUANTILES[1:]];require(expected==sorted(expected)and len(set(expected))==5,'Ordered expected limits')
  require(m['n_parameters']==(207 if a=='baseline'else 191)and m['recorded_fresh_checks']==16,'Compiled/check population')
  require([x['quantile']for x in m['root_checks']]==list(QUANTILES),'Six exact root-check roles')
  inf=m['inference']
  for k,v in {'backend':'jax','precision':'64b','fit_tolerance':1e-9,'test_stat':'qtilde','level':.05,'root_rtol':1e-4,'root_atol':1e-10,'root_cls_atol':5e-4,'coverage_validated':False,'fresh_check_evaluations':16}.items():require(same(inf[k],v),'Numerical setting differs')
  residuals=[]
  for x in m['root_checks']:
   q=x['quantile'];near(x['mu'],mu[q]);b=x['bracket'];require(len(b)==2 and number(b[0])<mu[q]<number(b[1]),'Root bracket');cl=number(x['recorded_cls']);require(0<=cl<=1 and abs(cl-.05)<=5e-4,'CLs root tolerance');near(x['absolute_cls_residual'],abs(cl-.05));residuals.append(abs(cl-.05))
  near(max(residuals),inf['root_cls_max_error']);maxerror=max(maxerror,max(residuals))
  fresh=m['final_fresh_evaluations']
  if a=='baseline':require(fresh is None and all(x['portfolio_occurrences_checked']is None for x in m['root_checks']),'Missing baseline portfolio must stay explicit');continue
  require(type(fresh)is list and len(fresh)==16,'Two8-point fresh passes');xs=[number(e['mu'])for e in fresh];require(xs[:8]==sorted(xs[:8],reverse=True)and xs[8:]==sorted(xs[8:])and xs[:8]==list(reversed(xs[8:]))and len(set(xs[:8]))==8,'Exact descending/ascending portfolio order')
  for e in fresh:
   p=e['profile_consistency'];require(e['status']=='evaluated'and len(e['cls'])==6 and all(0<=number(x)<=1 for x in e['cls'])and p['passed']is True and p['issues']==[]and p['global_optimum_proven']is False,'Fresh profile/probability scope')
   n=p['twice_nll'];t=number(p['absolute_tolerance']);require(0<=t<=1e-5,'NLL consistency tolerance')
   for free,fixed in(('free_data','fixed_data'),('free_data','mu0_data'),('free_asimov','fixed_asimov'),('free_asimov','generating_asimov')):require(number(n[free])<=number(n[fixed])+t,'Saved NLL nesting fails')
   nesting+=1
  for i,q in enumerate(QUANTILES):
   hits=[e for e in fresh if e['mu']==mu[q]];require(len(hits)==2,'Root twice in fresh passes');near(hits[-1]['cls'][i],m['root_checks'][i]['recorded_cls']);require(abs(number(hits[0]['cls'][i])-.05)<=5e-4 and m['root_checks'][i]['portfolio_occurrences_checked']==2,'Descending root target')
 near(d['maximum_recorded_root_cls_residual'],maxerror)
 require([r['quantile']for r in d['rows']]==list(QUANTILES),'All six ratio rows')
 for q,row in zip(QUANTILES,d['rows']):
  b,m,c=[d['models'][a]['mu'][q]for a in ARMS]
  for key,value in{'baseline_mu':b,'signal_mc_off_mu':m,'signal_mc_and_CR_off_mu':c,'mc_off_over_baseline':m/b,'CR_off_over_mc_off':c/m,'both_off_over_baseline':c/b,'mc_off_change_percent':100*(m/b-1),'additional_CR_off_change_percent':100*(c/m-1),'both_off_change_percent':100*(c/b-1)}.items():near(row[key],value)
 require(nesting==32,'Recorded controlled portfolio denominator');return maxerror

def check_models(bg,patches,changes,compiled):
 require(len(bg['channels'])==38 and len({c['name']for c in bg['channels']})==38 and set(patches)==set(ARMS),'38 background channels')
 baseline=patches['baseline'];require(len(baseline)==38,'38 baseline additions');expected=[];seen=set();removed=[];cr=[]
 for op in baseline:
  require(set(op)=={'op','path','value'}and op['op']=='add','Only signal append operations');parts=op['path'].split('/');require(len(parts)==5 and parts[0]==''and parts[1]=='channels'and parts[3]=='samples'and parts[2].isdigit()and parts[4].isdigit(),'Numeric signal append path');i,j=int(parts[2]),int(parts[4]);require(str(i)==parts[2]and str(j)==parts[4]and i<38 and i not in seen,'Unique exact append index');seen.add(i);ch=bg['channels'][i];s=op['value'];require(j==len(ch['samples'])and set(s)=={'name','data','modifiers'}and s['name']=='native_signal'and len(s['data'])==1 and number(s['data'][0])>=0,'Signal identity')
  mods=s['modifiers'];require(mods[0]=={'name':'mu_SIG','type':'normfactor','data':None}and len(mods)in(1,2),'POI/MC modifier identity')
  if len(mods)==2:require(mods[1]['type']=='shapesys'and len(mods[1]['data'])==1 and number(mods[1]['data'][0])>0,'Native signal MC constraint');removed.append({'channel':ch['name'],'modifier':mods[1]})
  else:require(s['data']==[0.],'Only empty bins omit MC')
  expected.append({'op':'add','path':op['path'],'value':{'name':s['name'],'data':s['data'],'modifiers':mods[:1]}})
  if ch['name']in CR:cr.append({'channel':ch['name'],'nominal_signal_yield':s['data'][0]})
 require(len(removed)==16 and {x['channel']for x in cr}==CR and same(changes['removed_signal_shapesys'],removed)and same(changes['removed_CR_signal'],cr),'Exact16 MC and6CR changes')
 require(same(patches['signal_mc_off'],expected)and same(patches['signal_mc_and_CR_off'],[x for x in expected if bg['channels'][int(x['path'].split('/')[2])]['name']not in CR]),'Unintended model change')
 require(bg['measurements'][0]['config']['poi']=='mu_SIG'and all(m['name']!='mu_SIG'for c in bg['channels']for s in c['samples']for m in s['modifiers']),'Background POI collision')
 names=sorted(c['name']for c in bg['channels']);observed={o['name']:o['data'][0]for o in bg['observations']};require(set(observed)==set(names),'Observed channel identities')
 for a in ARMS:
  x=compiled[a];require(x['n_parameters']==(207 if a=='baseline'else 191)and x['channels']==names and x['observed_main']==[observed[n]for n in names]and len(x['nominal_expected_main'])==38,'Compiled retained channel/data metadata')
  for value in x['nominal_expected_main']:number(value)
 require(same(compiled['baseline']['nominal_expected_main'],compiled['signal_mc_off']['nominal_expected_main']),'MC omission changed central compiled expectation')
 for i,n in enumerate(names):near(compiled['signal_mc_off']['nominal_expected_main'][i]-compiled['signal_mc_and_CR_off']['nominal_expected_main'][i],next(x['nominal_signal_yield']for x in cr if x['channel']==n)if n in CR else 0.,1e-10)

def check_precision(p):
 rows=p['channels'];require(len(rows)==38 and len({r['channel']for r in rows})==38,'38 precision rows');weights=[]
 for r in rows:
  n=r['selected_events'];require(type(n)is int and n>=0,'Selected count');w=number(r['sumw_pb']);v=number(r['sumw2_pb2']);require(w>=0 and v>=0,'Positive original-weight moments');rel(r['nominal_yield'],w*139000.)
  if n==0:require(w==v==0 and r['histogram_relative_mc']is None and r['diagnostic_5percent']=='unresolved'and r['likelihood_mc_constraint']is None,'Zero-selected precision unresolved')
  else:require(w>0 and v>0 and r['likelihood_mc_constraint']is not None,'Occupied bin constraint');rel(v,n*(w/n)**2);rel(r['histogram_relative_mc'],math.sqrt(v)/w);require(r['diagnostic_5percent']==('within_target'if math.sqrt(v)/w<=.05 else'exceeds_target'),'Histogram target status');weights.append(w/n)
 for w in weights:rel(w,weights[0])
 require([x['category']for x in p['SR_unions']]==['SR_high','SR_low'],'Two declared SR unions')
 for u in p['SR_unions']:
  group=u['category'].split('_')[1];selected=[r for r in rows if r['channel'].startswith('SR')and r['mapping']['region'].startswith('SR_S_'+group+'_')];require(len(selected)==16 and u['original_denominator']==20000 and u['diagnostic_target']==.05,'Original union/exposure')
  require(u['selected_events']==sum(r['selected_events']for r in selected),'Union counts');rel(u['sumw_pb'],math.fsum(r['sumw_pb']for r in selected));rel(u['sumw2_pb2'],math.fsum(r['sumw2_pb2']for r in selected));rel(u['histogram_relative_mc'],math.sqrt(u['sumw2_pb2'])/u['sumw_pb'])
 require(sum(r['selected_events']==0 for r in rows)==22,'22 empty channel rows')

def check_regenerated(root,outputs):
 """Encoder-independent background identity; all other projected bytes exact."""
 require(set(outputs)==set(PROJECTION_SHA256),'Regeneration population')
 name='background.json.gz';shipped=file(root,name).read_bytes();generated=outputs[name]
 require(sha(shipped)==PROJECTION_SHA256[name],'Shipped background transport changed')
 original=gzip.decompress(shipped);decoded=gzip.decompress(generated)
 require(decoded==original and sha(decoded)==ORIGINAL_SOURCES['background']['sha256'],'Regenerated decompressed background differs')
 # The generated source map honestly pins its own gzip transport. Permit only
 # this exact token substitution; no JSON formatting or other field may drift.
 token=(json.dumps(name)+': '+json.dumps(PROJECTION_SHA256[name])).encode()
 replacement=(json.dumps(name)+': '+json.dumps(sha(generated))).encode()
 source_bytes=file(root,'sources.json').read_bytes()
 require(source_bytes.count(token)==1,'Unique background transport source-map token')
 require(outputs['sources.json']==source_bytes.replace(token,replacement,1),'Regenerated source map differs beyond background encoding')
 for n,b in outputs.items():
  if n not in(name,'sources.json'):require(file(root,n).read_bytes()==b,'Source rederivation differs: '+n)

def verify(root=HERE,source_root=None):
 root=Path(root);require(not any(p.is_symlink()for p in root.rglob('*')),'Aliased public bundle');m=decode(file(root,'manifest.json').read_bytes());require(set(m)=={'schema_version','files'}and type(m['schema_version'])is int and m['schema_version']==1,'Exact transport schema');actual={str(p.relative_to(root)):sha(p.read_bytes())for p in root.rglob('*')if p.is_file()and p!=root/'manifest.json'};require(m['files']==actual,'Transport inventory differs')
 for n,digest in PROJECTION_SHA256.items():require(sha(file(root,n).read_bytes())==digest,'Source-authenticated projection differs: '+n)
 sources=decode(file(root,'sources.json').read_bytes());require(same(sources['original_roles'],ORIGINAL_SOURCES),'Mandatory original source roles differ');require(sources['raw_event_payloads_included']is False and sources['private_execution_context_included']is False,'Public custody scope')
 require(set(sources['projection_artifacts'])==set(PROJECTION_SHA256)-{'sources.json'},'Exact projection roles')
 for n,digest in sources['projection_artifacts'].items():require(PROJECTION_SHA256[n]==digest,'Source projection commitment differs')
 d=decode(file(root,'results.json').read_bytes());err=check_results(d);bgbytes=gzip.decompress(file(root,'background.json.gz').read_bytes());require(sha(bgbytes)==ORIGINAL_SOURCES['background']['sha256'],'Exact background bytes differ');bg=decode(bgbytes)
 patches={a:decode(file(root,a+'_patch.json').read_bytes())for a in ARMS}
 for a in ARMS:require(sha(file(root,a+'_patch.json').read_bytes())==ORIGINAL_SOURCES[a+'_patch']['sha256'],'Exact patch bytes differ')
 check_models(bg,patches,decode(file(root,'model_changes.json').read_bytes()),decode(file(root,'compiled.json').read_bytes()));check_precision(decode(file(root,'precision.json').read_bytes()))
 csvrows=list(csv.DictReader(io.StringIO(file(root,'limits_and_ratios.csv').read_text())));require(len(csvrows)==6,'Six CSV rows')
 for x,y in zip(csvrows,d['rows']):require(set(x)==set(y)and x['quantile']==y['quantile'],'CSV roles');[near(float(x[k]),v)for k,v in y.items()if k!='quantile']
 for p in root.rglob('*'):
  if p.is_file()and p.suffix in('.json','.md','.csv'):require(not any(t in p.read_text()for t in('/Users/','/private/tmp/','supervisor_pid','authorization_quote','environment_sha256')),'Private execution context leaked')
 if source_root is not None:
  outputs=runpy.run_path(str(HERE/'curate.py'))['projections'](Path(source_root))
  check_regenerated(root,outputs)
 return {'status':'passed_stored_diagnostic_checks','models':3,'controlled_fits':2,'root_values':18,'producer_reported_fresh_checks':48,'stored_controlled_nesting_summaries':32,'maximum_root_cls_residual':err,'baseline_full_portfolio_available':False,'source_rederivation':source_root is not None,'new_fits':0,'new_events':0,'physics_certified':False}
if __name__=='__main__':
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('--source-root',type=Path);a=p.parse_args();print(json.dumps(verify(source_root=a.source_root),indent=2))
