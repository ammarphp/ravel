"""Recreate the public scalar/model projections from exact local originals, no fits."""
from pathlib import Path
import argparse,csv,gzip,hashlib,io,json,runpy
HERE=Path(__file__).resolve().parent
ROLES=runpy.run_path(str(HERE/'source_roles.py'))['ORIGINAL_SOURCES']

def require(x,m):
 if not x:raise ValueError(m)
def exact(x):return json.dumps(x,sort_keys=True,separators=(',',':'),allow_nan=False)
def decode(b):
 def pairs(rows):
  d={}
  for k,v in rows:require(k not in d,'Duplicate JSON key');d[k]=v
  return d
 d=json.loads(b,object_pairs_hook=pairs);exact(d);return d
def encoded(x):return (json.dumps(x,indent=2,allow_nan=False)+'\n').encode()
def sha(b):return hashlib.sha256(b).hexdigest()
def compressed(b):
 stream=io.BytesIO()
 with gzip.GzipFile(filename='',mode='wb',fileobj=stream,mtime=0)as f:f.write(b)
 return stream.getvalue()

def projections(root):
 root=Path(root);raw={}
 for role,pin in ROLES.items():
  p=root/pin['path'];require(p.is_file()and not p.is_symlink()and not any(q.is_symlink()for q in p.parents),'Missing/aliased original')
  raw[role]=p.read_bytes();require(sha(raw[role])==pin['sha256'],'Original changed: '+role)
 data={r:decode(b)for r,b in raw.items()if r not in('control_source','report_source','numerical_engine')};report=data['reviewed_report'];m=data['protocol']
 model={}
 for name in('baseline','signal_mc_off','signal_mc_and_CR_off'):
  old=report['models'][name]
  model[name]={k:old[k]for k in('mu','n_parameters','inference','root_checks','recorded_fresh_checks','portfolio_scope')}
  model[name]['recorded_fit_seconds']=old.get('wall_seconds')
  model[name]['final_fresh_evaluations']=None if name=='baseline'else data[name+'_result']['diagnostics']['evaluations'][-16:]
 results={'schema_version':1,'status':'completed_diagnostic_projection','point':report['point'],'units':report['units'],'scope':report['scope'],'models':model,'rows':report['rows'],'root_count':18,'recorded_fresh_checks':48,'maximum_recorded_root_cls_residual':report['maximum_recorded_root_cls_residual'],'settings':report['settings'],'producer_dependencies':report['producer_dependencies'],'new_events':0,'new_fits':0,'physics_certified':False,'coverage_validated':False,'global_optimum_proven':False,'baseline_full_portfolio_available':False}
 precision={'channels':report['baseline_bins'],'SR_unions':report['baseline_SR_unions'],'scope':'Original20,000-event conditional histogram moments. No precision improvement from omission. Five-percent point diagnostic is analogous; primary preregistered checkpoint is150/140.'}
 review=data['independent_review'];review_projection={'status':review['status'],'passed_controls':review['tests']['passed'],'independently_reconciled_final_nesting_summaries':review['actual_check']['independently_reconciled_final_nesting_summaries'],'baseline_full_portfolio_available':False,'scope':review['actual_check']['claim_scope'],'new_raw_traversal':False,'new_optimization':False,'global_optimum_or_coverage_claim':False}
 outputs={'results.json':encoded(results),'precision.json':encoded(precision),'compiled.json':encoded(m['compiled']),'model_changes.json':encoded(report['transformations']),'independent_review.json':encoded(review_projection),'background.json.gz':compressed(raw['background']),'baseline_patch.json':raw['baseline_patch'],'signal_mc_off_patch.json':raw['signal_mc_off_patch'],'signal_mc_and_CR_off_patch.json':raw['signal_mc_and_CR_off_patch']}
 buf=io.StringIO(newline='');writer=csv.DictWriter(buf,fieldnames=list(report['rows'][0]));writer.writeheader();writer.writerows(report['rows']);outputs['limits_and_ratios.csv']=buf.getvalue().encode()
 outputs['sources.json']=encoded({'schema_version':1,'original_roles':ROLES,'public_scope':'Exact small background/patch bytes are provided. Result, compiled, precision, and review projections omit private execution context. Original full local receipts, result portfolios and logs remain unavailable in this public bundle; their fixed source hashes identify the retained originals without claiming public raw-event custody.','projection_artifacts':{p:sha(b)for p,b in outputs.items()},'raw_event_payloads_included':False,'private_execution_context_included':False})
 return outputs

def main():
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('--source-root',type=Path,required=True);p.add_argument('--out',type=Path,required=True);a=p.parse_args();require(not a.out.exists()and not a.out.is_symlink(),'Use NEW output');outputs=projections(a.source_root);a.out.mkdir(parents=True)
 for n,b in outputs.items():(a.out/n).write_bytes(b)
 print(json.dumps({'status':'exact_original_projections_written','files':len(outputs),'new_events':0,'new_fits':0}))
if __name__=='__main__':main()
