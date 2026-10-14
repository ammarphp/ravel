"""Cold source contracts/readers for the original EasyScan workflow.

Native samplers/engines are never imported here. Raw sampler tables are not
independent collision events, posterior qualification or scientific acceptance.
"""
import configparser
from copy import deepcopy
from fractions import Fraction
import csv,hashlib,json,math,re
import io
from pathlib import Path
from ravel.physics.dataset_query_quantities_core import Capture,keys,text,integer,strict,pin,digest

DATA=Path(__file__).parents[1]/'data/easyscan'
API=DATA/'upstream-api.json'
SCOPE='complete-original-parameter-space-sampling-delivery'
# Extension entries describe native interfaces, never study identities.
METHODS={
    'RANDOM': {'count': True, 'serial': False},
    'GRID': {'count': False, 'serial': False},
    'BESTFIT': {'count': True, 'serial': True},
    'MCMC': {'count': True, 'serial': False},
    'EMCEE': {'count': True, 'serial': True},
    'DYNESTY': {'count': True, 'serial': True},
    'ONEPOINT': {'count': False, 'serial': False},
}
PROGRAMME_STATUSES={'native': {}, 'phasetracer-xsm-a68b': {}}


class ScanInputError(ValueError):
    """A missing supplied input, usable by callers without parsing prose."""
    reason='missing_scan_input'

    def __init__(self, field):
        self.field=field
        super().__init__('missing_scan_input: '+field)


def required(value, field):
    if value is None or value=='' or value==[]:raise ScanInputError(field)
    return value


def emission_bytes(value):
    """Exact state_io.atomic_json serialization, committed before its writer."""
    return (json.dumps(value,indent=2,allow_nan=False)+'\n').encode('utf-8')


class Emitted:
    """Finite owned emissions: intended bytes, immediate and ending reads.

    Reuses the ordinary no-follow bounded descriptor reader. This is a finite
    observation contract, not a pathname lock or universal transient-ABA claim.
    Native mutable scientific files have their separate full output census.
    """
    def __init__(self,root,limit=64*1024**2):
        self.root=Path(root).absolute();self.limit=limit;self.expected={}

    def check(self,path):
        from ravel.workflow.research_cycle import _bounded_source_snapshot
        path=Path(path).absolute();fact=self.expected[path]
        _,raw=_bounded_source_snapshot(path,self.limit)
        if len(raw)!=fact['size'] or hashlib.sha256(raw).hexdigest()!=fact['sha256']:
            raise ValueError('generated output differs from intended bytes: '+str(path))

    def _commit(self,path,raw,replace,register):
        path=Path(path).absolute()
        if not path.is_relative_to(self.root) or path==self.root or '..' in path.parts or any(p.is_symlink() for p in (path,*path.parents)):
            raise ValueError('ordinary emitted member inside owned output required')
        if type(raw) is not bytes or len(raw)>self.limit:raise ValueError('emitted member exceeds bounded reader')
        if path in self.expected:
            if not replace:raise ValueError('single-write emitted member required')
            self.check(path)
        elif path.exists():raise ValueError('fresh emitted member required')
        fact={'path':str(path),'sha256':hashlib.sha256(raw).hexdigest(),'size':len(raw)}
        self.expected[path]=fact
        if register is not None:register(fact)
        path.parent.mkdir(parents=True,exist_ok=True)
        return path,fact

    def bytes(self,path,raw, *, register=None):
        path,fact=self._commit(path,raw,False,register);path.write_bytes(raw);self.check(path);return dict(fact)

    def json(self,path,value,writer, *, replace=False,register=None):
        path,fact=self._commit(path,emission_bytes(value),replace,register)
        writer(path,value);self.check(path);return dict(fact)

    def finish(self):
        for path in self.expected:self.check(path)

    def inventory(self):return [dict(self.expected[p]) for p in sorted(self.expected)]


def prior_coordinate(x,parameter):
    """Released statfun.prior scalar law, with its operation order retained.

    Executed EMCEE exports additionally retain the actual native Prior results,
    because NumPy scalar exponentiation need not round like Python's pow.
    """
    fields=parameter['fields'];kind=fields[1].upper()
    if kind=='FLAT':result=x*(float(fields[3])-float(fields[2]))+float(fields[2])
    elif kind=='LOG':
        maximum=math.log10(float(fields[3]));minimum=math.log10(float(fields[2]))
        result=10.0**(x*(maximum-minimum)+minimum)
    elif kind=='FIXED':result=float(fields[2])
    else:raise ValueError('unadmitted native Prior')
    if not math.isfinite(result):raise ValueError('nonfinite native Prior projection')
    return result


def relative(value):
    text(value,'literal relative path');p=Path(value)
    if p.is_absolute() or p.as_posix()!=value or any(v in ('','..','.') for v in p.parts):raise ValueError('ordinary relative workspace path required')
    return value


def config(value):
    fields=('schema_version','operation','study_id','question','ini','framework','workspace','programmes','runtime','resources','report','continuation','returned')
    if type(value) is not dict:raise ValueError('supplied scan contract required')
    for field in fields:
        if field not in value:raise ScanInputError(field)
    keys(value,fields,'EasyScan operation')
    if type(value['schema_version']) is not int or value['schema_version']!=2 or value['operation'] not in ('run','read-returned','continue-native'):raise ValueError('supported EasyScan operation2 required')
    text(value['study_id'],'supplied study identity')
    pin(value['question']);pin(value['ini'])
    for name in ('framework','workspace'):
        required(value[name],name)
        keys(value[name],('root','manifest'),name+' tree');text(value[name]['root']);pin(value[name]['manifest'])
    r=value['resources'];keys(r,('max_seconds','max_ram_mib','max_evaluations','max_programme_calls','max_output_bytes','max_output_members','max_copy_bytes'),'finite EasyScan resources')
    for k,lo,hi in (('max_seconds',1,3600),('max_ram_mib',512,8192),('max_evaluations',1,100000),('max_programme_calls',1,100000),('max_output_bytes',1,4*1024**3),('max_output_members',1,100000),('max_copy_bytes',1,4*1024**3)):integer(r[k],lo,hi,k)
    required(value['programmes'],'programmes')
    if type(value['programmes']) is not list or len(value['programmes'])>64:raise ValueError('complete ordered programme contracts required')
    names=[]
    for p in value['programmes']:
        keys(p,('section','inputs','outputs','intermediates','mutable_paths','units','status'),'programme')
        if not re.fullmatch(r'program[1-9][0-9]*',p['section']):raise ValueError('numeric native programme section required')
        names.append(p['section'])
        for key in ('inputs','outputs','intermediates','mutable_paths'):
            if type(p[key]) is not list or len(set(p[key]))!=len(p[key]):raise ValueError('complete distinct programme paths required')
            for path in p[key]:relative(path)
        if type(p['units']) is not dict:raise ValueError('explicit per-output units required')
        for k,u in p['units'].items():text(k);text(u)
        if p['status'] not in PROGRAMME_STATUSES:raise ValueError('source-defined programme status required')
    if names!=sorted(set(names),key=lambda x:int(x[7:])):raise ValueError('native ordered programme population differs')
    if value['runtime'] is not None:
        rt=value['runtime'];keys(rt,('python','trees','site_roots','versions'),'native runtime');pin(rt['python'])
        if type(rt['trees']) is not list or not rt['trees'] or type(rt['site_roots']) is not list or type(rt['versions']) is not dict:raise ValueError('complete runtime/versions required')
        for d in rt['trees']:keys(d,('root','manifest'),'runtime tree');text(d['root']);pin(d['manifest'])
        for s in rt['site_roots']:text(s)
        for k,v in rt['versions'].items():text(k);text(v)
    if (value['operation']=='continue-native')!=(value['continuation'] is not None):raise ValueError('explicit native continuation required')
    if (value['operation']=='read-returned')!=(value['returned'] is not None):raise ValueError('exact returned-native manifest required')
    if value['continuation'] is not None:pin(value['continuation'])
    if value['returned'] is not None:pin(value['returned'])
    report=value['report'];required(report,'report')
    keys(report,('format','path','table'),'selected table export')
    if report['format'] not in ('json','csv'):raise ValueError('supported table export format required')
    relative(report['path']);relative(report['table'])
    return deepcopy(value)


def ini(raw,doc):
    parser=configparser.ConfigParser(strict=True)
    parser.read_string(raw.decode('utf-8'))
    if 'scan' not in parser:raise ValueError('original scan section missing')
    canonical=['Scan method','Result folder name','Input parameters','Number of points','Parallel threads','Parallel folder','MCMC walkers','Random seed','Program name','Execute command','Command path','Input file','Input variable','Output file','Output variable','Time limit in minute','Command executor','Gaussian','Histogram','Scatter','Color','Contour']
    names={v.lower():v for v in canonical}
    projection={s:{names.get(k,k):v for k,v in parser.items(s)} for s in parser.sections()}
    def get(k):return projection['scan'].get(k)
    method=required(get('Scan method'),'scan.Scan method').upper()
    if method not in METHODS:raise ValueError('unadmitted native method')
    result=relative(required(get('Result folder name'),'scan.Result folder name'))
    params=[]
    for row in required(get('Input parameters'),'scan.Input parameters').splitlines():
        fields=[s.strip() for s in row.split(',')]
        if len(fields)<3 or not fields[0] or fields[1].lower() not in ('flat','log','fixed'):raise ValueError('explicit native parameter/prior fields required')
        try:nums=[float(v) for v in fields[2:]]
        except ValueError:raise ValueError('numeric native parameter fields required') from None
        if any(not math.isfinite(v) for v in nums):raise ValueError('finite native parameter fields required')
        params.append({'name':fields[0],'prior':fields[1].lower(),'fields':fields,'numeric':nums})
    if not params or len({p['name'] for p in params})!=len(params):raise ValueError('complete unique parameters required')
    sampled=[p for p in params if p['prior']!='fixed']
    count=int(get('Number of points')) if get('Number of points') is not None else None
    if METHODS[method]['count']:required(count,'scan.Number of points')
    if count is not None and count<1:raise ValueError('positive native count required')
    workers=int(required(get('Parallel threads'),'scan.Parallel threads'))
    if workers<1 or workers>64 or METHODS[method]['serial'] and workers!=1:raise ValueError('source-admitted native workers required')
    parallel=relative(required(get('Parallel folder'),'scan.Parallel folder')) if workers>1 else None
    grid=None
    if method=='GRID':
        if any(len(p['fields'])!=5 or not p['numeric'][2].is_integer() or p['numeric'][2]<1 for p in sampled):raise ValueError('explicit native grid interval required')
        grid=math.prod(int(p['numeric'][2])+1 for p in sampled)
    if method in ('MCMC','EMCEE') and any(len(p['fields'])!=6 for p in sampled):raise ValueError('explicit source initialization/interval required')
    walkers=int(required(get('MCMC walkers'),'scan.MCMC walkers')) if method=='EMCEE' else None
    if method=='EMCEE' and walkers<2*len(sampled):raise ValueError('native ensemble walker bound differs')
    progs=sorted([s for s in projection if s.startswith('program')],key=lambda s:int(s[7:]))
    if progs!=[p['section'] for p in doc['programmes']]:raise ValueError('whole native programme population differs')
    required(progs,'programmes')
    for name,p in zip(progs,doc['programmes']):
        d=projection[name]
        required(d.get('Execute command'),name+'.Execute command')
        required(d.get('Input variable'),name+'.Input variable')
        required(d.get('Output variable'),name+'.Output variable')
        if not d.get('Execute command') or 'Time limit in minute' in d or d.get('Command executor','').lower() not in ('','os.system'):raise ValueError('detached/unknown native executor unavailable; original same-group branch required')
        if d.get('Command path','').rstrip('/') not in ('','.'):relative(d['Command path'].rstrip('/'))
        for field,key in (('Input file','inputs'),('Output file','outputs')):
            paths=[]
            for row in d.get(field,'').splitlines():
                parts=[v.strip() for v in row.split(',')]
                if not row.strip():continue
                if len(parts)!=2:raise ValueError('complete original programme file mapping required')
                paths.append(relative(parts[1]))
            if paths!=p[key]:raise ValueError('original native file mapping differs')
        mapped=[v.split(',')[0].strip() for v in d.get('Output variable','').splitlines() if v.strip()]
        if set(mapped)!=set(p['units']):raise ValueError('every original output requires its explicit supplied unit')
    required_trials=count if method=='RANDOM' else grid if method=='GRID' else None
    if required_trials is not None and doc['resources']['max_evaluations']<required_trials:raise ValueError('declared evaluation ceiling cannot admit the complete original trial population')
    def gaussian_rows(value):
        result=[]
        for row in value.splitlines():
            fields=[v.strip() for v in row.split(',')]
            if len(fields)!=3:raise ValueError('complete source Gaussian row required')
            try:result.append((fields[0],Fraction(fields[1]),Fraction(fields[2])))
            except (ValueError,ZeroDivisionError):raise ValueError('finite numeric Gaussian source convention required') from None
        return result
    if doc['operation']=='continue-native' and method!='MCMC':raise ValueError('only native final-row MCMC continuation is supported; no sampler/RNG restoration')
    figures=[]
    plot_rules={'histogram':(1,'Histogram'),'scatter':(2,'Scatter'),'color':(3,'Color'),'contour':(3,'Contour')}
    for key,value in projection.get('plot',{}).items():
        if key.lower() not in plot_rules:raise ValueError('unknown original plot directive')
        n,prefix=plot_rules[key.lower()]
        for row in value.splitlines():
            fields=[s.strip() for s in row.split(',')]
            if len(fields) not in (n,n+1) or any(not v for v in fields):raise ValueError('complete original plot fields required')
            name=(fields[-1] if len(fields)==n+1 else prefix+'_'+'_'.join(fields))+'.png'
            relative(name);figures.append(name)
    if len(set(figures))!=len(figures):raise ValueError('native figure name collision')
    gaussians=gaussian_rows(projection.get('constraint',{}).get('Gaussian',''))
    if any(sigma<=0 for _,_,sigma in gaussians):raise ValueError('positive Gaussian uncertainty required')
    discrepancies=[]
    for p in sampled:
        if method in ('MCMC','EMCEE') and len(p['numeric'])>=4 and not p['numeric'][0]<=p['numeric'][-1]<=p['numeric'][1]:discrepancies.append({'parameter':p['name'],'kind':'original_initial_outside_prior','values':p['numeric']})
    return {'projection':projection,'method':method,'parameters':params,'sampled_parameters':len(sampled),'point_setting':count,'workers':workers,'parallel_folder':parallel,'result_folder':result,'grid_population':grid,'walkers':walkers if method=='EMCEE' else None,'chain_slots':walkers*math.ceil(count/walkers) if method=='EMCEE' else None,'figures':figures,'discrepancies':discrepancies,'seed':get('Random seed'),'rng_scope':'Python random only; native sampler/worker independent streams unknown'}


def table(raw):
    lines=raw.decode('utf-8').splitlines()
    if not lines:raise ValueError('empty native scientific table')
    header=next(csv.reader([lines[0]]));rows=[]
    if len(header)!=len(set(header)) or any(not v for v in header):raise ValueError('unique complete native columns required')
    for ordinal,line in enumerate(lines[1:],1):
        if not line.strip():rows.append({'ordinal':ordinal,'raw':line,'status':'blank','fields':[]});continue
        fields=next(csv.reader([line]));status='parsed' if len(fields)==len(header) else 'wrong_width';values=[]
        for f in fields:
            try:v=float(f)
            except ValueError:values.append({'raw':f,'value':None,'status':'literal_or_missing'});continue
            values.append({'raw':f,'value':v if math.isfinite(v) else None,'status':'finite' if math.isfinite(v) else 'native_nonfinite'})
        rows.append({'ordinal':ordinal,'raw':line,'status':status,'fields':values})
    return {'columns':header,'rows':rows,'raw_data_row_count':len(lines)-1,'malformed_rows':[r['ordinal'] for r in rows if r['status']=='wrong_width'],'nonfinite_rows':[r['ordinal'] for r in rows if any(v['status']=='native_nonfinite' for v in r['fields'])]}


def export_table(result, out, emitted):
    """Export exactly the requested table, retaining lexemes and invalid rows."""
    if 'report' not in result:raise ScanInputError('report')
    report=result['report'];path=Path(out)/relative(report['path'])
    tables=(result.get('delivery') or {}).get('tables',{})
    if report['table'] not in tables:raise ScanInputError('report.table')
    selected=tables[report['table']]
    if report['format']=='json':
        from ravel.workflow.state_io import atomic_json
        emitted.json(path,selected,atomic_json)
    elif report['format']=='csv':
        stream=io.StringIO(newline='');writer=csv.writer(stream,lineterminator='\n')
        writer.writerow(selected['columns'])
        for row in selected['rows']:stream.write(row['raw']+'\n')
        emitted.bytes(path,stream.getvalue().encode('utf-8'))
    else:raise ValueError('supported table export format required')
    return {'format':report['format'],'file':report['path'],'table':report['table']}


def dynesty_weights(parsed):
    cols=parsed['columns'];need=('log_likelihood','log_weight','log_evidence')
    if cols[:3]!=list(need) or parsed['malformed_rows'] or not parsed['rows']:raise ValueError('complete native Dynesty table required')
    def column(name):return [r['fields'][cols.index(name)]['value'] for r in parsed['rows']]
    lw=[r['fields'][cols.index('log_weight')]['value'] if r['fields'][cols.index('log_weight')]['value'] is not None else float('-inf') if r['fields'][cols.index('log_weight')]['raw'].lower()=='-inf' else None for r in parsed['rows']]
    lz=column('log_evidence');final=lz[-1]
    if final is None or any(v is None for v in lw):return {'status':'unavailable_nonfinite','final_logz':final,'raw_table_retained':True}
    differences=[v-final for v in lw]
    try:weights=[math.exp(v) for v in differences];total=math.fsum(weights)
    except OverflowError:return {'status':'unavailable_overflow','final_logz':final,'raw_table_retained':True}
    if not math.isfinite(total) or total<=0:return {'status':'unavailable_weight_sum','final_logz':final,'raw_table_retained':True}
    return {'status':'diagnostic','final_logz':final,'weights_using_final_logz':weights,'weight_sum':total,'separate_normalized_weights':[v/total for v in weights],'absolute_evidence_qualified':False}


def phase_status(raw):
    fields=raw.decode().split()
    if len(fields)<9:raise ValueError('complete source PhaseTracer output missing')
    nums=[float(s) for s in fields]
    if any(not math.isfinite(s) for s in nums):raise ValueError('finite PhaseTracer raw fields required')
    code=nums[3];mapping={'-100':'numerical_ewsb_failure','-1':'numerical_phasefinder_failure','-2':'physical_no_transition','-3':'physical_no_qualifying_transition'}
    label=mapping.get(str(int(code))) if code.is_integer() else None
    if code<0 and label is None:raise ValueError('unknown source PhaseTracer status')
    return {'raw_fields':fields,'source_status':label or 'source_transition_payload','code':code,'Tc_and_VEVs':None if code<0 else nums[4:9],'zero_placeholders_are_not_measurements':code<0}
