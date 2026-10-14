"""Finite public-source tool programs; no Python eval, model or native execution.

Programs are prospectively source-reviewed field bindings. They read a pinned
public prompt and policy/API basis only; they are not benchmark answer files.
Numeric arithmetic uses exact rational values. Native truth and scientific
interpretation remain outside the supplied-source calculation.
"""
from copy import deepcopy
from fractions import Fraction
from pathlib import Path
import hashlib,json,re
from ravel.workflow import scientific_artifact as artifact

MAX_STEPS=2048
MAX_ROWS=256

def _keys(value,keys):
    if type(value) is not dict or set(value)!=set(keys):raise ValueError('closed source-tool fields required')

def _number(value):
    if type(value) is bool:raise ValueError('Boolean is not a number')
    if isinstance(value,Fraction):return value
    return artifact._fraction(value)

def _json(value):
    if isinstance(value,Fraction):return str(value)
    if type(value) is list:return [_json(x) for x in value]
    if type(value) is dict:return {k:_json(v) for k,v in value.items()}
    if value is None or type(value) in (str,int,bool):return value
    raise ValueError('finite source scalar required')

def _inputs(text):
    """Exact full instruction and explicitly labelled inline source blocks."""
    result={'instruction':text.split('\nINPUT FILE:',1)[0]}
    pattern=r'^INPUT FILE: ([^\n]+)\n```[^\n]*\n(.*?)^```[ \t]*$'
    for m in re.finditer(pattern,text,re.M|re.S):
        name=m.group(1).strip()
        if name in result:raise ValueError('duplicate labelled public source input')
        result[name]=m.group(2)
    return result

class Program:
    def __init__(self,request,base_dir):
        _keys(request,['schema_version','prompt','policy','bindings','outputs'])
        if type(request['schema_version']) is not int or request['schema_version']!=1:raise ValueError('source tool/v1 required')
        self.base=Path(base_dir).resolve(strict=True);self.request=request;self.steps=0;self.values={};self.observations=[]
        self.prompt,text=artifact._basis_snapshot(request['prompt'],self.base)
        self.policy,policy_text=artifact._basis_snapshot(request['policy'],self.base)
        self.sources=_inputs(text);self.sources['policy']=policy_text
        if type(request['bindings']) is not list or not 0<=len(request['bindings'])<=128:raise ValueError('bounded ordered source bindings required')
        if type(request['outputs']) is not dict or not 1<=len(request['outputs'])<=64:raise ValueError('bounded complete source output fields required')
    def evaluate(self,e,row=None,depth=0):
        self.steps+=1
        if self.steps>MAX_STEPS or depth>24:raise ValueError('source tool step/depth ceiling reached')
        if type(e) is not dict or type(e.get('op')) is not str:raise ValueError('explicit source operation required')
        op=e['op'];go=lambda x,r=row:self.evaluate(x,r,depth+1)
        if op=='ref':
            _keys(e,['op','id'])
            if e['id'] not in self.values:raise ValueError('prior declared source binding required')
            return deepcopy(self.values[e['id']])
        if op=='row':
            _keys(e,['op','field'])
            if type(row) is not dict or e['field'] not in row:raise ValueError('declared selected source row field required')
            return deepcopy(row[e['field']])
        if op=='literal':
            _keys(e,['op','value','source','quote'])
            if e['source'] not in self.sources or type(e['quote']) is not str or not e['quote'] or e['quote'] not in self.sources[e['source']]:raise ValueError('literal policy/value needs exact public source quote')
            if type(e['value']) not in (str,int,bool) and e['value'] is not None:raise ValueError('literal primitive required')
            return e['value']
        if op=='extract':
            _keys(e,['op','source','pattern','group'])
            if e['source'] not in self.sources or type(e['pattern']) is not str or len(e['pattern'])>1024 or type(e['group']) not in (str,int):raise ValueError('bounded explicit source regex required')
            matches=list(re.finditer(e['pattern'],self.sources[e['source']],re.M))
            if len(matches)!=1:raise ValueError('source extraction requires exactly one match')
            value=matches[0].group(e['group']);self.observations.append({'source':e['source'],'pattern':e['pattern'],'span':list(matches[0].span()),'literal':matches[0].group()})
            return value.strip()
        if op=='table':
            _keys(e,['op','source','pattern','row_prefix','columns','region'])
            if e['source'] not in self.sources or type(e['columns']) is not list or not e['columns'] or len(e['columns'])>16:raise ValueError('explicit source row schema required')
            rows=[]
            lines=self.sources[e['source']].splitlines()
            if e['region'] is not None:
                _keys(e['region'],['header'])
                starts=[i for i,line in enumerate(lines) if re.fullmatch(e['region']['header'],line)]
                if len(starts)!=1:raise ValueError('unique public source table header required')
                tail=lines[starts[0]+1:];lines=[]
                for line in tail:
                    if not line.strip():break
                    if re.fullmatch(r'[\s|:-]+',line):continue
                    if not re.match(e['row_prefix'],line):raise ValueError('unparsed row inside complete source table region')
                    lines.append(line)
            for line in lines:
                if not re.match(e['row_prefix'],line):continue
                m=re.fullmatch(e['pattern'],line)
                if m is None or len(m.groups())!=len(e['columns']):raise ValueError('every declared source table row must match the complete column capture')
                rows.append(dict(zip(e['columns'],[x.strip() for x in m.groups()])))
            if not 1<=len(rows)<=MAX_ROWS:raise ValueError('finite nonempty full source row population required')
            self.observations.append({'source':e['source'],'pattern':e['pattern'],'rows':len(rows)})
            return rows
        if op=='list':
            _keys(e,['op','items'])
            if type(e['items']) is not list or len(e['items'])>MAX_ROWS:raise ValueError('bounded explicit list required')
            return [go(x) for x in e['items']]
        if op=='object':
            _keys(e,['op','fields'])
            if type(e['fields']) is not dict or not 1<=len(e['fields'])<=64:raise ValueError('complete finite object fields required')
            return {k:go(v) for k,v in e['fields'].items()}
        if op in ('number','count','not','split'):
            _keys(e,['op','value']);v=go(e['value'])
            if op=='number':return _number(v)
            if op=='count':
                if type(v) is not list:raise ValueError('count requires full declared population')
                return len(v)
            if op=='not':
                if type(v) is not bool:raise ValueError('strict Boolean required')
                return not v
            if type(v) is not str:raise ValueError('source split requires literal string')
            return v.split()
        if op in ('add','sub','mul','div','eq','lt','le','gt','ge','and','or','concat'):
            _keys(e,['op','left','right']);a,b=go(e['left']),go(e['right'])
            if op=='eq':return type(a) is type(b) and a==b
            if op in ('and','or'):
                if type(a) is not bool or type(b) is not bool:raise ValueError('strict Boolean logic required')
                return a and b if op=='and' else a or b
            if op=='concat':
                if type(a) is not str or type(b) is not str:raise ValueError('literal text concatenation required')
                return a+b
            a,b=_number(a),_number(b)
            if op=='add':return a+b
            if op=='sub':return a-b
            if op=='mul':return a*b
            if op=='div':
                if b==0:raise ValueError('undefined division retained as refusal')
                return a/b
            return {'lt':lambda:a<b,'le':lambda:a<=b,'gt':lambda:a>b,'ge':lambda:a>=b}[op]()
        if op=='number_text':
            _keys(e,['op','value']);v=_number(go(e['value']));sign='-' if v<0 else '';n=abs(v.numerator);d=v.denominator;a=b=0
            while d%2==0:a+=1;d//=2
            while d%5==0:b+=1;d//=5
            if d!=1:raise ValueError('nonterminating exact number has no unrounded text token')
            places=max(a,b);digits=str(n*2**(places-a)*5**(places-b)).zfill(places+1)
            return sign+(digits if places==0 else digits[:-places]+'.'+digits[-places:])
        if op=='monotonic_decreasing':
            _keys(e,['op','rows','order_field','value_field']);rows=go(e['rows'])
            if type(rows) is not list or not rows or len(rows)>MAX_ROWS:raise ValueError('complete ordered source population required')
            ordered=sorted(rows,key=lambda r:_number(r[e['order_field']]))
            if len({_number(r[e['order_field']]) for r in ordered})!=len(ordered):raise ValueError('distinct source ordering coordinates required')
            return all(_number(a[e['value_field']])>_number(b[e['value_field']]) for a,b in zip(ordered,ordered[1:]))
        if op=='regex_value':
            _keys(e,['op','value','pattern','group']);v=go(e['value'])
            if type(v) is not str:raise ValueError('literal source text required')
            matches=list(re.finditer(e['pattern'],v))
            if len(matches)!=1:raise ValueError('unique source value match required')
            return matches[0].group(e['group'])
        if op=='unique':
            _keys(e,['op','items']);items=go(e['items']);result=[]
            if type(items) is not list or len(items)>MAX_ROWS:raise ValueError('bounded complete source list required')
            for value in items:
                if not any(type(value) is type(old) and value==old for old in result):result.append(value)
            return result
        if op=='contains':
            _keys(e,['op','value','item']);a,b=go(e['value']),go(e['item'])
            if type(a) is not str or type(b) is not str or not b:raise ValueError('literal source membership required')
            return b in a
        if op=='split_delimited':
            _keys(e,['op','value','separator']);v,sep=go(e['value']),go(e['separator'])
            if type(v) is not str or type(sep) is not str or not sep:raise ValueError('literal source delimiter required')
            values=[part.strip() for part in v.split(sep)]
            if not values or any(not part for part in values) or len(values)>MAX_ROWS:raise ValueError('complete nonempty delimiter population required')
            return values
        if op=='ensure_numeric_census':
            _keys(e,['op','left','right']);a,b=go(e['left']),go(e['right'])
            if type(a) is not list or type(b) is not list or len(a)>MAX_ROWS or len(b)>MAX_ROWS:raise ValueError('declared source populations required')
            a,b=[_number(x) for x in a],[_number(x) for x in b]
            if len(set(a))!=len(a) or len(set(b))!=len(b) or set(a)!=set(b):raise ValueError('actual rows differ from complete intended source population')
            return True
        if op=='replace':
            _keys(e,['op','value','old','new']);v=go(e['value']);a,b=go(e['old']),go(e['new'])
            if type(v) is not str or type(a) is not str or not a or type(b) is not str:raise ValueError('explicit source/policy text replacement required')
            return v.replace(a,b)
        if op in ('filter','map','sort','extreme','all','any'):
            _keys(e,['op','rows','expression']);rows=go(e['rows'])
            if type(rows) is not list or len(rows)>MAX_ROWS:raise ValueError('finite complete row population required')
            pairs=[(r,go(e['expression'],r)) for r in rows]
            if op in ('filter','all','any'):
                if any(type(v) is not bool for _,v in pairs):raise ValueError('row predicate must be Boolean')
                if op=='filter':return [r for r,v in pairs if v]
                return all(v for _,v in pairs) if op=='all' else any(v for _,v in pairs)
            if op=='map':return [v for _,v in pairs]
            if op=='sort':return [r for r,_ in sorted(pairs,key=lambda p:_number(p[1]))]
            if not pairs:raise ValueError('extreme selection needs nonempty admitted rows')
            largest=max(_number(v) for _,v in pairs);selected=[r for r,v in pairs if _number(v)==largest]
            if len(selected)!=1:raise ValueError('source extrema tied; require explicit unique-selection policy')
            return selected[0]
        if op=='field':
            _keys(e,['op','value','field']);v=go(e['value'])
            if type(v) is not dict or e['field'] not in v:raise ValueError('declared object field required')
            return deepcopy(v[e['field']])
        if op=='if':
            _keys(e,['op','condition','then','else']);v=go(e['condition'])
            if type(v) is not bool:raise ValueError('strict Boolean branch required')
            return go(e['then'] if v else e['else'])
        if op=='grid':
            _keys(e,['op','start','stop','step']);a,b,c=(_number(go(e[k])) for k in ('start','stop','step'))
            if c<=0 or b<a or (b-a)/c!=int((b-a)/c):raise ValueError('positive exact inclusive-grid step and divisible endpoint required')
            n=int((b-a)/c)+1
            if n>MAX_ROWS:raise ValueError('inclusive-grid population exceeds bound')
            return [a+i*c for i in range(n)]
        if op=='join':
            _keys(e,['op','items','separator']);items=go(e['items']);sep=go(e['separator'])
            if type(items) is not list or any(type(x) is not str for x in items) or type(sep) is not str:raise ValueError('literal text list join required')
            return sep.join(items)
        raise ValueError('unsupported source operation; implement before admission')
    def run(self):
        for binding in self.request['bindings']:
            _keys(binding,['id','expression'])
            if type(binding['id']) is not str or binding['id'] in self.values:raise ValueError('distinct ordered source binding required')
            self.values[binding['id']]=self.evaluate(binding['expression'])
        result={k:self.evaluate(v) for k,v in self.request['outputs'].items()}
        # Read exact committed bases afresh after calculation, not a new runtime gate.
        artifact._basis(self.request['prompt'],self.base);artifact._basis(self.request['policy'],self.base)
        return {'schema_version':1,'kind':'public_source_tool_facts','facts':_json(result),'prompt':deepcopy(self.request['prompt']),'policy':deepcopy(self.request['policy']),'program_sha256':hashlib.sha256(json.dumps(self.request,sort_keys=True,separators=(',',':')).encode()).hexdigest(),'observations':self.observations,'steps':self.steps,'source_scope':'Literal public source parsing/declared arithmetic and policy bindings only; no native truth, benchmark acceptance or inferred scientific validity.','scientific_acceptance':False,'execution_authorized':False}

def calculate(request,*,base_dir):return Program(request,base_dir).run()


def input_pins(request,*,base_dir):
    Program(request,base_dir)
    return [deepcopy(request[k]) for k in ('prompt','policy')]
