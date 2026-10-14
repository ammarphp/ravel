"""Exact-row released pure-limit chargino decay table, never mixed-MSSM widths.

All3794 rows/13 columns including140 duplicate coordinates remain in the
output. Inclusive nonstrange multihadron and its exclusive subchannels overlap.
"""
import argparse,hashlib,json
from decimal import Decimal,localcontext
from fractions import Fraction
from pathlib import Path
from . import model_tool_bridge as custody,spheno_mssm as support

TABLE=Path(__file__).resolve().parents[1]/'data/spectrum/chargino-decay-2312.08087.dat'
SHA256='ae89a04b3558f2df03d6011f891cf89cb81973aa115553f0703371cd1a1203ad'
COLUMNS=('chargino_mass_GeV','mass_difference_GeV','total_width_GeV','electron_GeV','muon_GeV','single_pion_GeV','inclusive_nonstrange_multihadron_GeV','pi_minus_pi0_GeV','pi_minus_pi_minus_pi_plus_GeV','pi_minus_pi0_pi0_GeV','single_K_GeV','K_pi_GeV','K_2plus_pi_GeV')
SCOPE='source_bound_pure_limit_chargino_decay_table'
require=support.require

def population():
    raw=support.read(TABLE,SHA256);lines=raw.decode('ascii').splitlines(keepends=True);rows=[];coords={}
    for line_no,line in enumerate(lines,1):
        if not line.strip() or line.startswith('#'):continue
        tokens=line.split();require(len(tokens)==13,'complete13 literal released columns required')
        values=[support.named.number(x) for x in tokens]
        require(values[0]>0 and 0<values[1]<values[0] and all(x>=0 for x in values[2:]),'finite released mass/width population required')
        key=tuple(values[:2]);old=coords.get(key,[])
        require(not old or [support.named.number(x) for x in rows[old[0]]['tokens']]==values,'conflicting released duplicate coordinates refused')
        index=len(rows);coords.setdefault(key,[]).append(index)
        rows.append({'row_ordinal':index+1,'source_line':line_no,'source_text':line,'tokens':tokens})
    require(len(rows)==3794 and len(coords)==3654 and sum(len(x)-1 for x in coords.values())==140,'exact complete released table census required')
    return raw,{'schema_version':1,'source_sha256':SHA256,'source_url':'https://member.ipmu.jp/satoshi.shirai/Chargino_Decay/chargino_decay.dat','paper':'https://arxiv.org/abs/2312.08087','columns':list(COLUMNS),'all_lines':lines,'rows':rows,'row_count':3794,'unique_coordinates':3654,'duplicate_rows':140,'units':'GeV','rounding':'Literal published decimal precision; no certified error enclosure or uncertainty assigned','overlap':{'column_indexing':'zero_based','total_width_column':2,'inclusive_column':6,'contained_exclusive_columns':[7,8,9],'rule':'Never add inclusive and contained exclusive widths to form the total; use published column3.'}}

def validate(task):
    custody._keys(task,('request',),'pure-limit decay table task');require(type(task['request']) is str and task['request'].strip(),'explicit source request required');return dict(task)

def _load(task,base):
    validate(task);p=custody._regular(task['request'],base);raw=support.read(p);d=support.document(raw)
    custody._keys(d,('schema_version','basis','chargino_mass_GeV','neutralinos','complete_accessible_neutralino_population','other_decay_modes','source_evidence'),'exact pure-limit table request')
    require(type(d['schema_version']) is int and d['schema_version']==1 and d['basis'] in ('pure_higgsino_single_neutralino_normalization','pure_wino_four_times_normalization'),'explicit documented pure-limit basis required; no mixed-state substitution')
    require(d['complete_accessible_neutralino_population'] is True and d['other_decay_modes']=='excluded_by_declared_pure_limit_scope','complete accessible daughters and conditional pure-limit scope required')
    support.named.number(d['chargino_mass_GeV']);require(type(d['neutralinos']) is list and 1<=len(d['neutralinos'])<=2,'explicit complete accessible pure-Higgsino (at most two) neutralino multiplicity required')
    identities=[]
    for r in d['neutralinos']:
        custody._keys(r,('id','mass_difference_GeV'),'declared accessible neutralino')
        require(type(r['id']) is str and r['id'].strip(),'explicit daughter identity required');identities.append(r['id']);support.named.number(r['mass_difference_GeV'])
    require(len(set(identities))==len(identities),'distinct physical daughters, no guessed multiplicity factor')
    require(d['basis']!='pure_wino_four_times_normalization' or len(identities)==1,'documented pure Wino basis has one neutral partner; no invented additional multiplicity')
    require(type(d['source_evidence']) is list and 1<=len(d['source_evidence'])<=32,'source-pinned pure-limit/multiplicity premise required; authenticity and physics need review')
    return p,d,raw

def inputs(task,base):
    p,d,_=_load(task,base);calculate(d,population()[1])
    return sorted(set([p,TABLE,Path(__file__).resolve(),Path(support.__file__).resolve(),Path(support.named.__file__).resolve()]+[custody._pin(r,p.parent) for r in d['source_evidence']]))

def calculate(d,table):
    require(d['basis'] in ('pure_higgsino_single_neutralino_normalization','pure_wino_four_times_normalization'),'explicit documented pure-limit basis required; no mixed-state substitution')
    require(type(d['neutralinos']) is list and 1<=len(d['neutralinos'])<=2 and len({r['id'] for r in d['neutralinos']})==len(d['neutralinos']),'complete distinct admitted pure-limit daughter population required')
    require(d['basis']!='pure_wino_four_times_normalization' or len(d['neutralinos'])==1,'documented pure Wino single neutral partner required')
    m=support.named.number(d['chargino_mass_GeV']);factor=4 if d['basis']=='pure_wino_four_times_normalization' else 1;channels=[]
    for daughter in d['neutralinos']:
        delta=support.named.number(daughter['mass_difference_GeV']);matches=[r for r in table['rows'] if support.named.number(r['tokens'][0])==m and support.named.number(r['tokens'][1])==delta]
        require(matches,'exact released mass/splitting row required; no interpolation/extrapolation')
        row=matches[0];tokens=row['tokens']
        # Integer basis factor only, exact decimal row arithmetic.
        with localcontext() as ctx:
            ctx.prec=80;widths=[str(Decimal(t)*factor) for t in tokens[2:]]
        channels.append({'daughter':dict(daughter),'all_duplicate_lineages':[{'row_ordinal':r['row_ordinal'],'source_line':r['source_line']} for r in matches],'original13_tokens':tokens,'basis_factor':factor,'scaled11_widths_GeV':widths,'total_width_GeV':widths[0]})
    total=sum((Fraction(c['total_width_GeV']) for c in channels),Fraction(0))
    return {'schema_version':1,'basis':d['basis'],'daughter_population':channels,'complete_accessible_neutralino_population_declared':True,'total_width_exact_GeV':{'numerator':total.numerator,'denominator':total.denominator},'inclusive_exclusive_double_counting_performed':False,'interpolation_performed':False,'uncertainty_assigned':False,'mixed_state_application_supported':False,'physical_pure_basis_established':False}

def run(task,base,output):
    p,d,raw_request=_load(task,base);files=inputs(task,base);before={x:custody._hash(x) for x in files};raw,table=population();selected=calculate(d,table)
    out=Path(output).absolute();require(not out.exists() or (out.is_dir() and not list(out.iterdir())),'fresh empty table output required')
    require(not any(x.is_symlink() for x in (out,*out.parents)) and not any(x.is_relative_to(out) for x in files),'table output may not contain original inputs or aliases')
    out.mkdir(parents=True,exist_ok=True);target=out/'released-chargino-decay.dat';target.write_bytes(raw);require(support.read(target,SHA256)==raw,'intended original table copy changed')
    result={'status':'passed','scope':SCOPE,'physics_validated':False,'request':json.loads(raw_request),'source_pin':{'path':str(TABLE),'sha256':SHA256},'complete_released_population':table,'selected':selected,'complete_source_table':{'path':str(target),'sha256':SHA256},'limitations':['Pure-limit/multiplicity/source assertions are explicit conditional inputs, not model validation.','No interpolation, mixed MSSM mapping, finite-precision enclosure, new QCD model or invented uncertainty.','Inclusive/exclusive hadronic overlap remains explicit; total uses released total column.','This result is separate from every generated spectrum; no DECAY width graft or fabricated complete SLHA.','Original M1=M2 mixed-state81 LLP lifetime goal remains open.']}
    intended_result=(json.dumps(result,indent=2,allow_nan=False)+'\n').encode()
    committed=support.write_exact(out/'chargino-decay-table.json',result);expected=support.population(out)
    require(set(expected)=={'.','released-chargino-decay.dat','chargino-decay-table.json'},'complete exact table output membership required')
    require(before=={x:custody._hash(x) for x in inputs(task,base)},'original table inputs changed')
    require(expected==support.population(out) and support.read(target,SHA256)==raw and custody._hash(out/'chargino-decay-table.json')==committed['sha256'],'complete table outputs changed before delivery')
    require(support.read(out/'chargino-decay-table.json',limit=64*1024*1024)==intended_result and (json.dumps(result,indent=2,allow_nan=False)+'\n').encode()==intended_result,
        'returned table result differs from its intended durable commitment')
    return result

def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--request',required=True);p.add_argument('--rundir',required=True);p.add_argument('--review-policy',required=True);p.add_argument('--approval-mode',choices=('physicist','scripted_yes'),default='physicist');a=p.parse_args(argv)
    task={'request':str(custody._regular(a.request,Path.cwd()))};inputs(task,Path.cwd());policy=custody._read(custody._regular(a.review_policy,Path.cwd()));require(policy['policy']['max_redos']==0,'one attempt zero redo required')
    spec={'schema_version':2,'mode':'chargino-decay-table','source':'Exact released2312.08087 pure-limit decay table','assumptions':['Complete3794 rows/13 columns preserved; selected exact rows are conditional on explicit pure-limit daughter census.','No mixed-state MSSM lifetime qualification or uncertainty inferred.'],'max_seconds':30,'max_attempts':1,'approval_mode':a.approval_mode,'review_policy':policy,'task':task}
    from ravel.workflow import science
    proposal=Path(a.rundir).absolute().with_name(Path(a.rundir).name+'-proposal');require(not proposal.exists() and not Path(a.rundir).exists(),'fresh table study/proposal required');proposal.mkdir(parents=True);support.write_exact(proposal/'science.json',spec);science.plan(a.rundir,proposal/'science.json');return 0

if __name__=='__main__':raise SystemExit(main())
