"""Native-only child for complete released SFitter sectors, algorithms and phases.

Importing this module does not import an engine. Dispatch remains the existing
approved science worker. Opaque state is read only after the parent authenticates
the complete original successful ordinary capsule and its complete membership.
"""
import hashlib
import importlib.metadata
import importlib.util
import json
import os
from pathlib import Path
import pickle
import sys

def _module(name,path):
    spec=importlib.util.spec_from_file_location(name,path)
    module=importlib.util.module_from_spec(spec);sys.modules[name]=module
    spec.loader.exec_module(module);return module

def initialize(params, contract, device, doc):
    """Construct the real full likelihood, then the real selected-dimension fitter."""
    import torch
    from sfitter.likelihood.full_likelihood import ProfileLikelihood
    from sfitter.likelihood.toys2d import SpiralLikelihood, FivePointLikelihood
    from sfitter.likelihood.toy import ToyLikelihood
    from sfitter.fit.flow_fitter import FlowFitter
    from sfitter.fit.smc_fitter import SMCFitter
    from sfitter.fit.craft import CraftFitter
    native_params={k:v for k,v in params.items() if k!='parameter_names'}
    cls={'top':ProfileLikelihood,'higgs':ProfileLikelihood,'toy':ToyLikelihood,
         'spiral':SpiralLikelihood,'five_point':FivePointLikelihood}[contract['profile']]
    full=cls(native_params,device)
    if list(full.parameter_names)!=contract['selection']['full'] or full.dims_nuisance!=0:
        raise ValueError('complete native sector coordinates differ')
    selected=contract['selection']
    class Coordinates:
        parameter_names=selected['selected']
        dims_parameter=len(parameter_names)
        dims_nuisance=0
        dims_total=dims_parameter
        def embed(self,x):
            if x.shape[-1]!=self.dims_parameter:raise ValueError('selected native coordinate shape differs')
            out=torch.zeros((*x.shape[:-1],len(selected['full'])),device=x.device,dtype=x.dtype)
            # index_copy is differentiable; every omitted coefficient stays zero.
            return out.index_copy(-1,torch.tensor(selected['indices'],device=x.device),x)
        def log_likelihood(self,x):return full.log_likelihood(self.embed(x))
        def log_prior(self,x):return full.log_prior(self.embed(x))
    likelihood=Coordinates()
    fitter={'flow':FlowFitter,'smc':SMCFitter,'craft':CraftFitter}[contract['algorithm']](
        params,True,device,doc.get_file('model.pth'),likelihood)
    return fitter,likelihood,full

def make_plots(doc,params,results,algorithm):
    from sfitter.eval.plots import Plots
    if algorithm=='flow' and len(results.parameters)>1:
        Plots.make_plots(doc,params,results)
        return {'called':['hist_weights','hist_1d','hist_2d_marginalize','hist_2d_profile','contour_2d','triangle'],'unavailable':{}}
    plots=Plots(params,results);called=[];unavailable={}
    if algorithm=='flow':plots.hist_weights(doc.add_file('hist_weights.pdf'));called.append('hist_weights')
    else:unavailable['hist_weights']='native SMC/CRAFT do not return flow weight histograms'
    plots.hist_1d(doc.add_file('hist_1d.pdf'));called.append('hist_1d')
    if len(results.parameters)>1:
        plots.hist_2d(doc.add_file('hist_2d_marginalize.pdf'),source='marginalize')
        plots.hist_2d(doc.add_file('hist_2d_profile.pdf'),source='profile')
        plots.contour_2d(doc.add_file('contour_2d.pdf'));plots.triangle(doc.add_file('triangle.pdf'))
        called+=['hist_2d_marginalize','hist_2d_profile','contour_2d','triangle']
    else:unavailable['pair_plots']='one selected coordinate has no two-dimensional parameter pairs'
    return {'called':called,'unavailable':unavailable}

def saved_directory(basedir, package_root):
    """Bind Documenter's lexical '..' path to its actual unaliased owned run."""
    import re
    package=Path(package_root).absolute()
    if '..' in package.parts or any(p.is_symlink() for p in (package,*package.parents)):
        raise ValueError('owned native package aliases forbidden')
    original=Path(basedir).absolute()
    if any(p.is_symlink() for p in (original,*original.parents)):
        raise ValueError('native Documenter path aliases forbidden')
    name=original.name
    if not re.fullmatch(r'\d{8}_\d{6}_[A-Za-z0-9_]{1,64}',name):
        raise ValueError('safe native Documenter run name required')
    expected=package/'output'/name
    if any(p.is_symlink() for p in (expected,*expected.parents)) or not expected.is_dir():
        raise ValueError('complete unaliased owned native run required')
    actual=original.resolve(strict=True)
    if actual!=expected or expected.resolve(strict=True)!=expected:
        raise ValueError('native Documenter escaped owned output namespace')
    return expected

def main(argv=None):
    args=sys.argv[1:] if argv is None else argv
    if len(args)!=1:raise ValueError('one exact native request required')
    req_path=Path(args[0]).absolute();req=json.loads(req_path.read_bytes())
    fields={'schema_version','config','contract','package_root','run_card','output','basis','runtime_assets','source_files','support_files','selected_files','saved_run_name'}
    if set(req)!=fields or req['schema_version']!=2:raise ValueError('closed complete native request required')
    out=Path(req['output']);helper=_module('ravel_sfitter_worker',out/'sfitter_worker.py')
    progress={'schema_version':2,'operation':req['config']['phase'],'phase':'bootstrap','completed':[],'error':None,'physics_validated':False}
    helper._write(out/'progress.json',progress)
    try:
        runtime=req['config']['runtime']
        if Path(sys.executable).resolve()!=Path(runtime['python']['path']).resolve():raise ValueError('native interpreter differs')
        helper._check({runtime['python']['path']:runtime['python']['sha256']})
        for group in ('runtime_assets','source_files','support_files','selected_files'):helper._check(req[group])
        sys.path[:0]=[req['package_root'],*runtime['site_roots']];os.chdir(req['package_root'])
        if runtime['device']=='cpu':os.environ['CUDA_VISIBLE_DEVICES']=''
        versions={name:importlib.metadata.version(name) for name in runtime['versions']}
        if versions!=runtime['versions']:raise ValueError('native distribution versions differ')
        import torch
        if str(torch.device('cuda:0' if torch.cuda.is_available() else 'cpu'))!=runtime['device']:raise ValueError('native device differs')
        torch.set_num_threads(1);torch.set_default_dtype(torch.float64)
        exporter=_module('ravel_sfitter_export',out/'sfitter_results.py')
        from sfitter.util.documenter import Documenter
        phase=req['config']['phase']
        if phase=='run':doc,params=Documenter.from_param_file(req['run_card'])
        else:doc,params=Documenter.from_saved_run(req['saved_run_name'])
        # Saved params are immutable admission inputs; fresh card differs solely
        # by the literal relocated datacard path. Compare their parsed meaning.
        if params!=req['contract']['params']:raise ValueError('actual native params differ from admitted card')
        fitter,likelihood,full=initialize(params,req['contract'],torch.device(runtime['device']),doc)
        origin=next({'path':p,'sha256':h} for p,h in req['source_files'].items() if p.endswith('/sfitter/likelihood/full_likelihood.py'))
        initialized=exporter.complete_initialized_state(full,req['contract'],origin)
        helper._write(out/'initialized-state.json',initialized)
        progress['completed']+=['native_initialization','initialized_state_retained'];progress['phase']='native_calculation';helper._write(out/'progress.json',progress)
        if req['config']['operation']=='fixed-vector-qualification':
            with torch.no_grad():scores=likelihood.log_likelihood(torch.tensor(req['config']['vectors'],device=runtime['device'],dtype=torch.float64))
            delivery={'schema_version':2,'kind':'sfitter_complete_fixed_vectors','selection':req['contract']['selection'],'scores':exporter.array(scores.cpu().numpy()),'vectors':req['config']['vectors'],'profile':req['contract']['profile'],'physics_validated':False}
            plots={'called':[],'unavailable':{'all':'fixed-vector operation performs no fit or plotting'}}
        else:
            if phase=='run':fitter.train();fitter.save()
            else:fitter.load()
            if phase=='plot':
                with open(doc.get_file('results.pkl'),'rb') as stream:results=pickle.load(stream)
            else:
                results=fitter.fit()
                with open(doc.add_file('results.pkl'),'wb') as stream:pickle.dump(results,stream);stream.flush();os.fsync(stream.fileno())
            delivery=exporter.complete_fit_result(results,req['basis'],req['contract']['algorithm'],req['contract']['profile'])
            helper._write(out/'delivery.json',delivery)
            plots=make_plots(doc,params,results,req['contract']['algorithm'])
        helper._write(out/'delivery.json',delivery);helper._write(out/'plots.json',plots)
        run=saved_directory(doc.basedir,req['package_root'])
        helper._write(out/'saved-state.json',{'run_name':run.name,'path':str(run),'phase':phase,'trained':phase=='run' and req['config']['operation']=='fit','fit_called':phase!='plot' and req['config']['operation']=='fit','plot_only':phase=='plot'})
        for name in ('delivery.json','initialized-state.json'):
            if (out/name).stat().st_size>req['config']['max_export_bytes']:raise ValueError('native complete export exceeds declared bound')
        for group in ('runtime_assets','source_files','support_files','selected_files'):helper._check(req[group])
        observed={**req,'runtime_assets':{**req['runtime_assets'],**req['support_files']},'exporter_sha256':req['support_files'][str(out/'sfitter_results.py')],'driver_sha256':req['support_files'][str(out/'driver.py')]}
        helper._write(out/'runtime.json',{'schema_version':2,'versions':versions,'device':runtime['device'],'precision':'double','imports':helper._imports(observed),'source_files':req['source_files'],'runtime_assets':req['runtime_assets'],'support_files':req['support_files'],'randomness':'unchanged upstream; no deterministic seed or independent-chain claim','physics_validated':False})
        progress['completed']+=['native_delivery','native_plots','final_custody'];progress['phase']='complete';helper._write(out/'progress.json',progress)
        return 0
    except Exception as exc:
        progress['error']={'type':type(exc).__name__,'message':str(exc)};helper._write(out/'progress.json',progress);raise

if __name__=='__main__':raise SystemExit(main())
