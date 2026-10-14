"""Finite UFO selected-vertex -> Diagrammatica construction and tree reference.

UFO source is parsed, never imported. This is a declared scalar-expression/
Lorentz dialect, not an emulator of arbitrary UFO Python or FeynGraph enumeration.
The ordinary diagrammatica-code operation remains the execution/review owner.
"""
import ast
import cmath
from copy import deepcopy
import hashlib
import json
import math
from pathlib import Path
import re
import time

from ravel.physics import model_tool_bridge as custody
from ravel.validation.model_tool_witness import card_values

OPERATION = 'ufo_decay_code'
FILES = {'parameters.py':'Parameter', 'particles.py':'Particle',
         'vertices.py':'Vertex', 'couplings.py':'Coupling',
         'lorentz.py':'Lorentz', 'function_library.py':'Function'}
MAX_BYTES = 16 * 1024**2
SCOPE = ('Selected canonical neutral-singlet tree one-vertex decay coefficient '
         'transport, unexecuted HEPTAPOD code and independent on-shell reference; '
         'no imported UFO, CAS amplitude evaluation or complete-model certificate.')


def _json(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False)


def _number(value):
    if type(value) not in (int, float, complex):
        raise ValueError('scalar numeric expression required; bool/array unsupported')
    value = complex(value)
    if not math.isfinite(value.real) or not math.isfinite(value.imag) or abs(value) > 1e100:
        raise ValueError('nonfinite or overflowing selected UFO expression')
    return value


def _real(value, label, nonnegative=False):
    value = _number(value)
    if value.imag != 0 or (nonnegative and value.real < 0):
        raise ValueError('finite real '+label+' required; no real-part/absolute-value repair')
    return value.real


def _pair(value):
    value = _number(value)
    return {'real':value.real, 'imag':value.imag}


def _literal(node):
    try:
        return ast.literal_eval(node)
    except (ValueError, TypeError) as exc:
        raise ValueError('canonical literal UFO attribute required') from exc


def _numeric_literal(node):
    if isinstance(node,ast.Constant) and type(node.value) in (int,float):
        return _real(node.value,'literal numeric attribute')
    if isinstance(node,ast.UnaryOp) and isinstance(node.op,(ast.UAdd,ast.USub)):
        return _numeric_literal(node.operand)*(1 if isinstance(node.op,ast.UAdd) else -1)
    if isinstance(node,ast.BinOp) and isinstance(node.op,(ast.Add,ast.Sub,ast.Mult,ast.Div)):
        a,b=_numeric_literal(node.left),_numeric_literal(node.right)
        try:
            value=a+b if isinstance(node.op,ast.Add) else a-b if isinstance(node.op,ast.Sub) else a*b if isinstance(node.op,ast.Mult) else a/b
        except ZeroDivisionError as exc: raise ValueError('undefined literal numeric attribute') from exc
        return _real(value,'literal numeric attribute')
    raise ValueError('numeric/rational literal attribute required; arbitrary expression unsupported')


def _ref(node, namespace):
    if not isinstance(node, ast.Attribute) or not isinstance(node.value, ast.Name) or node.value.id != namespace:
        raise ValueError('literal '+namespace+' source reference required')
    return node.attr


def _records(text, factory):
    """Whole declaration modules; no hidden procedural mutation is interpreted."""
    result = {}
    for st in ast.parse(text).body:
        if isinstance(st, (ast.Import, ast.ImportFrom)):
            continue
        if isinstance(st, ast.Expr) and isinstance(st.value, ast.Constant) and isinstance(st.value.value, str):
            continue
        if isinstance(st, ast.Try) and factory == 'Lorentz':
            # Released SM optional form_factors import: imports only, no body.
            if (all(isinstance(x,(ast.Import,ast.ImportFrom)) for x in st.body)
                    and not st.orelse and not st.finalbody
                    and all(not h.name and isinstance(h.type,ast.Name) and h.type.id=='ImportError'
                            and all(isinstance(x,ast.Pass) for x in h.body) for h in st.handlers)):
                continue
        if not isinstance(st, ast.Assign) or len(st.targets) != 1 or not isinstance(st.targets[0], ast.Name):
            raise ValueError('procedural UFO module is outside static declaration dialect')
        target = st.targets[0].id
        if target.startswith('__') and isinstance(st.value, ast.Constant):
            continue
        if target in result:
            raise ValueError('duplicate source declaration '+target)
        call = st.value
        if not isinstance(call, ast.Call) or call.args:
            raise ValueError('canonical keyword constructor required; source aliases/procedures unsupported')
        if factory == 'Particle' and isinstance(call.func, ast.Attribute) and call.func.attr == 'anti':
            if call.keywords or not isinstance(call.func.value, ast.Name) or call.func.value.id not in result:
                raise ValueError('ordered canonical anti() declaration required')
            result[target] = {'anti_of':call.func.value.id, 'line':st.lineno}
            continue
        if not isinstance(call.func, ast.Name) or call.func.id != factory:
            raise ValueError('only '+factory+' declarations are understood in this module')
        attrs = {x.arg:x.value for x in call.keywords}
        if None in attrs or len(attrs) != len(call.keywords):
            raise ValueError('duplicate/expanded UFO constructor keywords')
        result[target] = {'attrs':attrs, 'line':st.lineno}
    if not result or len(result) > 4096:
        raise ValueError('bounded nonempty UFO declaration population required')
    return result


class Expressions:
    """Evaluate captured declared scalar expressions without eval/import/exec."""
    def __init__(self, parameters, functions, supplied):
        self.parameters, self.functions, self.supplied = parameters, functions, supplied
        self.values, self.active, self.ledger = {}, [], {}

    def parameter(self, name):
        if name in self.values:
            return self.values[name]
        if name not in self.parameters or name in self.active or len(self.active) >= 128:
            raise ValueError('unresolved/cyclic selected parameter '+name)
        self.active.append(name)
        row = self.parameters[name]; attrs = row['attrs']
        nature = _literal(attrs['nature']); declared_type = _literal(attrs['type'])
        if nature == 'external':
            address = (_literal(attrs['lhablock']).lower(), tuple(_literal(attrs['lhacode'])))
            if address not in self.supplied:
                raise ValueError('missing explicitly supplied external parameter '+name)
            value = _number(self.supplied[address]); expression = None
        elif nature == 'internal':
            expression = _literal(attrs['value'])
            if not isinstance(expression, str):
                raise ValueError('internal scalar expression string required')
            value = self.expression(expression); address = None
        else:
            raise ValueError('unsupported selected parameter nature')
        if declared_type not in ('real','complex') or (declared_type == 'real' and value.imag != 0):
            raise ValueError('evaluated selected parameter disagrees with declared real/complex type')
        self.active.pop(); self.values[name] = value
        self.ledger[name] = {'source_line':row['line'], 'nature':nature, 'type':declared_type,
                             'source_expression':expression, 'card_address':None if address is None else [address[0],list(address[1])],
                             'value':_pair(value)}
        return value

    def expression(self, text, local=None, depth=0):
        if not isinstance(text,str) or len(text) > 4096 or depth > 32:
            raise ValueError('bounded scalar source expression required')
        node = ast.parse(text, mode='eval').body
        if len(list(ast.walk(node))) > 512:
            raise ValueError('selected expression exceeds syntax bound')
        return self._eval(node, local or {}, depth)

    def _eval(self, node, local, depth):
        if isinstance(node, ast.Constant):
            return _number(node.value)
        if isinstance(node, ast.Name):
            return local[node.id] if node.id in local else self.parameter(node.id)
        if isinstance(node, ast.Attribute) and isinstance(node.value,ast.Name) and node.value.id == 'cmath' and node.attr == 'pi':
            return _number(math.pi)
        if isinstance(node, ast.Attribute) and node.attr in ('real','imag'):
            value = self._eval(node.value,local,depth)
            return _number(value.real if node.attr=='real' else value.imag)
        if isinstance(node, ast.UnaryOp) and isinstance(node.op,(ast.UAdd,ast.USub)):
            value = self._eval(node.operand,local,depth)
            return value if isinstance(node.op,ast.UAdd) else -value
        if isinstance(node, ast.BinOp) and isinstance(node.op,(ast.Add,ast.Sub,ast.Mult,ast.Div,ast.Pow)):
            a,b = self._eval(node.left,local,depth),self._eval(node.right,local,depth)
            try:
                if isinstance(node.op,ast.Add): value=a+b
                elif isinstance(node.op,ast.Sub): value=a-b
                elif isinstance(node.op,ast.Mult): value=a*b
                elif isinstance(node.op,ast.Div): value=a/b
                else:
                    if b.imag != 0 or abs(b.real) > 16:
                        raise ValueError('selected power exponent outside bounded scalar dialect')
                    value=a**b.real
            except (ZeroDivisionError, OverflowError) as exc:
                raise ValueError('undefined selected scalar expression') from exc
            return _number(value)
        if isinstance(node, ast.Call) and not node.keywords:
            args = [self._eval(x,local,depth) for x in node.args]
            funcs = {k:getattr(cmath,k) for k in ('sqrt','sin','cos','tan','asin','acos','atan','exp','log')}
            name = node.func.id if isinstance(node.func,ast.Name) else None
            if name == 'complex' and len(args) == 2 and all(x.imag==0 for x in args):
                return _number(complex(args[0].real,args[1].real))
            if isinstance(node.func,ast.Attribute) and isinstance(node.func.value,ast.Name) and node.func.value.id=='cmath':
                name = node.func.attr
                if name in funcs and len(args)==1:
                    return _number(funcs[name](args[0]))
            # Released Function declarations may use imported cmath names.
            if name in funcs and name not in self.functions and len(args)==1:
                return _number(funcs[name](args[0]))
            if isinstance(node.func,ast.Attribute) and node.func.attr=='conjugate' and not args:
                return _number(self._eval(node.func.value,local,depth).conjugate())
            if name in self.functions:
                row = self.functions[name]['attrs']; names = _literal(row['arguments'])
                if (not isinstance(names,(list,tuple)) or len(names)!=len(args) or len(set(names))!=len(names)
                        or any(not isinstance(n,str) or not re.fullmatch('[A-Za-z][A-Za-z0-9_]*',n) for n in names)):
                    raise ValueError('finite canonical Function arguments required')
                return self.expression(_literal(row['expression']),dict(zip(names,args)),depth+1)
        raise ValueError('unsupported scalar source expression; supply a qualified consumer for this function/dialect')


def _linear(structure, family):
    """Exact supported matrix tensors, allowing finite real linear combinations."""
    def dump(text): return ast.dump(ast.parse(text,mode='eval').body)
    if family == 'SFF':
        basis = {'Identity(2,1)':(1,1), 'ProjM(2,1)':(1,0), 'ProjP(2,1)':(0,1), 'Gamma5(2,1)':(-1,1)}
    else:
        basis = {'Gamma(3,2,1)':(1,1), 'Gamma(3,2,-1)*ProjM(-1,1)':(1,0),
                 'Gamma(3,2,-1)*ProjP(-1,1)':(0,1), 'Gamma(3,2,-1)*Gamma5(-1,1)':(-1,1)}
    known = {dump(k):v for k,v in basis.items()}
    def scalar(node):
        if isinstance(node,ast.Constant) and type(node.value) in (int,float): return float(node.value)
        if isinstance(node,ast.UnaryOp) and isinstance(node.op,(ast.UAdd,ast.USub)):
            return scalar(node.operand)*(1 if isinstance(node.op,ast.UAdd) else -1)
        if isinstance(node,ast.BinOp) and isinstance(node.op,ast.Div): return scalar(node.left)/scalar(node.right)
        raise ValueError('not a finite numeric matrix coefficient')
    def walk(node):
        if ast.dump(node) in known: return known[ast.dump(node)]
        if isinstance(node,ast.UnaryOp) and isinstance(node.op,(ast.UAdd,ast.USub)):
            a=walk(node.operand); sign=1 if isinstance(node.op,ast.UAdd) else -1
            return tuple(sign*x for x in a)
        if isinstance(node,ast.BinOp) and isinstance(node.op,(ast.Add,ast.Sub)):
            a,b=walk(node.left),walk(node.right); sign=1 if isinstance(node.op,ast.Add) else -1
            return tuple(x+sign*y for x,y in zip(a,b))
        if isinstance(node,ast.BinOp) and isinstance(node.op,ast.Mult):
            def factors(part):
                if isinstance(part,ast.BinOp) and isinstance(part.op,ast.Mult):
                    return factors(part.left)+factors(part.right)
                return [part]
            factor=1.; matrices=[]
            for part in factors(node):
                try: factor*=scalar(part)
                except ValueError: matrices.append(part)
            if not matrices or not math.isfinite(factor):
                raise ValueError('finite nonempty matrix product required')
            matrix=matrices[0]
            for part in matrices[1:]: matrix=ast.BinOp(left=matrix,op=ast.Mult(),right=part)
            if ast.dump(matrix) not in known:
                raise ValueError('matrix product ordering/contraction is outside exact supported basis')
            return tuple(factor*x for x in known[ast.dump(matrix)])
        raise ValueError('unsupported momentum/tensor/Lorentz ordering; no inferred basis substitution')
    if not isinstance(structure,str) or len(structure)>4096: raise ValueError('bounded Lorentz source string required')
    node=ast.parse(structure,mode='eval').body
    if len(list(ast.walk(node)))>512: raise ValueError('bounded Lorentz syntax required')
    try: result=walk(node)
    except (ZeroDivisionError,OverflowError) as exc: raise ValueError('undefined Lorentz coefficient') from exc
    if any(not math.isfinite(x) for x in result): raise ValueError('nonfinite Lorentz projection')
    return result


def tree_reference(family, masses, coefficients, color, identical=False):
    """Unpolarized on-shell two-body width, vertex coefficient includes its i.

No supplied total DECAY width is replaced; this is one selected tree channel.
Coefficient mapping has removed the global i for the HEPTAPOD coordinates.
"""
    m,a,b = [_real(x,'on-shell mass',True) for x in masses]
    if m <= a+b: raise ValueError('strictly open tree channel required; no off-shell continuation')
    if type(color) is not int or color not in (1,3): raise ValueError('explicit final-color multiplicity required')
    if family=='SSS':
        if set(coefficients)!={'g'} or color!=1: raise ValueError('SSS singlet coefficient required')
        spin_sum=abs(_number(coefficients['g']))**2; initial=1; symmetry=2 if identical else 1
    elif family in ('SFF','VFF'):
        if set(coefficients)!={'gL','gR'} or identical: raise ValueError('distinct Dirac chiral coordinates required')
        left,right=[_number(coefficients[k]) for k in ('gL','gR')]
        norm=abs(left)**2+abs(right)**2; mixed=(left*right.conjugate()).real
        if family=='SFF':
            spin_sum=norm*(m*m-a*a-b*b)-4*mixed*a*b; initial=1
        else:
            spin_sum=norm*(2*m*m-a*a-b*b-(a*a-b*b)**2/(m*m))+12*mixed*a*b; initial=3
        symmetry=1
    else: raise ValueError('served tree reference families are SSS/SFF/VFF')
    if not math.isfinite(spin_sum) or spin_sum<0: raise ValueError('negative/nonfinite trace witness; no clipping')
    momentum=math.sqrt((m*m-(a+b)**2)*(m*m-(a-b)**2))/(2*m)
    width=momentum/(8*math.pi*m*m)*spin_sum*color/initial/symmetry
    if not math.isfinite(width): raise ValueError('nonfinite tree reference')
    return {'partial_width_GeV':width,'spin_polarization_sum_without_color':spin_sum,'initial_spin_average':initial,
            'final_color_sum':color,'identical_final_symmetry_divisor':symmetry,'three_masses_GeV':list(masses),
            'supplied_total_width_replaced':False,'native_amplitude_evaluated':False,'complete_total_width':False}


def _capture(task, base):
    from ravel.physics import diagrammatica_code as code
    code.validate(task)
    path=custody._regular(task['input'],base); raw=path.read_bytes()
    from ravel.workflow.state_io import _unique
    def nonfinite(value): raise ValueError('nonfinite request JSON')
    doc=json.loads(raw.decode('utf-8'),object_pairs_hook=_unique,parse_constant=nonfinite)
    if raw!=path.read_bytes(): raise ValueError('request changed during capture')
    custody._keys(doc,('schema_version','operation','units','source','model_tree','parameter_card','parent_pdg','vertex',
                       'release','backend_files','max_seconds'),'UFO decay request')
    if (type(doc['schema_version']) is not int or doc['schema_version']!=2 or doc['operation']!=OPERATION
            or doc['units']!='GeV' or not isinstance(doc['source'],str) or not doc['source'].strip()
            or type(doc['parent_pdg']) is not int or not 0<doc['parent_pdg']<1000000000
            or not isinstance(doc['vertex'],str) or not re.fullmatch('[A-Za-z][A-Za-z0-9_]{0,63}',doc['vertex'])
            or doc['release']!=code.RELEASE or type(doc['max_seconds']) is not int or not 1<=doc['max_seconds']<=60):
        raise ValueError('explicit schema2, source, parent, vertex, GeV, inspected release and bounded construction time required')
    model,manifest,paths=custody._tree(doc['model_tree'],path.parent)
    card=custody._pin(doc['parameter_card'],path.parent)
    custody._keys(doc['backend_files'],code.BACKEND,'exact inspected backend closure')
    backend=[]
    for rel,digest in code.BACKEND.items():
        if doc['backend_files'][rel].get('sha256')!=digest: raise ValueError('only exact inspected HEPTAPOD backend admitted')
        backend.append(custody._pin(doc['backend_files'][rel],path.parent))
    captured={str(p):p.read_bytes() for p in [path,manifest,*paths,card,*backend]}
    if sum(map(len,captured.values()))>MAX_BYTES: raise ValueError('UFO decay source closure exceeds16MiB')
    if captured[str(path)]!=raw or hashlib.sha256(captured[str(card)]).hexdigest()!=doc['parameter_card']['sha256']:
        raise ValueError('declared source/card changed before captured validation')
    for name in FILES:
        if str(model/name) not in captured: raise ValueError('missing source module '+name)
    # A second source census verifies the captured whole-tree population, not only selected files.
    declared=json.loads(captured[str(manifest)].decode('utf-8'),object_pairs_hook=_unique,parse_constant=nonfinite)['files']
    for rel,backend_path in zip(code.BACKEND,backend):
        if hashlib.sha256(captured[str(backend_path)]).hexdigest()!=code.BACKEND[rel]:
            raise ValueError('captured HEPTAPOD backend changed before construction')
    if {p.relative_to(model).as_posix():hashlib.sha256(captured[str(p)]).hexdigest() for p in paths}!=declared:
        raise ValueError('captured UFO tree differs from complete declared bytes')
    return doc,path,model,card,captured


def _compile(doc,path,model,card,captured):
    tables={name:_records(captured[str(model/name)].decode('utf-8'),factory) for name,factory in FILES.items()}
    params=tables['parameters.py']; functions=tables['function_library.py']; ext={}
    for key,row in params.items():
        attrs=row['attrs']
        if _literal(attrs['nature'])=='external':
            if _literal(attrs['type'])!='real': raise ValueError('scalar real external card parameters required')
            block,codes=_literal(attrs['lhablock']),_literal(attrs['lhacode'])
            if not isinstance(block,str) or not re.fullmatch('[A-Za-z][A-Za-z0-9_]*',block) or not isinstance(codes,list) or not codes or any(type(n) is not int or n<=0 for n in codes):
                raise ValueError('canonical external card address required')
            address=(block.lower(),tuple(codes))
            if address in ext: raise ValueError('duplicate source external address')
            ext[address]=key
    supplied=card_values(captured[str(card)].decode('utf-8'))
    if not ext or set(supplied)!=set(ext): raise ValueError('supplied card must cover exactly every external UFO address; no source default substitution')
    evaluator=Expressions(params,functions,supplied)
    particles={}
    for key,row in tables['particles.py'].items():
        if 'anti_of' in row:
            original=particles[row['anti_of']]
            if original['name']==original['antiname']: raise ValueError('self-conjugate anti() declaration unsupported')
            particles[key]={**original,'name':original['antiname'],'antiname':original['name'],'pdg':-original['pdg'],
                'charge':-original['charge'],'color':-original['color'] if abs(original['color']) in (3,6) else original['color'],
                'line':row['line'],'anti_of':row['anti_of']}
        else:
            a=row['attrs']; q=_numeric_literal(a['charge'])
            particles[key]={'name':_literal(a['name']),'antiname':_literal(a['antiname']),'pdg':_literal(a['pdg_code']),
                'spin':_literal(a['spin']),'color':_literal(a['color']),'charge':_real(q,'charge'),
                'mass':_ref(a['mass'],'Param'),'width':_ref(a['width'],'Param'),'line':row['line'],
                'ghost':_literal(a['GhostNumber']) if 'GhostNumber' in a else 0,
                'goldstone':_literal(a['goldstoneboson']) if 'goldstoneboson' in a else False,
                'custom_propagator':'propagator' in a}
        if (type(particles[key]['spin']) is not int or type(particles[key]['color']) is not int
                or not isinstance(particles[key]['name'],str) or not particles[key]['name']
                or not isinstance(particles[key]['antiname'],str) or not particles[key]['antiname']):
            raise ValueError('typed integer spin/color and literal nonempty particle/anti names required')
    pdgs=[p['pdg'] for p in particles.values()]
    if any(type(n) is not int or n==0 for n in pdgs) or len(set(pdgs))!=len(pdgs): raise ValueError('unique nonzero signed particle PDGs required')
    if doc['vertex'] not in tables['vertices.py']: raise ValueError('selected UFO vertex is absent')
    vertex=tables['vertices.py'][doc['vertex']]; a=vertex['attrs']
    if not isinstance(a['particles'],ast.List) or len(a['particles'].elts)!=3: raise ValueError('selected vertex must have exactly three source legs')
    leg_names=[_ref(n,'P') for n in a['particles'].elts]
    try: legs=[particles[n] for n in leg_names]
    except KeyError as exc: raise ValueError('unresolved selected particle reference') from exc
    if legs[2]['pdg']!=doc['parent_pdg'] or legs[2]['name']!=legs[2]['antiname'] or legs[2]['color']!=1 or legs[2]['charge']!=0:
        raise ValueError('supported source ordering puts a neutral self-conjugate color-singlet parent at leg3; no inferred crossing/permutation')
    if any(p['ghost']!=0 or p['goldstone'] is not False or p['custom_propagator'] for p in legs): raise ValueError('selected ghost/Goldstone/custom-propagator fields need a different qualified consumer')
    spins=[p['spin'] for p in legs]
    if spins==[1,1,1]:
        family='SSS'; color=1
        if any(p['name']!=p['antiname'] or p['color']!=1 or p['charge']!=0 for p in legs): raise ValueError('only neutral self-conjugate singlet SSS served')
    elif spins in ([2,2,1],[2,2,3]):
        family='SFF' if spins[2]==1 else 'VFF'
        anti,particle=legs[:2]
        if (anti['pdg']!=-particle['pdg'] or particle['pdg']<=0 or anti['name']!=particle['antiname']
                or anti['antiname']!=particle['name'] or particle['name']==particle['antiname']
                or anti['mass']!=particle['mass'] or anti['width']!=particle['width'] or anti['charge']!=-particle['charge']):
            raise ValueError('source leg1 anti/leg2 same-species Dirac pair with exact conjugate properties required; Majorana/flavor change unserved')
        if [anti['color'],particle['color']]==[1,1]: color=1
        elif [anti['color'],particle['color']]==[-3,3]: color=3
        else: raise ValueError('only singlet or triplet Dirac color pair served')
    else: raise ValueError('selected source spins outside SSS/SFF/VFF capability')
    expected_color='1' if color==1 else 'Identity(1,2)'
    if _literal(a['color'])!=[expected_color]: raise ValueError('exact single canonical color basis required; no inferred multiplicity')
    if not isinstance(a['lorentz'],ast.List) or not a['lorentz'].elts or not isinstance(a['couplings'],ast.Dict): raise ValueError('explicit complete selected vertex tensor/coupling population required')
    tensors=[_ref(n,'L') for n in a['lorentz'].elts]
    rows=[];coefficients={'g':0j} if family=='SSS' else {'gL':0j,'gR':0j}; seen=set()
    for key,coupling in zip(a['couplings'].keys,a['couplings'].values):
        index=_literal(key)
        if (not isinstance(index,tuple) or len(index)!=2 or any(type(n) is not int for n in index)
                or index in seen or index[0]!=0 or not 0<=index[1]<len(tensors)):
            raise ValueError('unique valid complete selected color/Lorentz indices required')
        seen.add(index);name=_ref(coupling,'C');tensor=tensors[index[1]]
        try: tensor_attrs=tables['lorentz.py'][tensor]['attrs'];coupling_attrs=tables['couplings.py'][name]['attrs']
        except KeyError as exc: raise ValueError('unresolved selected tensor/coupling reference') from exc
        if _literal(tensor_attrs['spins'])!=spins: raise ValueError('Lorentz spin positions disagree with selected source legs')
        if set(tensor_attrs)!={'name','spins','structure'}: raise ValueError('selected form factor or extra Lorentz semantics unserved')
        if set(coupling_attrs)!={'name','value','order'}:
            raise ValueError('selected noncanonical/counterterm coupling attributes need a qualified consumer')
        order=_literal(coupling_attrs['order'])
        if not isinstance(order,dict) or any(not isinstance(k,str) or type(v) is not int or v<0 for k,v in order.items()):
            raise ValueError('explicit finite nonnegative source coupling orders required')
        expression=_literal(coupling_attrs['value'])
        value=evaluator.expression(expression)
        if family=='SSS':
            if _literal(tensor_attrs['structure'])!='1': raise ValueError('SSS nonderivative unit tensor required')
            weights=(1,);coefficients['g']+=value/1j
        else:
            weights=_linear(_literal(tensor_attrs['structure']),family)
            for coordinate,weight in zip(('gL','gR'),weights): coefficients[coordinate]+=value*weight/1j
        rows.append({'source_index':list(index),'lorentz':tensor,'structure':_literal(tensor_attrs['structure']),
            'coupling':name,'source_coupling_expression':expression,'evaluated_source_coefficient':_pair(value),
            'chiral_projection_weights':list(weights),'coupling_order':_literal(coupling_attrs['order'])})
    if {i for _,i in seen}!=set(range(len(tensors))): raise ValueError('selected Lorentz population has an unbound coupling row')
    if not any(abs(v)>0 for v in coefficients.values()): raise ValueError('selected supplied point has zero vertex; no nonvacuous open-decay claim')
    masses=[_real(evaluator.parameter(p['mass']),'physical on-shell mass',True) for p in [legs[2],*legs[:2]]]
    widths=[_real(evaluator.parameter(p['width']),'supplied total width',True) for p in [legs[2],*legs[:2]]]
    if family in ('SFF','VFF') and masses[1]!=masses[2]: raise ValueError('same-species conjugate masses differ')
    identical=family=='SSS' and leg_names[0]==leg_names[1]
    reference=tree_reference(family,masses,coefficients,color,identical)
    parent={'label':'X','spin':0 if spins[2]==1 else 1,'mass':masses[0],'antiparticle':False,'self_conjugate':True}
    if family=='SSS':
        daughters=[{'label':'s' if identical or i==0 else 't','spin':0,'mass':masses[i+1],'antiparticle':False,'self_conjugate':True} for i in range(2)]
        vertex_doc={'type':'scalar','coupling':'g'}
    else:
        daughters=[{'label':'f','spin':.5,'mass':masses[2],'antiparticle':False,'self_conjugate':False},
                   {'label':'fbar','spin':.5,'mass':masses[1],'antiparticle':True,'self_conjugate':False}]
        vertex_doc={'type':'chiral','coupling':{'gL':'gL','gR':'gR'}}
    pin=lambda p:{'path':str(p),'sha256':hashlib.sha256(captured[str(p)]).hexdigest()}
    compiled={'schema_version':1,'operation':'symbolic_decay_code','units':'GeV','release':doc['release'],'backend_files':deepcopy(doc['backend_files']),
        'diagram':{'initial':[parent],'final':daughters,'vertices':[vertex_doc],'color_factor':color},
        'grounding':[pin(model/n) for n in FILES]+[pin(card)],'vertex_coefficient_definition':
            'Source vertex '+doc['vertex']+' at ordered source legs '+str(leg_names)+'; exact captured tensor basis projected to i*g or i*(gL PL+gR PR), hence coordinate=source coefficient/i. No arbitrary crossing or vertex enumeration.',
        'coupling_dimensions_GeV':{k:1 if family=='SSS' else 0 for k in coefficients},'max_seconds':doc['max_seconds']}
    from ravel.physics import diagrammatica_code as code
    code._diagram(compiled)
    substitutions={**{'mX':_pair(masses[0])},**{k:_pair(v) for k,v in coefficients.items()}}
    for p in daughters: substitutions['m'+p['label']]=_pair(p['mass'])
    details={'family':family,'selected_vertex':doc['vertex'],'vertex_source_line':vertex['line'],'source_leg_symbols':leg_names,
        'source_leg_records':legs,'selected_lorentz_coupling_rows':rows,'selected_parameter_evaluation':evaluator.ledger,
        'external_card_address_count':len(ext),'unconsumed_internal_parameters':sorted(set(params)-set(evaluator.values)-set(ext.values())),
        'supplied_total_widths_GeV':widths,'coefficient_coordinates':{k:_pair(v) for k,v in coefficients.items()},
        'numerical_substitution_coordinates':substitutions,'tree_reference':reference,
        'source_UFO_Python_imported':False,'whole_model_evaluated':False,'whole_model_validity':None}
    return compiled,details


def prepare(task, base):
    """Callable preparation with actual finite source/card expression evaluation."""
    doc,path,model,card,captured=_capture(task,base)
    compiled,details=_compile(doc,path,model,card,captured)
    for name,raw in captured.items():
        if Path(name).read_bytes()!=raw: raise ValueError('scientific source changed during UFO decay preparation')
    if custody.source_tree(model)!=json.loads(captured[str(custody._regular(doc['model_tree']['manifest']['path'],path.parent))].decode('utf-8')):
        raise ValueError('complete model source population changed during UFO decay preparation')
    return compiled,details,captured


def inputs(task, base):
    return [Path(p) for p in prepare(task,base)[2]]


def execution_seconds(task, base):
    return prepare(task,base)[0]['max_seconds']


def _wl_number(value):
    text=format(_real(value,'Wolfram numeric literal'),'.17g')
    return text.replace('e','*^').replace('E','*^')


def _point_script(symbolic, substitutions, aliases):
    """Keep complex conjugation symbolic; never install numerical OwnValues.

    Released same-species aliases are symbolic Set values. Collapse those
    coordinates before constructing the final rules so no rule targets an
    already-aliased mass symbol with a conflicting numerical value.
    """
    coordinates=deepcopy(substitutions)
    for alias,target in aliases.items():
        if alias not in coordinates or target not in coordinates or coordinates[alias]!=coordinates[target]:
            raise ValueError('same-species mass substitution coordinates disagree')
        del coordinates[alias]
    rules=[]
    for name,value in coordinates.items():
        if not re.fullmatch('[A-Za-z][A-Za-z0-9]*',name):raise ValueError('literal generated point coordinate required')
        rules.append(name+' -> Complex['+_wl_number(value['real'])+','+_wl_number(value['imag'])+']')
    tail=('\n(* RAVEL supplied point: fresh symbolic kernel required. Numerical values are substituted only after completed symbolic conjugation and width. *)\n'
          'ravelPointRules = {'+', '.join(rules)+'};\n'
          'ravelAmpSqPoint = N[ampSqKin /. ravelPointRules];\n'
          'ravelWidthPoint = N[width /. ravelPointRules];\n'
          'Print["POINT_NUMERICAL_RESULT[ampSq]: ", ravelAmpSqPoint];\n'
          'Print["POINT_NUMERICAL_RESULT[width_GeV]: ", ravelWidthPoint];\n')
    return symbolic+tail


def run(task, base, output):
    from ravel.physics import diagrammatica_code as code
    from ravel.physics.finite_mc_model import _admit_output
    started=time.monotonic();compiled,details,captured=prepare(task,base)
    out=_admit_output(output)
    if any(Path(p).is_relative_to(out) for p in captured): raise ValueError('output cannot contain scientific inputs')
    request=out/'diagrammatica-compiled-request.json';custody._write(request,compiled)
    backend=code.run({'input':str(request)},out,out/'diagrammatica')
    drift=[]
    for name,raw in captured.items():
        try:
            if Path(name).read_bytes()!=raw:drift.append(name)
        except OSError:drift.append(name)
    # Reconcile the entire source population as well as the individual bytes.
    request_path=custody._regular(task['input'],base)
    source_request=json.loads(captured[str(request_path)].decode('utf-8'))
    model_root=Path(source_request['model_tree']['root'])
    if not model_root.is_absolute():model_root=request_path.parent/model_root
    manifest=custody._regular(source_request['model_tree']['manifest']['path'],request_path.parent)
    try:
        if custody.source_tree(model_root)!=json.loads(captured[str(manifest)].decode('utf-8')):
            drift.append(str(model_root))
    except (OSError,ValueError):drift.append(str(model_root))
    if time.monotonic()-started>compiled['max_seconds']: raise TimeoutError('declared whole construction budget exhausted')
    passed=backend['status']=='passed' and not drift
    report={'schema_version':1,'kind':'ufo_selected_decay_construction','status':'passed' if passed else 'failed','scope':SCOPE,
        'physics_validated':False,'execution_authorized':False,'generated_events':0,'native_calls':0,'model_calls':0,
        'source_pins':[{'path':name,'sha256':hashlib.sha256(raw).hexdigest(),'size':len(raw)} for name,raw in captured.items()],
        'source_drift':drift,'selected_construction':details,'diagrammatica_result':backend,
        'limitations':['Static declared UFO dialect, not arbitrary runtime Python, automatic diagram enumeration or generic crossing.',
            'Only selected neutral singlet, SSS or canonical same-species Dirac SFF/VFF color1/3 one-vertex tree decays.',
            'Every external address is explicitly supplied; selected internal dependencies/couplings are evaluated, not all model interactions.',
            'Tree reference and source-generated scripts are not native FeynCalc/ALOHA agreement, loop/UV/gauge checks or a certified complete total width.',
            'Unpolarized partial-width conventions are explicit; polarized/angle-sensitive crossing and equivalence require independent qualification.']}
    # Preserve exact raw scripts; numerical point construction is a separate derivative.
    if passed:
        derivative=out/'decay-supplied-point.wl'
        derivative.write_text(_point_script((out/'diagrammatica/decay-symbolic.wl').read_text(),
            details['numerical_substitution_coordinates'],backend['same_species_mass_coordinate_identifications']))
        report['supplied_point_substitution_policy']='Unassigned symbolic amplitude/conjugation/kinematics/width first; numerical substitution only in final ampSqKin and width, after same-species mass aliases are collapsed.'
        report['supplied_point_script']={'path':str(derivative),'sha256':custody._hash(derivative),'executed':False}
    custody._write(out/'ufo-decay-construction.json',report)
    return report
