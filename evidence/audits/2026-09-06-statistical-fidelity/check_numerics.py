"""Fresh counting-root comparison using guarded Brent and independent pyhf TOMS748.
This compares root solvers for one model, not independent statistical frameworks.
"""
import argparse,hashlib,importlib.metadata,json,platform,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[3]
sys.path.insert(0,str(ROOT/'src'))
import pyhf
from ravel.physics.pyhf_exclude import compute,model_from_counting,robust_optimizer

def run():
 engine=ROOT/'src/ravel/physics/pyhf_exclude.py'
 pin=hashlib.sha256(engine.read_bytes()).hexdigest()
 counting=dict(n=10,b=10,db=2,s=5)
 pyhf.set_backend('numpy',robust_optimizer(maxiter=200000,tolerance=1e-9),precision='64b')
 model,data=model_from_counting(counting)
 result=compute(model,data,n_curve=5)
 # Independent scalar root solver on a fresh model/standard optimizer. Sharing
 # pyhf likelihood and asymptotic distribution is explicit; this is no coverage test.
 pyhf.set_backend('numpy',pyhf.optimize.scipy_optimizer(maxiter=200000,tolerance=1e-9),precision='64b')
 reference_model,reference_data=model_from_counting(counting)
 observed,expected=pyhf.infer.intervals.upper_limits.toms748_scan(reference_data,reference_model,.001,10.,level=.05,rtol=1e-8)
 observed=float(observed);expected=[float(x) for x in expected]
 relative=result['obs_limit']/observed-1
 assert abs(relative)<1e-4,(result['obs_limit'],observed)
 assert all(abs(a/b-1)<1e-4 for a,b in zip(result['exp_limits'],expected))
 assert hashlib.sha256(engine.read_bytes()).hexdigest()==pin
 return dict(schema_version=1,engine_sha256=pin,script_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),runtime={'python':platform.python_version(),**{n:importlib.metadata.version(n) for n in ['pyhf','numpy','scipy','iminuit']}},root_precision_example=dict(counting_input=counting,plot_grid_points=5,level=.05,reference_solver='pyhf.infer.intervals.upper_limits.toms748_scan; fresh model and standard scipy optimizer',reference_observed_limit=observed,refined_observed_limit=result['obs_limit'],reference_expected_limits=expected,refined_expected_limits=result['exp_limits'],refined_relative_error=relative,root_rtol=1e-4,limit_status=result['limit_status'],limit_brackets=result['limit_brackets'],fit_diagnostics=result['fit_diagnostics']),result=result)

if __name__=='__main__':
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('--out',type=Path,required=True);a=p.parse_args()
 if a.out.exists():p.error('--out must be new; preserve prior evidence')
 result=run()
 with a.out.open('x') as f:json.dump(result,f,indent=2,allow_nan=False);f.write('\n')
 print(json.dumps(result['root_precision_example'],indent=2))
