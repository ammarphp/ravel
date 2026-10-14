"""Supplied mass/width grids and source-defined paired-region constructions.

No generation or fit is launched. Complete observations, correlated transfer
laws, operative cards and original generated exposure remain supplied premises.
"""
from copy import deepcopy
from fractions import Fraction as F
import hashlib
import json
import math
from pathlib import Path

from ravel.physics import statistical_construction as regional
from ravel.physics import background_construction as background
from ravel.physics.ma5_saf import Capture, _json
from ravel.physics.ma5_pad import InputCapture
from ravel.workflow import task_completion, science
from ravel.workflow.state_io import atomic_json

SCOPE = 'supplied_whole_mass_width_grid_construction'
from ravel.physics import supplied_contracts as contracts
MAX_DELIVERY = 64*1024**2


def require(ok, message):
    if not ok: raise ValueError(message)


def keys(d, fields, label):
    if type(d) is dict:
        for field in fields:
            if field not in d: raise contracts.MissingInputError(field, label)
    regional._keys(d, set(fields), label)
def q(x): return regional._q(x)
def literal(x):
    require(type(x) in (int, float) and math.isfinite(x), 'finite literal scan coordinate required')
    return F(str(x))


def read(c, pin, base, *, document=True):
    require(type(pin) is dict and set(pin) in ({'path','sha256'}, {'path','sha256','size'}), 'closed source pin required')
    path, raw = c.pin({k:pin[k] for k in ('path','sha256')}, base)
    if 'size' in pin: require(type(pin['size']) is int and pin['size']==len(raw), 'source size changed')
    require(len(c.files)<=512 and sum(len(v[1]) for v in c.files.values())<=32*1024**2,
            'whole source metadata exceeds512 members/32MiB')
    return path, _json(raw) if document else raw


def all_sources(doc, c, base):
    require(type(doc['sources']) is list and 1<=len(doc['sources'])<=128, 'complete explicit scientific source population required')
    ids=[];out=[]
    for row in doc['sources']:
        keys(row, ('id','path','sha256'), 'scientific source')
        regional._id(row['id']);require(row['id'] not in ids, 'unique scientific source IDs required');ids.append(row['id'])
        path,_=read(c,{k:row[k] for k in ('path','sha256')},base,document=False)
        out.append({**row,'path':str(path)})
    return out


def transfer_basis(transfer, windows):
    """Exact POINT basis or explicit BIN-AVERAGE basis, never implicit midpoint."""
    keys(transfer, ('degree','domain','evaluation','coordinates','coefficients','tag_efficiency','log_response','source'), 'tag transfer')
    require(type(transfer['degree']) is int and 0 <= transfer['degree'] <= 12, 'bounded supplied Bernstein degree required')
    degree = transfer['degree']
    a,b=background._interval(transfer['domain']);n=len(windows)
    require(0<q(transfer['tag_efficiency'])<1, 'tag fraction must be strictly between0and1')
    if transfer['evaluation']=='point':
        xs=regional._vector(transfer['coordinates'],n,'source-defined transfer evaluation coordinates')
        for x,w in zip(xs,windows):
            lo,hi=background._interval(w);require(a<=lo<hi<=b and lo<=x<=hi, 'source transfer point/window outside domain')
        rows=[[math.comb(degree,j)*((x-a)/(b-a))**j*(1-(x-a)/(b-a))**(degree-j) for x in xs] for j in range(degree+1)]
    elif transfer['evaluation']=='bin_average':
        require(transfer['coordinates'] is None, 'bin-average convention must not claim point samples')
        integrated=background.basis_integrals({'kind':'bernstein','degree':degree},transfer['domain'],windows)
        rows=[[q(v)*(b-a)/(degree+1)/(q(w[1])-q(w[0])) for v,w in zip(row,windows)] for row in integrated]
    else: raise ValueError('explicit point or bin_average source convention required')
    require(all(sum(row[i] for row in rows)==1 for i in range(n)), 'Bernstein partition changed')
    return rows


def validate_response(response, coordinate):
    """Admit a complete point even when a missing data law blocks lowering."""
    contracts.fields(response, ('construction_metadata',))
    keys(response, ('schema_version','coordinate','sources','observable','windows','region_ids','energy_tev','lumi_fb','normalization','components','model','assumptions','construction_metadata'), 'width-specific response')
    require(type(response['schema_version']) is int and response['schema_version']==1 and response['coordinate']==coordinate, 'fresh exact mass/width response required')
    regional._id(response['observable'])
    require(type(response['region_ids']) is list and response['region_ids'] and len(set(response['region_ids'])) == len(response['region_ids']), 'complete unique supplied response regions required')
    for rid in response['region_ids']: regional._id(rid)
    windows=response['windows'];require(type(windows) is list and 1<=len(windows)<=64, 'complete response mass windows required')
    intervals=[background._interval(w) for w in windows]
    require(all(a[1]==b[0] for a,b in zip(intervals,intervals[1:])), 'contiguous response window required')
    require(literal(response['energy_tev']) > 0 and literal(response['lumi_fb']) > 0, 'explicit positive response energy and luminosity required')
    require(type(response['sources']) is list and response['sources'], 'point scientific sources required')
    ids={r['id'] for r in response['sources']};require(len(ids)==len(response['sources']), 'unique point source identities required')
    norm=response['normalization'];keys(norm,('cross_section_pb','includes_branching','generated_sumw','accepted_sumw','acceptance_definition','efficiency_definition','population','source'),'signal normalization')
    require(norm['source'] in ids and norm['includes_branching'] is True and q(norm['cross_section_pb'])>0 and q(norm['generated_sumw'])>0, 'positive branching-included complete normalization required')
    require(0<=q(norm['accepted_sumw'])<=q(norm['generated_sumw']), 'accepted/full exposure ordering required')
    require(norm['acceptance_definition']=='accepted_over_complete_generated' and norm['efficiency_definition']=='fit_bins_over_accepted', 'explicit single-use acceptance and efficiency required')
    regional._text(norm['population'],'whole generated population statement')
    model=response['model'];keys(model,('parameter_card','pdg','width_scheme','interference','coupling_projection','source','decay_channels'),'resonance model')
    require(type(model['pdg']) is int and model['pdg']>0 and model['source'] in ids and model['width_scheme'] in ('fixed_pole_width','source_running_width'), 'source-bound resonance and width scheme required')
    require(model['interference'] in ('neglected_by_assumption','included_signed') and model['coupling_projection']=='none', 'explicit interference and separate coupling projection required')
    require(type(model['decay_channels']) is list and model['decay_channels'] and all(type(ch) is list and ch and all(type(p) is int for p in ch) for ch in model['decay_channels']) and len({tuple(ch) for ch in model['decay_channels']}) == len(model['decay_channels']), 'explicit complete decay-channel contract required')
    wanted=['bsm'] if model['interference']=='neglected_by_assumption' else ['bsm','interference']
    components=response['components'];require(type(components) is list and [r['basis'] for r in components]==wanted, 'complete signal/interference basis required')
    nuisance_dimension=None
    for row in components:
        keys(row,('basis','selected_sumw','log_response','source'),'allregion response component')
        values=regional._vector(row['selected_sumw'],len(response['region_ids'])*len(windows),'allregion selected weights')
        require(row['source'] in ids, 'component source required')
        if row['basis']=='bsm':require(all(x>=0 for x in values) and sum(values)<=q(norm['accepted_sumw']), 'selected BSM exceeds accepted population')
        matrix=row['log_response'];require(type(matrix) is list and len(matrix)==len(values) and type(matrix[0]) is list and len(matrix[0])<=32, 'complete bounded nuisance response required')
        if nuisance_dimension is None:nuisance_dimension=len(matrix[0])
        for vector in matrix:regional._vector(vector,nuisance_dimension,'consistent allcomponent nuisance response')
    require(type(response['assumptions']) is list and response['assumptions'], 'point applicability assumptions required')
    for a in response['assumptions']:
        keys(a,('id','statement','source','status'),'point assumption');regional._id(a['id']);regional._text(a['statement'],'point assumption')
        require(a['source'] in ids and a['status'] in ('assumed','externally_checked'), 'source-bound assumption status required')


def operative_card(card, pdg, coordinate, decay_channels):
    from ravel.physics.model_inputs import _parse_slha
    masses,decays,_=_parse_slha(card.decode())
    require(type(pdg) is int and pdg in masses and pdg in decays, 'operative resonance MASS and DECAY card required')
    require(masses[pdg]['mass_GeV_exact']==literal(coordinate['mass_GeV']) and decays[pdg]['width_GeV_exact']==literal(coordinate['mass_GeV'])*literal(coordinate['width_over_mass']), 'operative source-card mass/width differs from requested point')
    channels=decays[pdg]['channels']
    require(decays[pdg]['branching_fraction_sum_exact']==1 and channels and sorted(x['daughter_pdgs'] for x in channels)==sorted(decay_channels), 'source card must retain the complete supplied decay convention; no missing modes')


def validate_law(law):
    """Missing response does not suspend admission of a supplied observation law."""
    contracts.fields(law, ('region_pairs',))
    keys(law, ('schema_version','sources','windows','regions','region_pairs','transfer','latent_rates','resonant_backgrounds','auxiliary','template_statistics','partition','poi','assumptions') + (('expected_data',) if 'expected_data' in law else ()), 'regional law')
    require(type(law['schema_version']) is int and law['schema_version']==1, 'regional law schema1 required')
    n=len(law['windows']);require(type(law['windows']) is list and 1<=n<=60, 'bounded complete regional windows required')
    intervals=[background._interval(w) for w in law['windows']];require(all(a[1]==b[0] for a,b in zip(intervals,intervals[1:])), 'complete contiguous observed windows required')
    ids={row['id'] for row in law['sources']};require(ids and len(ids)==len(law['sources']), 'unique explicit law sources required')
    region_ids, pairs = paired_regions(law)
    total = len(region_ids)*n
    for row in law['regions']:
        keys(row,('id','role','observed','source'),'observed region');require(row['source'] in ids and type(row['observed']) is list and len(row['observed'])==n and (all(x is None for x in row['observed']) if ('expected_data' in law and law['expected_data'].get('conditioning')=='supplied_nominal') else all(type(x) is int and x>=0 for x in row['observed'])), 'actual integer observations or explicit nominal Asimov nulls required')
    transfer_basis(law['transfer'],law['windows'])
    aux=law['auxiliary'];keys(aux,('kind','names','observed','factor','eta_bounds','source'),'auxiliary')
    k=len(aux['names']);require(aux['kind']=='supplied_gaussian_factor' and aux['source'] in ids and type(aux['names']) is list and k<=32 and len(set(aux['names']))==k, 'explicit supplied bounded Gaussian factor required')
    regional._vector(aux['observed'],k,'auxiliary observations')
    require(type(aux['factor']) is list and len(aux['factor'])==k and type(aux['eta_bounds']) is list and len(aux['eta_bounds'])==k, 'complete auxiliary factor and bounds required')
    for i,row in enumerate(aux['factor']):
        numbers=regional._vector(row,k,'auxiliary factor');require(numbers[i]>0 and all(v==0 for v in numbers[i+1:]), 'positive lower triangular supplied factor required')
        regional._bounds(aux['eta_bounds'][i],'0');regional._id(aux['names'][i])
    transfer=law['transfer'];require(transfer['source'] in ids and type(transfer['coefficients']) is list and len(transfer['coefficients'])==transfer['degree']+1, 'complete supplied Bernstein coefficient population required')
    require(type(transfer['log_response']) is list and len(transfer['log_response'])==total, 'whole shared transfer response required')
    for row in transfer['log_response']:regional._vector(row,k,'transfer response')
    rates=law['latent_rates'];keys(rates,tuple(pair['id'] for pair in pairs),'independent paired rates')
    pars=[law['poi'],*transfer['coefficients']]
    require(law['poi']['role']=='poi', 'explicit supplied strength POI required')
    require(all(p['role']=='rate' and p['source']==transfer['source'] for p in transfer['coefficients']), 'shared transfer coefficient context required')
    for side in (pair['id'] for pair in pairs):
        require(type(rates[side]) is list and len(rates[side])==n and all(p['role']=='rate' for p in rates[side]), 'every independent named antitag rate required')
        pars.extend(rates[side])
    names=[]
    for p in pars:
        keys(p,('name','role','initial','bounds','fixed','meaning','source'),'physical parameter');regional._id(p['name']);names.append(p['name']);regional._text(p['meaning'],'parameter meaning')
        lo,_=regional._bounds(p['bounds'],p['initial']);require(p['source'] in ids and type(p['fixed']) is bool and (p['role']!='rate' or lo>=0), 'source-bound nonnegative rate domain required')
    if 'expected_data' in law:
        from ravel.physics import regional_expected
        regional_expected.validate_request(law['expected_data'],pars,aux,ids)
    require(len(names)==len(set(names)) and not set(names).intersection(aux['names']) and not law['poi']['fixed'], 'unique physical/nuisance names and floating POI required')
    require(type(law['resonant_backgrounds']) is list, 'complete resonant background population required')
    for row in law['resonant_backgrounds']:
        keys(row,('id','expected_events','log_response','source'),'resonant background');regional._id(row['id']);require(row['source'] in ids and all(x>=0 for x in regional._vector(row['expected_events'],total,'resonant events')), 'whole nonnegative resonant background required')
        require(len(row['log_response'])==total, 'complete resonant nuisance response required')
        for values in row['log_response']:regional._vector(values,k,'resonant nuisance response')
    for field,kind in (('partition','declared_disjoint_poisson_counts'),('template_statistics','conditional_on_supplied_coefficients')):
        row=law[field];keys(row,('kind','statement','source'),field);regional._text(row['statement'],field)
        require(row['kind']==kind and row['source'] in ids, 'supplied disjoint observations and explicit fixed-template law required; finite-MC auxiliaries need their separately supplied consumer')
    require(type(law['assumptions']) is list and law['assumptions'], 'explicit law applicability assumptions required')
    for row in law['assumptions']:
        keys(row,('id','statement','source','status'),'law assumption');regional._id(row['id']);regional._text(row['statement'],'law assumption');require(row['source'] in ids and row['status'] in ('assumed','externally_checked'), 'source-bound law assumption required')


def paired_regions(law):
    contracts.fields(law, ('regions', 'region_pairs'))
    regions = law['regions']
    require(type(regions) is list and 2 <= len(regions) <= 16, 'bounded supplied region census required')
    ids = [r['id'] for r in regions]
    require(len(set(ids)) == len(ids), 'unique supplied region identities required')
    for row in regions:
        keys(row, ('id', 'role', 'observed', 'source'), 'supplied region')
        regional._id(row['id'])
        require(row['role'] in ('signal_region', 'control_region'), 'explicit region statistical role required')
    pairs = law['region_pairs']
    require(type(pairs) is list and pairs, 'complete supplied tag/antitag pairs required')
    used = []; pair_ids = []
    for pair in pairs:
        keys(pair, ('id', 'tagged', 'antitagged'), 'region pair')
        regional._id(pair['id']); pair_ids.append(pair['id'])
        used.extend((pair['tagged'], pair['antitagged']))
    require(len(set(pair_ids)) == len(pair_ids) and len(used) == len(set(used)) and set(used) == set(ids),
            'every region must occur in exactly one supplied pair')
    return ids, pairs


def construct(law, response, coordinate):
    """Lower supplied transfer and response laws without fitting or launching."""
    validate_response(response, coordinate); validate_law(law)
    region_ids, pairs = paired_regions(law)
    windows = law['windows']; n = len(windows); total = n*len(region_ids)
    require(response['windows'] == windows and response['region_ids'] == region_ids,
            'exact supplied law/response region and window basis required')
    bins = [{'id': row['id']+'_b'+str(i), 'role': row['role'], 'observed': value,
             'observation_id': row['id']+'_b'+str(i), 'source': row['source']}
            for row in law['regions'] for i, value in enumerate(row['observed'])]
    transfer = law['transfer']; basis = transfer_basis(transfer, windows)
    coefficients = deepcopy(transfer['coefficients']); poi = deepcopy(law['poi'])
    pars = [poi, *coefficients]; k = len(law['auxiliary']['names']); terms = []
    tag = q(transfer['tag_efficiency'])/(1-q(transfer['tag_efficiency']))
    zero = ['0']*total
    for pair in pairs:
        name = pair['id']; tag_index = region_ids.index(pair['tagged']); anti_index = region_ids.index(pair['antitagged'])
        for i, parameter in enumerate(law['latent_rates'][name]):
            p = deepcopy(parameter); pars.append(p); co = zero.copy(); co[anti_index*n+i] = '1'
            terms.append({'id': name+'_anti'+str(i), 'basis': 'background', 'coefficients': co,
                          'powers': {p['name']: 1}, 'log_response': [['0']*k for _ in co], 'source': p['source']})
            for j, coefficient in enumerate(coefficients):
                co = zero.copy(); co[tag_index*n+i] = str(tag*basis[j][i])
                terms.append({'id': name+'_tag'+str(i)+'_'+str(j), 'basis': 'background', 'coefficients': co,
                              'powers': {p['name']: 1, coefficient['name']: 1},
                              'log_response': deepcopy(transfer['log_response']), 'source': transfer['source']})
    for row in law['resonant_backgrounds']:
        terms.append({'id': row['id'], 'basis': 'background', 'coefficients': [str(q(v)) for v in row['expected_events']],
                      'powers': {}, 'log_response': deepcopy(row['log_response']), 'source': row['source']})
    norm = response['normalization']; model = response['model']
    scale = q(norm['cross_section_pb'])*1000*literal(response['lumi_fb'])/q(norm['generated_sumw'])
    for row in response['components']:
        values = regional._vector(row['selected_sumw'], total, 'complete selected weights including control contamination')
        terms.append({'id': 'signal_'+row['basis'], 'basis': row['basis'], 'coefficients': [str(v*scale) for v in values],
                      'powers': {poi['name']: 2 if model['interference']=='included_signed' and row['basis']=='bsm' else 1},
                      'log_response': deepcopy(row['log_response']), 'source': row['source']})
    metadata = response['construction_metadata']
    keys(metadata, ('model_id', 'question', 'energy', 'luminosity', 'scale', 'domain_statement'), 'supplied construction presentation')
    for key, value in metadata.items(): regional._text(value, key)
    d = {'schema_version': 1, 'model_id': metadata['model_id'], 'question': metadata['question'],
         'sources': deepcopy(law['sources']+response['sources']), 'parameters': pars, 'bins': bins, 'terms': terms,
         'auxiliary': deepcopy(law['auxiliary']), 'partition': deepcopy(law['partition']),
         'prediction': {'units': 'expected_events', 'energy': metadata['energy'], 'luminosity': metadata['luminosity'],
                       'basis': 'background + strength^2 BSM + strength interference' if model['interference']=='included_signed' else 'background + strength BSM',
                       'scale': metadata['scale'], 'domain_statement': metadata['domain_statement'], 'source': transfer['source']},
         'template_statistics': deepcopy(law['template_statistics']), 'assumptions': deepcopy(law['assumptions']+response['assumptions'])}
    if 'expected_data' in law: d['expected_data'] = deepcopy(law['expected_data'])
    return regional.validate(d)


def validate(task): keys(task,('input',),'mass-width-grid task');require(type(task['input']) is str and task['input'], 'mass-width-grid input pathname required')


def _load(task, base):
    validate(task);c=InputCapture();p,raw=c.read(task['input'],base);d=_json(raw)
    return _load_document(p,d,c)


def _load_document(p,d,c):
    # Shared side-effect-free semantics for the source-specific input producer.
    base=p.parent
    contracts.fields(d, ('analysis', 'axes', 'cells', 'output'))
    keys(d,('schema_version','goal_binding','analysis','axes','cells','regional_input','native_runtime','native_fit','review_policy','child_seconds','assumptions','output'),'whole width study')
    output_spec(d['output'])
    require(type(d['schema_version']) is int and d['schema_version']==2, 'explicit mass-width-grid schema2 required')
    projection=task_completion.binding_projection(d['goal_binding'],base_dir=base)
    for row in projection['input_pins']:read(c,row,base,document=False)
    require(type(d['assumptions']) is list and d['assumptions'] and all(type(s) is str and s for s in d['assumptions']), 'explicit scope and applicability assumptions required')
    a=d['analysis']; contracts.fields(a, ('region_ids','generation'))
    keys(a,('id','energy_tev','lumi_fb','observable','pdg','references','missing','region_ids','generation'),'analysis')
    regional._text(a['id'], 'supplied analysis identity'); regional._id(a['observable'])
    require(literal(a['energy_tev']) > 0 and literal(a['lumi_fb']) > 0, 'explicit positive analysis energy and luminosity required')
    require(type(a['region_ids']) is list and a['region_ids'] and len(set(a['region_ids'])) == len(a['region_ids']), 'complete supplied analysis region identities required')
    for rid in a['region_ids']: regional._id(rid)
    generation = a['generation']; keys(generation, ('beam_pdg', 'energy_gev', 'initial', 'required_final', 'decay_channels'), 'supplied generation convention')
    require(type(generation['beam_pdg']) is list and len(generation['beam_pdg']) == 2 and all(type(p) is int for p in generation['beam_pdg']), 'two supplied beam identities required')
    require(type(generation['energy_gev']) is list and len(generation['energy_gev']) == 2 and all(literal(x)>0 for x in generation['energy_gev']) and sum(literal(x) for x in generation['energy_gev']) == literal(a['energy_tev'])*1000, 'beam energies must match supplied collision energy')
    require(type(generation['initial']) is list and len(generation['initial']) == 2 and type(generation['required_final']) is list and all(type(x) is str and x for x in generation['initial']+generation['required_final']), 'explicit source process convention required')
    require(type(a['pdg']) is int and a['pdg']>0, 'explicit source resonance PDG required')
    require(type(a['references']) is list and a['references'], 'primary analysis/reference targets required')
    for row in a['references']:read(c,row,base,document=False)
    require(type(a['missing']) is list and all(type(s) is str and s for s in a['missing']), 'explicit remaining scientific dependencies required')
    from ravel.workflow.scan_orchestrator import enumerate_axes
    grid=enumerate_axes(d['axes'],maximum=128)
    reserved = {name for i in range(len(grid)) for name in
                ('point-'+str(i)+'-construction.json', 'point-'+str(i)+'-native', 'point-'+str(i)+'-generation')}
    require(not {d['output'][kind]['filename'] for kind in ('result','report')}.intersection(reserved),
            'output contract collides with derived construction destinations')
    require([r['name'] for r in d['axes']]==['mass_GeV','width_over_mass'], 'mass and width axes required')
    widths=[literal(x) for x in d['axes'][1]['values']]
    require(widths==sorted(widths) and widths and len(set(widths))==len(widths) and all(x>0 for x in widths), 'explicit increasing positive finite width ratios required')
    require(all(literal(x)>0 for x in d['axes'][0]['values']), 'explicit positive mass grid required')
    cells=d['cells'];require(type(cells) is list and len(cells)==len(grid), 'complete mass/width denominator required')
    require([r['coordinate'] for r in cells]==grid, 'ordered full mass/width product required; no best-point selection')
    law=None
    if d['regional_input'] is not None:
        lp,law=read(c,d['regional_input'],base);law['sources']=all_sources(law,c,lp.parent)
        validate_law(law)
        require([r['id'] for r in law['regions']] == a['region_ids'], 'law differs from supplied analysis region population')
    for row in cells:
        keys(row,('coordinate','generation_request','response','missing'),'mass/width cell')
        require(type(row['missing']) is list and all(type(s) is str and s for s in row['missing']), 'cell missing-input obligations required')
        if row['response'] is not None:
            rp,response=read(c,row['response'],base);response['sources']=all_sources(response,c,rp.parent)
            validate_response(response,row['coordinate'])
            require(response['observable']==a['observable'] and response['region_ids']==a['region_ids'] and literal(response['energy_tev'])==literal(a['energy_tev']) and literal(response['lumi_fb'])==literal(a['lumi_fb']), 'response differs from supplied analysis basis, energy or luminosity')
            require(response['coordinate']==row['coordinate'] and response['model']['pdg']==a['pdg'] and response['model']['coupling_projection']=='none' and response['model']['decay_channels']==generation['decay_channels'], 'exact response point/resonance and complete decay identity; no automatic coupling projection')
            mp,card=read(c,response['model']['parameter_card'],rp.parent,document=False)
            operative_card(card,response['model']['pdg'],row['coordinate'],response['model']['decay_channels'])
            if law is not None: construct(law,response,row['coordinate'])
        if row['generation_request'] is not None:
            gp,request=read(c,row['generation_request'],base)
            require(request['goal_binding']==d['goal_binding'], 'generation preparation must retain original parent')
            cfgp,config=read(c,request['config'],gp.parent)
            if row['response'] is not None:
                rp,response=read(c,row['response'],base)
                cardpin=response['model']['parameter_card'];cardpath,_=read(c,cardpin,rp.parent,document=False)
                generatedcardpath,_=read(c,config['cards']['parameter'],cfgp.parent,document=False)
                require(cardpath==generatedcardpath and cardpin['sha256']==config['cards']['parameter']['sha256'], 'generator must use the operative exact point card; no point label override')
            require(config['generation']['beam_pdg']==generation['beam_pdg'] and config['generation']['energy_gev']==generation['energy_gev'], 'generation differs from supplied beam convention')
            cpp,cr=read(c,config['cards']['parameter'],cfgp.parent,document=False)
            operative_card(cr,a['pdg'],row['coordinate'],generation['decay_channels'])
            _,process=read(c,config['cards']['process'],cfgp.parent,document=False)
            from ravel.physics.model_events import process_commands
            commands=process_commands(process.decode(),config)
            for command in commands:
                if command.startswith(('generate ','add process ')):
                    expression=command.removeprefix('generate ').removeprefix('add process ')
                    initial,final=expression.split('>',1)
                    require(initial.split()==generation['initial'] and set(generation['required_final']) <= set(final.split('[')[0].split('@')[0].split('/')[0].split()), 'each source process must retain the supplied initial and required final particles')
            from ravel.workflow.model_event_plan import request_inputs
            for path in request_inputs(request,gp.parent):
                # Large native runtime files use existing streaming admission
                # at later generation planning; this recipe retains their exact
                # external digests without decoding binaries into its context.
                from ravel.physics.model_events import _generated_pin
                observed=_generated_pin(path)
                c.stream_pin({k:observed[k] for k in ('path','sha256')},gp.parent,allow_empty=True)
                require(len(c.streams)+len(c.files)<=20000 and sum(v[0][0][3] for v in c.streams.values())<=16*1024**3, 'expanded generation runtime closure exceeds20000members/16GiB')
    for field in ('native_runtime','native_fit','review_policy'):
        if d[field] is not None:read(c,d[field],base)
    require((d['native_runtime'] is None)==(d['native_fit'] is None), 'native runtime and fit are a complete pair')
    require(type(d['child_seconds']) is int and 1<=d['child_seconds']<=86400, 'prospective child ceiling required')
    c.finish();return p,d,law,c


def inputs(task,base):
    from ravel.physics import regional_expected
    _,_,_,c=_load(task,base);return [*c.files,*c.streams,Path(__file__).resolve(),Path(regional.__file__).resolve(),Path(background.__file__).resolve(),Path(regional_expected.__file__).resolve(),Path(contracts.__file__).resolve()]


def execution_seconds(task,base):return 60


def goal_inputs(spec,base):
    _,d,_,_=_load(spec['task'],base)
    require(spec.get('goal_binding')==d['goal_binding'], 'ordinary outer parent must equal whole mass-width-grid parent')


def _write(out,name,value,cap):
    # Commit the intended document before giving any writer mutable objects.
    # The bounded capture must equal these exact bytes, never a new baseline
    # of whatever the writer happened to leave on disk.
    intended=(json.dumps(value,indent=2,allow_nan=False)+'\n').encode('utf-8')
    atomic_json(out/name,json.loads(intended));p,b=cap.read(str(out/name),out)
    require(b==intended, 'generated width document differs from intended bytes')
    return {'path':str(p),'sha256':hashlib.sha256(intended).hexdigest(),'size':len(intended)}


def run(task,base,output):
    p,d,law,c=_load(task,base);out=Path(output).absolute()
    require(not out.exists() and '..' not in out.parts and not any(q.is_symlink() for q in (out,*out.parents)), 'fresh canonical mass-width-grid output required')
    require(not any(q.is_relative_to(out) for q in c.files), 'output cannot contain source');out.mkdir(parents=True);emitted=Capture();rows=[]
    for index,cell in enumerate(d['cells']):
        row={'coordinate':cell['coordinate'],'state':'blocked','missing':list(d['analysis']['missing']+cell['missing']),
             'generation_preparation':None,'construction':None,'native_specification':None}
        if d['native_runtime'] is None or d['review_policy'] is None:row['missing'].append('Exact native likelihood runtime, fit prescription and independent ordinary review policy for a later separately approved fit.')
        if law is None:row['missing'].append('Genuine complete background/auxiliary/transfer law plus actual integer observations or an explicit source-bound expected-only generating prescription; postfit HEPData cannot substitute.')
        if cell['response'] is None:row['missing'].append('Width-specific source-card and complete supplied regional signal/contamination response, original generated denominator and uncertainties.')
        else:
            rp,response=read(c,cell['response'],p.parent);response['sources']=all_sources(response,c,rp.parent)
            if law is not None:
                doc=construct(law,response,cell['coordinate'])
                # Original derived inputs are separate source objects from the
                # primary statements. Bind all of them in the ordinary child.
                for identity,path in [('width_request',p),('width_law',Path(d['regional_input']['path']) if Path(d['regional_input']['path']).is_absolute() else p.parent/d['regional_input']['path']),('width_response',rp)]:
                    require(identity not in {x['id'] for x in doc['sources']}, 'reserved width source identity collision')
                    doc['sources'].append({'id':identity,'path':str(path),'sha256':hashlib.sha256(c.files[path][1]).hexdigest()})
                doc['sources'].append({'id':'width_parameter_card','path':str(read(c,response['model']['parameter_card'],rp.parent,document=False)[0]),'sha256':response['model']['parameter_card']['sha256']})
                regional.validate(doc)
                row['construction']=_write(out,'point-'+str(index)+'-construction.json',doc,emitted)
                row['state']='constructed_conditional_inputs'
                if not row['missing'] and cell['generation_request'] is not None and d['native_runtime'] is not None and d['review_policy'] is not None:
                    _,runtime=read(c,d['native_runtime'],p.parent);_,fit=read(c,d['native_fit'],p.parent);_,policy=read(c,d['review_policy'],p.parent)
                    require(fit['poi']==law['poi']['name'], 'native fit must use constructed physical POI')
                    from ravel.workflow.resonance_study import construct_regional
                    child=out/('point-'+str(index)+'-native')
                    result=construct_regional({k:row['construction'][k] for k in ('path','sha256')},runtime,fit,child,base_dir=out,max_seconds=d['child_seconds'])
                    for f in sorted(child.rglob('*')):
                        if f.is_file():emitted.read(str(f),out)
                    spec={'schema_version':2,'mode':result['mode'],'source':doc['question'],'assumptions':d['assumptions'],
                          'max_seconds':d['child_seconds']+60,'approval_mode':'physicist','max_attempts':1,'goal_binding':d['goal_binding'],'review_policy':policy,'task':result['task']}
                    science.validate(spec);science.task_inputs(spec,child)
                    row['native_specification']=_write(child,'science.json',spec,emitted);row['state']='prepared_unapproved'
        if cell['generation_request'] is not None:
            gp,request=read(c,cell['generation_request'],p.parent)
            from ravel.workflow.model_event_plan import prepare
            destination=out/('point-'+str(index)+'-generation')
            row['generation_preparation']=prepare(request,base_dir=gp.parent,output_dir=destination)
            for f in sorted(destination.rglob('*')):
                if f.is_file():emitted.read(str(f),out)
        else:row['missing'].append('Source-matched generation/shower model and operative card/runtime for each width; no narrow-width rescaling.')
        if row['missing'] and row['state']=='prepared_unapproved':row['state']='constructed_conditional_inputs';row['native_specification']=None
        rows.append(row)
    result={'kind':'whole-mass-width-grid-recipe','schema_version':1,'status':'passed','status_scope':SCOPE,
            'goal_binding':d['goal_binding'],'original_request':_json(c.files[read(c,d['goal_binding']['contract'],p.parent,document=False)[0]][1])['prompt'],'analysis':d['analysis'],'axes':d['axes'],'cells':rows,
            'input_pins':[{'path':str(path),'sha256':hashlib.sha256(raw).hexdigest(),'size':len(raw)} for path,(_,raw) in c.files.items()]+[{'path':str(path),'sha256':fact[1],'size':fact[0][3]} for path,(fact,_) in c.streams.items()],
            'output_inventory':[{'path':str(path),'sha256':hashlib.sha256(raw).hexdigest(),'size':len(raw)} for path,(_,raw) in emitted.files.items()],
            'generated_events':0,'fits':0,'physics_validated':False,'execution_authorized':False,'original_task_complete':False,
            'coupling_projection':None,'calibration':'unknown','native_parity':'unknown','assumptions':d['assumptions'],
            'output':d['output'], 'endpoint_obligations':[*d['analysis']['missing'], 'Source-qualified coupling-to-rate/width/branching map and supplied reference comparison; broad-width strength is not a coupling bound.', 'Separately admitted generation, reconstructed response, complete fit population and scientific decisions.']}
    require(len(rows)==len(d['cells']), 'whole width population changed');c.finish();emitted.finish()
    try:
        _emit_result(out,result,d['output']['result'],emitted)
        require(sum(len(v[1]) for v in emitted.files.values())<=MAX_DELIVERY, 'whole delivery exceeds64MiB including completion')
        c.finish();emitted.finish()
    except Exception:
        target=out/d['output']['result']['filename']
        if target.exists(): target.rename(target.with_name('failed-'+target.name))
        raise
    return result


def output_spec(spec):
    contracts.fields(spec, ('result', 'report'))
    keys(spec, ('result', 'report'), 'width output contract')
    contracts.output_contract(spec['result'])
    report = spec['report']; keys(report, ('filename', 'format'), 'population report')
    contracts.output_contract({'filename':report['filename'], 'format':'json'})
    require(report['format'] in ('markdown', 'csv', 'json'), 'supported supplied population report format required')
    require(report['filename'] != spec['result']['filename'], 'distinct result/report outputs required')


def _emit_result(out, value, output, cap):
    if output['format']=='json': return _write(out,output['filename'],value,cap)
    p=contracts.publish(out,value,output);_,raw=cap.read(str(p),out)
    return {'path':str(p),'sha256':hashlib.sha256(raw).hexdigest(),'size':len(raw)}


def write_report(result,out):
    import csv
    import io
    cap=Capture()
    for pin in result['output_inventory']:read(cap,pin,out,document=False)
    report=result['output']['report'];destination=Path(out)/report['filename']
    require(not destination.exists() and not destination.is_symlink(), 'fresh report destination required')
    rows=[[c['coordinate']['mass_GeV'],c['coordinate']['width_over_mass'],c['state'],'; '.join(c['missing'])] for c in result['cells']]
    header=['mass_GeV','width_over_mass','state','remaining_inputs']
    if report['format']=='json':
        contracts.publish(out, [dict(zip(header,row)) for row in rows], {'filename':report['filename'],'format':'json'})
    elif report['format']=='csv':
        stream=io.StringIO();writer=csv.writer(stream);writer.writerow(header);writer.writerows(rows);destination.write_text(stream.getvalue())
    else:
        lines=['# Complete mass / width input construction','',result['original_request'],'',
               'No generation, fit, native parity, coupling limit or original-task completion is inferred.','',
               '| '+' | '.join(header)+' |','|---:|---:|---|---|']
        lines+=['| '+' | '.join(str(v).replace('|','\\|') for v in row)+' |' for row in rows]
        destination.write_text('\n'.join(lines)+'\n')
    cap.finish()
    return [{'stem':destination.stem,'files':[destination.name],
             'normalization':'Whole mass/width input population; no generation, fit or physical limit'}]
