"""Fresh native FeynGraph child; never imported by planning to load its engine."""
import hashlib
import importlib
import json
from pathlib import Path
import sys

COMMIT='15afe2f2c701331c76a0f5d55a752dca099104be'
def digest(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def check(assets):
    for p,h in assets.items():
        q=Path(p)
        if not q.is_file() or q.is_symlink() or digest(q)!=h:raise ValueError('native admitted input changed: '+p)
def particle(p):return {k:getattr(p,k)() for k in ('name','anti_name','is_anti','is_fermi','pdg','spin','color')}
def leg(p):return {'id':p.id(),'vertex_id':p.vertex().id(),'particle':particle(p.particle()),'momentum':p.momentum(),'momentum_text':p.momentum_str(),'ray_index':p.ray_index(),'ray_index_ordered':p.ray_index_ordered()}
def propagator(p):return {'id':p.id(),'vertex_ids':[v.id() for v in p.vertices()],'particle':particle(p.particle()),'momentum':p.momentum(),'momentum_text':p.momentum_str(),'ray_indices':[p.ray_index(i) for i in range(2)],'ordered_ray_indices':[p.ray_index_ordered(i) for i in range(2)]}
def vertex(v):return {'id':v.id(),'degree':v.degree(),'interaction':{'name':v.interaction().name(),'coupling_orders':v.interaction().coupling_orders()},'particles_ordered':[particle(p) for p in v.particles_ordered()],'propagators_ordered':[p.id() for p in v.propagators_ordered()]}
def row(d,i,loops):
    return {'id':i,'incoming':[leg(p) for p in d.incoming()],'outgoing':[leg(p) for p in d.outgoing()],'propagators':[propagator(p) for p in d.propagators()],'vertices':[vertex(v) for v in d.vertices()],'symmetry_factor':d.symmetry_factor(),'relative_sign':d.sign(),'coupling_orders':d.orders(),'bridges':[p.id() for p in d.bridges()],'loops':[{'index':j,'size':d.loopsize(j),'chord':[p.id() for p in d.chord(j)],'vertex_ids':[v.id() for v in d.loop_vertices(j)]} for j in range(loops)]}
def check_source_membership(model,vertices,splittings):
    """None is an optional splitting, never evidence that a vertex exists."""
    if type(vertices) is not list or type(splittings) is not list:
        raise ValueError('complete native vertex membership census required')
    native=[]
    for v in vertices:
        if type(v) is not dict or set(v)!={'name','coupling_orders'} or type(v['name']) is not str or not v['name'] or type(v['coupling_orders']) is not dict:
            raise ValueError('closed native vertex membership record required')
        if any(type(k) is not str or type(n) is not int or n<0 for k,n in v['coupling_orders'].items()):
            raise ValueError('literal native coupling orders required')
        native.append(v['name'])
    if len(set(native))!=len(native):raise ValueError('duplicate native vertex membership')
    requested=model['source_vertex_names'];names=[];claimed=[];available=set(native)
    for row in splittings:
        if type(row) is not dict or set(row)!={'name','splitting'} or type(row['name']) is not str:
            raise ValueError('closed source vertex splitting roster required')
        names.append(row['name']);split=row['splitting']
        if split is None:
            members=[row['name']]
        else:
            if type(split) is not dict or not split:
                raise ValueError('nonempty native vertex splitting required')
            members=list(split)
            for name,indices in split.items():
                if type(name) is not str or not name or type(indices) is not list or not indices:
                    raise ValueError('complete native vertex splitting members required')
                for pair in indices:
                    if type(pair) not in (tuple,list) or len(pair)!=2 or any(type(i) is not int or i<0 for i in pair):
                        raise ValueError('literal native color/Lorentz index pair required')
        if any(name not in available for name in members):
            raise ValueError('source vertex missing from actual native membership')
        if set(members)&set(claimed):raise ValueError('ambiguous source/native vertex membership')
        claimed.extend(members)
    if names!=requested:raise ValueError('complete ordered source vertex splitting roster differs')
    if model['kind']=='ufo' and set(claimed)!=available:
        raise ValueError('complete source/native UFO vertex membership differs')
    return splittings
def enumerate_processes(c,fg,model,output,write):
    """Actual released calls; an explicit model is mandatory, including builtin."""
    result={'schema_version':1,'engine_commit':COMMIT,'model':c['model'],'model_particles':[particle(p) for p in model.particles()],'model_vertices':[{'name':v.name(),'coupling_orders':v.coupling_orders()} for v in model.vertices()],'source_vertex_splittings':[{ 'name':n,'splitting':model.splitting(n)} for n in c['model']['source_vertex_names']],'processes':[],'complete':False,'imports':[]}
    write(result)
    check_source_membership(c['model'],result['model_vertices'],result['source_vertex_splittings'])
    fg.set_threads(1)
    for requested in c['processes']:
        p={'request':requested,'count':None,'diagrams':[],'renders':[],'complete':False};result['processes'].append(p);write(result)
        selector=fg.DiagramSelector()
        for s in requested['selectors']:getattr(selector,s['method'])(*s['arguments'])
        generator=fg.DiagramGenerator(requested['incoming'],requested['outgoing'],requested['loops'],model,selector)
        generator.set_momentum_labels(requested['momentum_labels']);container=generator.generate();p['count']=len(container)
        if p['count']>c['max_diagrams']:
            write(result);raise ValueError('native complete population exceeds admitted cap; no truncation labelled complete')
        for i in range(p['count']):p['diagrams'].append(row(container[i],i,requested['loops']))
        for i in range(min(p['count'],c['render']['max_visualize'])):
            for fmt in c['render']['formats']:
                rel=requested['id']+'/diagram-'+str(i)+('.svg' if fmt=='svg' else '.tikz');q=Path(output)/rel;q.parent.mkdir(parents=True,exist_ok=True)
                getattr(container[i],'draw_svg' if fmt=='svg' else 'draw_tikz')(str(q))
                p['renders'].append({'diagram_id':i,'format':fmt,'relative_path':rel,'sha256':digest(q),'size':q.stat().st_size})
        p['complete']=True;write(result)
    result['complete']=True;write(result);return result

def main():
    request_path=Path(sys.argv[1]);raw=request_path.read_bytes();r=json.loads(raw);check(r['assets'])
    if digest(__file__)!=r['driver_sha256'] or str(Path(sys.executable).resolve()) not in r['assets']:raise ValueError('actual native driver/interpreter not admitted')
    if 'feyngraph' in sys.modules:raise ValueError('fresh engine namespace required')
    sys.path[:0]=r['sites'];fg=importlib.import_module('feyngraph');origins=[]
    for n,m in list(sys.modules.items()):
        if n=='feyngraph' or n.startswith('feyngraph.'):
            p=getattr(m,'__file__',None)
            if p is None or str(Path(p).resolve()) not in r['assets']:raise ValueError('engine import outside admitted runtime')
            origins.append({'name':n,'path':str(Path(p).resolve()),'sha256':digest(p)})
    c=r['configuration'];m=c['model'];model=fg.Model.from_ufo(r['model_entry']) if m['kind']=='ufo' else fg.Model.from_qgraf(r['model_entry']) if m['kind']=='qgraf' else fg.Model()
    out=Path(r['output'])
    def write(x):
        tmp=out/'enumeration.json.tmp';tmp.write_text(json.dumps(x,indent=2,allow_nan=False)+'\n');tmp.replace(out/'enumeration.json')
    result=enumerate_processes(c,fg,model,out,write);result['imports']=origins;check(r['assets'])
    if request_path.read_bytes()!=raw:raise ValueError('native request changed')
    write(result)
if __name__=='__main__':main()
