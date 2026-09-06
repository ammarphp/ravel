#!/usr/bin/env python3
"""Rebuild this bounded waypoint from retained records, or verify its public bytes.

No event reader, generation, likelihood optimization or certificate issuance occurs.
The optional --units check evaluates fixed parameter vectors only.
"""
from __future__ import annotations
import argparse
import copy
import csv
import gzip
import hashlib
import io
import json
import math
from pathlib import Path, PurePosixPath
import re
import sys
import tomllib

HERE = Path(__file__).resolve().parent
CAMPAIGN = 'trial-runs/2026-09-05_SUSY-2018-16_rrr-closure'
REVIEW = 'local-runs/rrr-closure/physics-review'
STAGES = ['prepare','madgraph','unpack_lhe','lhe_check','pythia','normalization','delphes','analysis','simpleanalysis','sa2json','pyhf','native_report']
RUNS = {'smoke2': ('nominal_m150_dm10_smoke2', 1000, 'smoke2'), 'anchor20k': ('nominal_m150_dm10_20k', 20000, '20k')}

def digest(data):
    return hashlib.sha256(data).hexdigest()

def strict(data):
    def pairs(values):
        result = {}
        for key, value in values:
            if key in result:
                raise ValueError(f'duplicate key: {key}')
            result[key] = value
        return result
    def constant(value):
        raise ValueError(f'nonfinite JSON: {value}')
    result = json.loads(data, object_pairs_hook=pairs, parse_constant=constant)
    def finite(value):
        if isinstance(value, float) and not math.isfinite(value):
            raise ValueError('nonfinite number')
        if isinstance(value, dict):
            for v in value.values(): finite(v)
        if isinstance(value, list):
            for v in value: finite(v)
    finite(result)
    return result

def encoded(value):
    return (json.dumps(value, indent=2, sort_keys=True, allow_nan=False)+'\n').encode()

def safe_path(value):
    if not isinstance(value, str) or not value or '\\' in value or ':' in value:
        raise ValueError(f'not a portable relative path: {value!r}')
    parts = PurePosixPath(value).parts
    if value.startswith('/') or any(x in ('..', '.') for x in parts) or str(PurePosixPath(value)) != value:
        raise ValueError(f'unsafe path: {value!r}')
    return value

def contained(base, name):
    safe_path(name)
    path = base / name
    if not path.resolve().is_relative_to(base.resolve()) or path.is_symlink():
        raise ValueError(f'path escape/symlink: {name}')
    return path

def pick(data, keys):
    return {key: data[key] for key in keys if key in data}

def privacy(data):
    # Reject local home/scratch paths, even when embedded in prose or JSON keys.
    patterns = [b'/' + b'Users/', b'/' + b'home/', b'/' + b'private/tmp/']
    if any(pattern in data for pattern in patterns):
        raise ValueError('unredacted local absolute path')

class Builder:
    def __init__(self, root):
        self.root = root.resolve()
        self.sources = {}
        self.outputs = {}
    def read(self, name, scope):
        data = contained(self.root, name).read_bytes()
        self.sources[name] = {'sha256': digest(data), 'bytes': len(data), 'scope': scope,
                              'public_original_availability': 'not_assumed; see bundled derivatives'}
        return data
    def load(self, name, scope):
        return strict(self.read(name, scope))
    def scrub(self, value):
        if isinstance(value, str):
            value = value.replace(str(self.root) + '/', '')
            privacy(value.encode())
            return value
        if isinstance(value, list): return [self.scrub(v) for v in value]
        if isinstance(value, dict): return {self.scrub(k): self.scrub(v) for k,v in value.items()}
        return value
    def put(self, name, value, sources, transformation):
        data = encoded(self.scrub(value))
        self.raw(name, data, sources, transformation)
    def raw(self, name, data, sources, transformation):
        privacy(data)
        self.outputs[name] = (data, {'sources': sources, 'transformation': transformation})
    def exact_gzip(self, name, source):
        data = self.read(source, 'Exact scientific likelihood operand; raw event files excluded')
        strict(data); privacy(data)
        self.outputs[name] = (gzip.compress(data, mtime=0), {
            'sources': [source], 'transformation': 'lossless gzip; original JSON bytes recover exactly',
            'uncompressed_sha256': digest(data)})
    def csv(self, name, rows, sources):
        out = io.StringIO(newline='')
        writer = csv.DictWriter(out, fieldnames=list(rows[0])); writer.writeheader(); writer.writerows(rows)
        self.raw(name, out.getvalue().encode(), sources, 'selected scalar rows; empty cell means unavailable/null, never zero')

def build(root):
    b = Builder(root)
    refpath = f'{CAMPAIGN}/inputs/references-derived/published-limits-52.json'
    references = b.load(refpath, '52 reference-matched published observed/median-expected cross-section limits; not author lattice')
    b.put('published-limits-52.json', references, [refpath], 'JSON reformat only')
    publicflowpath = f'{CAMPAIGN}/inputs/references-derived/cutflows-m150-m140.json'
    b.put('public-cutflows-m150-m140.json', b.load(publicflowpath, 'Published raw counts versus weighted 140/fb yields; uncertainties not supplied'), [publicflowpath], 'JSON reformat only; raw and weighted columns remain distinct')
    acceptancepath = f'{CAMPAIGN}/inputs/references-derived/acceptance-efficiency-52.json'
    b.put('public-acceptance-efficiency-52.json', b.load(acceptancepath, 'Figure 32 numerical factors; algebraic product is not a resolved physical comparison definition'), [acceptancepath], 'JSON reformat only; null definitions and uncertainties preserved')
    for suffix in 'abcdef':
        b.read(f'{CAMPAIGN}/inputs/reference/figure_32{suffix}.yaml', 'Primary numerical acceptance/efficiency table; source units and row preserved in derived reference')
    point = next(p for p in references['points'] if p['point_id'] == 'm150_m140')
    inclusivepath = f'{CAMPAIGN}/outputs/inclusive-normalization/summary.json'
    inclusive = b.load(inclusivepath, 'Separate bound inclusive four-state LO generation control; only four prefix stages completed')
    inclusive = pick(inclusive, ['schema_version','kind','status','scope','process','rate','subprocesses','events','settings','generator','verification','limitations'])
    b.put('inclusive-normalization.json', inclusive, [inclusivepath], 'Selected rate/process/event checks; historical table comparison omitted')
    for suffix in ['outputs/inclusive-normalization/manifest.json','outputs/inclusive-normalization/extract_control.py','inputs/references-derived/source-pins.json','inputs/reference/slepton_xsec_UL.yaml']:
        path = f'{CAMPAIGN}/{suffix}'
        if (root/path).is_file(): b.read(path, 'Upstream source evidence pin; retained original not bundled')
    b.exact_gzip('likelihood/background.json.gz', f'{CAMPAIGN}/inputs/reference/background-official.json')
    b.exact_gzip('likelihood/official-m150-m140-patch.json.gz', f'{CAMPAIGN}/inputs/references-derived/official-patches/m150_m140.json')
    anchorbase=f'{CAMPAIGN}/runs/nominal_m150_dm10_20k'
    configpath=f'{anchorbase}/config.toml'
    original_config=b.read(configpath,'Original completed anchor configuration; only two path fields changed in public template')
    config=tomllib.loads(original_config.decode())
    replacements={'statistics_python':'/ABSOLUTE/PATH/TO/JAX_PYTHON','likelihood':'inputs/background-official.json'}
    template=original_config.decode()
    for key,value in replacements.items():
        template,count=re.subn(r'(?m)^'+key+r' = "[^"\n]*"$',key+' = "'+value+'"',template)
        if count!=1:raise ValueError('Unexpected original configuration path field')
    b.raw('recipe/config.toml.template',template.encode(),[configpath],'Only statistics_python and likelihood path values replaced; all other original config bytes preserved')
    preserved=copy.deepcopy(config)
    del preserved['ravel']['native']['statistics_python'];del preserved['ravel']['native']['inputs']['likelihood']
    cards={}
    for name in ['process.dat','param.dat','run.dat','shower.cfg','detector.tcl']:
        source=f'{anchorbase}/inputs/cards/{name}';data=b.read(source,'Exact completed anchor physics card; no tuning or path edits')
        destination=f'recipe/inputs/cards/{name}'
        b.raw(destination,data,[source],'byte-for-byte copy')
        cards[destination]={'source':source,'sha256':digest(data)}
    b.put('recipe/recipe.json',{'schema_version':1,'compute_authorized':False,'physics_certified':False,
        'original_config_source':configpath,'original_config_sha256':digest(original_config),
        'original_config_except_two_relocated_paths':preserved,'template_replacements':replacements,'cards':cards,
        'scope':'Reconstruction of the explicit 20k anchor recipe after separately documented native/JAX setup; not a full environment lock, approval, or bitwise reproduction.',
        'binary_difference':'Frozen anchor used the original six-decimal RISR serializer. Current native source has the separately tested round-trip-precision change; exact anchor binary is not bundled.'},[configpath]+[v['source'] for v in cards.values()], 'Exact card inventory plus path-only configuration transformation declaration')
    rate = inclusive['rate']['cross_section_pb']
    results = {}; channels = []; cutflows = []; shape = {}; responses = {}; provenance = {}; reco_diagnostics = {}
    channel_sources = []; cutflow_sources = []; response_sources = []
    for label, (run, n_events, shape_label) in RUNS.items():
        base = f'{CAMPAIGN}/runs/{run}'
        fitpath = f'{base}/output/exclusion.json'
        fit = b.load(fitpath, 'Saved asymptotic six-root result; no refit during curation')
        fit.pop('execution_provenance', None)
        b.put(f'fits/{label}.json', fit, [fitpath], 'Drop execution_provenance containing local paths; preserve all numerical fit/scan records')
        normpath = f'{base}/output/normalization.json'
        norm = b.load(normpath, 'Native tagged 1-ME-jet LO rate and original exposure; not inclusive rate')
        metapath = f'{base}/output/signal_model.json'
        meta = b.load(metapath, 'Signal model, all 32 SR + 6 CR moments, opt-in shapesys policy')
        b.put(f'likelihood/{label}-signal-model.json', meta, [metapath], 'JSON reformat and repository-root prefix removal; source bytes separately pinned')
        b.exact_gzip(f'likelihood/{label}-patch.json.gz', f'{base}/output/EwkCompressed2018_patch.json')
        statepath = f'{base}/execution_state.json'
        state = b.load(statepath, 'Retained complete execution ledger; curation checks recorded statuses, not full raw ancestry replay')
        stages = state['stages']
        if set(stages) != set(STAGES) or any(stages[s]['status'] != 'succeeded' for s in STAGES):
            raise ValueError(f'{label}: incomplete recorded execution')
        receipts = []
        raw = []
        for s in STAGES:
            stage = stages[s]
            record_path = Path(stage['attempt_record'])
            if not record_path.is_absolute(): record_path = root/base/record_path
            rel = record_path.relative_to(root).as_posix()
            record = b.load(rel, 'Retained stage attempt record; path/approval content not bundled')
            if record['receipt_sha256'] != stage['receipt_sha256'] or record['status'] != 'succeeded':
                raise ValueError('ledger / attempt disagreement')
            receipts.append(pick(stage, ['stage','status','attempt_id','fingerprint','receipt_sha256','started_utc','finished_utc','exit_code']))
            for name, snapshot in stage.get('output_snapshot', {}).items():
                if any(x in name for x in ('.root','.hepmc','.lhe','.jsonl','.csv','native_objects')):
                    raw.append({'stage': s, 'path': b.scrub(name), 'recorded_snapshot': snapshot})
        provenance[label] = {'run': base, 'stages': receipts, 'nonbundled_event_artifacts': raw,
            'raw_custody_scope': 'Hashes are retained receipt assertions; curation does not rehash large raw ancestors. Public readers cannot replay missing event data.',
            'fit_command': b.scrub(stages['pyhf']['command']),
            'supervisor_runtime_is_not_fit_interpreter': True}
        k = norm['kfactor']
        scale_fb = rate * k * 1000
        sigma_obs = fit['obs_limit'] * scale_fb
        sigma_exp = fit['exp_limits'][2] * scale_fb
        results[label] = {'run': base, 'generated_events': n_events, 'recorded_completed_stages': len(receipts),
            'model': 'four-state selectron-L/R and smuon-L/R, m(parent)=150 GeV, m(LSP)=140 GeV',
            'native_tagged_lo_cross_section_pb': norm['cross_section_pb'], 'kfactor': k,
            'luminosity_pb_inverse': meta['luminosity_pb_inverse'],
            'inclusive_reference_lo_cross_section_pb': rate, 'inclusive_reference_times_k_fb': scale_fb,
            'observed_mu95': fit['obs_limit'], 'expected_mu95': fit['exp_limits'],
            'conditional_observed_sigma95_fb': sigma_obs, 'conditional_median_expected_sigma95_fb': sigma_exp,
            'published_observed_sigma95_fb': point['observed_sigma95_fb'],
            'published_median_expected_sigma95_fb': point['median_expected_sigma95_fb'],
            'observed_relative_residual': sigma_obs / point['observed_sigma95_fb'] - 1,
            'median_expected_relative_residual': sigma_exp / point['median_expected_sigma95_fb'] - 1,
            'limit_status': fit['limit_status'], 'inference': fit['inference'],
            'conditional_conversion': 'mu95 * bound inclusive four-state LO pb * declared K * 1000 fb/pb. No additional luminosity correction, no official-template luminosity assumption.',
            'physics_certified': False}
        dpath = f'{REVIEW}/shape-likelihood/{shape_label}/diagnosis.json'
        d = b.load(dpath, 'Actual ROOT channel moments reconciled to native template, full published channel denominator')
        channel_sources.append(dpath)
        for row in d['channels']:
            channels.append({'sample': label, **{k:v for k,v in row.items() if not k.startswith(('fixed_background','delta_fixed'))}})
        groups = {name: {k:v for k,v in row.items() if not k.startswith(('fixed_background','explicit_shape'))} for name,row in d['groups'].items()}
        for group in groups.values():
            group['uniform_positive_weight_relative_mc_error'] = 1 / math.sqrt(group['selected_nonzero']) if group['selected_nonzero'] else None
        shape[label] = {'groups': groups, 'checks': d['checks'], 'normalization_basis': d['normalization_basis'],
                        'official_uncertainty_boundary': d['official_uncertainty_boundary'],
                        'covariance_scope': d['covariance']['interpretation']}
        flowpath = f'{base}/output/compressed_validation.json'
        flow = b.load(flowpath, 'Native all-event cumulative predicates; unknown public stages preserved')
        cutflow_sources.append(flowpath)
        for arm, rows in flow['cutflows'].items():
            for row in rows:
                cutflows.append({'sample': label,'arm': arm, **pick(row,['predicate','count','sumw_pb','sumw2_pb2','unknown_count']),
                    'conditional_status':row['conditional']['status'],'conditional_ratio':row['conditional'].get('ratio'),
                    'conditional_mc_standard_error':row['conditional'].get('mc_standard_error')})
        results[label]['native_comparison_status'] = pick(flow,['truth_acceptance','input_population_status','earliest_unrepresented_reference_stage','comparison_status','unknown_reference_predicates'])
        responsepath = f'{REVIEW}/truth-reco-response-v1/{label}/truth_reco_response.json'
        response = b.load(responsepath, 'Full raw Delphes population, bare-direct-lepton ancestry and same-event TRef/native joins')
        response_sources.append(responsepath)
        responses[label] = pick(response,['schema_version','status','four_state_population_status','four_state_violating_events','physics_certified','input_events','particle_entries','raw_weights','signed_weight_caution','root_slepton_counts_both_charges','topology','reco_origin_counts','total_response','definitions','native_join_status','reader_runtime'])
        if response['input_events'] != n_events: raise ValueError('event denominator disagreement')
        recopath = f'{CAMPAIGN}/outputs/{label}-reco-fraction-diagnostic.json'
        reco = b.load(recopath, 'Conditional inclusive-rate-weighted reconstructed fraction versus unresolved public algebraic A times efficiency')
        for source in reco['inputs']:
            relative = Path(source['path']).relative_to(root).as_posix()
            if digest(b.read(relative, 'Pinned operand of reconstructed-fraction diagnostic')) != source['sha256']:
                raise ValueError('Reconstructed-fraction input changed')
        producer = f'{CAMPAIGN}/build/compare_reco_efficiency.py'
        if digest(b.read(producer, 'Reconstructed-fraction producer, read-only; not rerun during curation')) != reco['engine_sha256']:
            raise ValueError('Reconstructed-fraction producer changed')
        reco_diagnostics[label] = reco
    b.csv('channels.csv', channels, channel_sources)
    b.csv('native-cutflows.csv', cutflows, cutflow_sources)
    b.put('shape-diagnostics.json', shape, channel_sources, 'Selected channel-group diagnostics; prepared omission controls are not reported as executed fits')
    b.put('truth-response.json', responses, response_sources, 'Selected all-population definitions/totals; raw event rows and two-dimensional matrices omitted')
    b.put('reco-fraction-diagnostics.json', reco_diagnostics, [f'{CAMPAIGN}/outputs/{label}-reco-fraction-diagnostic.json' for label in RUNS], 'Repository-root prefix removal; original-rate, selected-population and public-product source pins checked')
    for dest, src in [('response-by-pt.csv','truth-reco-response-v1/response-by-pt.csv'),('figures/response-by-pt.png','truth-reco-response-v1/response-by-pt.png'),('figures/sr-normalized-shapes.png','shape-likelihood/sr-normalized-shapes.png')]:
        path=f'{REVIEW}/{src}'; b.raw(dest,b.read(path,'Existing diagnostic figure/table, exact bytes; not regenerated during curation'),[path],'byte-for-byte copy')
    diag = {}
    diagnostic_names = [('btag','btag-working-point/audit.json'),('btag_transfer','btag-working-point/check_transfer.json'),('risr','risr-differential/summary.json'),('risr_serialization_candidate','risr-differential/candidate-verification.json'),('signal_units','check_signal_units.json'),('independent_fixed_parameter_review','waypoint-independent/check_fixed.json'),('independent_reference_review','waypoint-independent/reference-agreement.json'),('independent_smoke_truth_review','truth-response-independent/verification.json')]
    for key, name in diagnostic_names:
        path=f'{REVIEW}/{name}'; data=b.load(path,'Scoped existing diagnosis/review; no fresh physics execution during curation')
        diag[key]=data
    b.put('diagnostics.json',diag,[f'{REVIEW}/{n}' for _,n in diagnostic_names], 'Repository-root prefix removal; existing check results retained, not newly performed')
    for name in ['btag-working-point/source-pins.json','btag-working-point/review.md','risr-differential/README.md','truth-reco-response-v1/manifest.json','shape-likelihood/verification.json','waypoint-independent/check_fixed.py','check_signal_units.py']:
        path=f'{REVIEW}/{name}';b.read(path,'Diagnostic implementation/primary-source lineage, not copied external implementation')
    # Include primary-source URLs and hashes without distributing external source code.
    srcpath=f'{REVIEW}/btag-working-point/source-pins.json'
    b.put('btag-source-pins.json', strict(b.read(srcpath,'Primary-source location/byte pins; calibration remains unresolved')), [srcpath], 'Repository-root prefix removal only')
    result={'schema_version':1,'kind':'bounded_completed_anchor_waypoint','as_of':'2026-09-06',
        'analysis':'ATLAS-SUSY-2018-16 / EwkCompressed2018', 'results':results,
        'reference_point':point,'reference_matched_denominator':52,'new_mass_points_in_this_bundle':1,
        'expected_public_family':'median only; no expected uncertainty bands supplied',
        'claim_status':{'recorded_twelve_stage_completion':'both samples','six_root_numerical_checks':'resolved in both saved fits',
            'all_event_local_diagnostics':'1000/1000 and 20000/20000; summaries bound to retained inputs',
            'public_raw_event_custody':'not_reproducible_from_bundle_raw_events_not_distributed',
            'atlas_truth_acceptance':'unscorable_definition_and_required_truth_objects_unresolved',
            'official_template_normalization':'luminosity_and_cross_section_not_assigned',
            'five_percent_own_mc_target':'not_met; zero-selected bins precision unresolved',
            'btag_85_mv2c10_response':'generic_boolean_transport_confirmed_target_calibration_unresolved',
            'physics_or_coverage_certificate':'none','full_fresh_mass_plane':'not_completed'},
        'omitted_work':'Subsequent replicas, unfinished work, raw events, binaries and private authorization records are outside this completed waypoint.',
        'uncertainty_scope':'Generator integration uncertainty is separate from Poissonized independent-event signal MC constraints; no detector/ISR/theory/coverage validation.'}
    b.put('waypoint.json',result,[refpath,inclusivepath]+[f'{CAMPAIGN}/runs/{v[0]}/output/exclusion.json' for v in RUNS.values()], 'Conditional unit conversion and explicitly scoped completion/diagnosis summary')
    b.put('execution-provenance.json',provenance,[f'{CAMPAIGN}/runs/{v[0]}/execution_state.json' for v in RUNS.values()], 'Selected statuses/receipt assertions; no private approval content, absolute home paths, or raw event bytes')
    b.put('source-provenance.json',{'schema_version':1,'sources':b.sources,'scope':'Exact original small-file byte hashes checked during curation. Source originals may be private/local or external and are not implied to ship. Nonbundled raw-event hashes are separately labelled retained receipt assertions.'},list(b.sources),'Inventory of actually read source bytes; unavailable raw external custody explicitly excluded')
    for name, (data, _) in b.outputs.items():
        path=contained(HERE,name);path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(data)
    files={}
    for path in sorted(HERE.rglob('*')):
        if not path.is_file() or path.name=='manifest.json' or '__pycache__' in path.parts: continue
        name=path.relative_to(HERE).as_posix();data=path.read_bytes()
        files[name]={'sha256':digest(data),'bytes':len(data),**b.outputs.get(name,(None,{'sources':[],'transformation':'authored public documentation or verification code'}))[1]}
    (HERE/'manifest.json').write_bytes(encoded({'schema_version':1,'files':files,'scope':'Bundle integrity, not a signature, external provenance proof or physics certificate.'}))
    return verify(HERE,root)

def verify(folder, source_root=None):
    manifest=strict((folder/'manifest.json').read_bytes())
    if manifest.get('schema_version') != 1: raise ValueError('manifest version')
    expected=set(manifest['files'])|{'manifest.json'}
    actual={p.relative_to(folder).as_posix() for p in folder.rglob('*') if p.is_file() and '__pycache__' not in p.parts}
    if actual != expected: raise ValueError('unlisted/missing bundle files')
    for name,record in manifest['files'].items():
        data=contained(folder,name).read_bytes()
        if digest(data)!=record['sha256'] or len(data)!=record['bytes']:raise ValueError(f'byte mismatch: {name}')
        if name.endswith('.gz'):
            data=gzip.decompress(data)
            if digest(data)!=record['uncompressed_sha256']:raise ValueError(f'gzip source mismatch: {name}')
        if not name.endswith('.png'): privacy(data)
        if name.endswith(('.json','.json.gz')):strict(data)
    load=lambda name:strict((folder/name).read_bytes())
    waypoint=load('waypoint.json');refs=load('published-limits-52.json');inc=load('inclusive-normalization.json')
    if len(refs['points'])!=52 or len({p['point_id'] for p in refs['points']})!=52:raise ValueError('reference denominator')
    points=[p for p in refs['points'] if p['point_id']=='m150_m140']
    if len(points)!=1 or waypoint['reference_point']!=points[0]:raise ValueError('reference point binding')
    if any(points[0].get(k)!=v for k,v in [('m_parent_GeV',150),('m_lsp_GeV',140),('delta_m_GeV',10)]):
        raise ValueError('reference point coordinates')
    provenance=load('execution-provenance.json');responses=load('truth-response.json');shapes=load('shape-diagnostics.json')
    reco=load('reco-fraction-diagnostics.json');acceptance=load('public-acceptance-efficiency-52.json')
    if acceptance['certified'] or acceptance['native_truth_comparison_eligible'] or len(acceptance['points'])!=52:
        raise ValueError('unsupported acceptance certification/denominator')
    acceptance_points=[p for p in acceptance['points'] if p['point_id']=='m150_m140']
    if len(acceptance_points)!=1:raise ValueError('acceptance point binding')
    acceptance_point=acceptance_points[0]
    if any(acceptance_point[k]!=points[0][k] for k in ('m_parent_GeV','m_lsp_GeV','delta_m_GeV')):
        raise ValueError('acceptance coordinate binding')
    if {p['point_id'] for p in acceptance['points']}!={p['point_id'] for p in refs['points']}:
        raise ValueError('acceptance reference subset mismatch')
    close=lambda a,b:math.isclose(a,b,rel_tol=1e-12,abs_tol=1e-12)
    for label,(_,n,_) in RUNS.items():
        result=waypoint['results'][label];fit=load(f'fits/{label}.json');response=responses[label]
        resolved={'observed':'resolved','expected':['resolved']*5}
        if fit.get('limit_status')!=resolved or result.get('limit_status')!=resolved:
            raise ValueError('six resolved limit statuses required in fit and summary')
        if result['observed_mu95']!=fit['obs_limit'] or result['expected_mu95']!=fit['exp_limits']:
            raise ValueError('fit and summary limits differ')
        if result['physics_certified'] or response['physics_certified']:raise ValueError('unsupported certificate')
        if result['generated_events']!=n or response['input_events']!=n:raise ValueError('population mismatch')
        stages=provenance[label]['stages']
        if [s['stage'] for s in stages]!=STAGES or any(s['status']!='succeeded' or s['exit_code']!=0 for s in stages):raise ValueError('completion mismatch')
        scale=inc['rate']['cross_section_pb']*result['kfactor']*1000
        if not close(scale,result['inclusive_reference_times_k_fb']):raise ValueError('rate algebra')
        point=waypoint['reference_point']
        for kind,mu,reference in [('observed',fit['obs_limit'],point['observed_sigma95_fb']),('median_expected',fit['exp_limits'][2],point['median_expected_sigma95_fb'])]:
            if not close(mu*scale,result[f'conditional_{kind}_sigma95_fb']) or not close(mu*scale/reference-1,result[f'{kind}_relative_residual']):raise ValueError('limit conversion')
        if fit['inference']['fresh_check_evaluations']!=16 or fit['inference']['root_cls_max_error']>fit['inference']['root_cls_atol']:raise ValueError('saved root check failed')
        rows=list(csv.DictReader((folder/'channels.csv').open()));rows=[r for r in rows if r['sample']==label]
        if len(rows)!=38:raise ValueError('channel denominator')
        for group, selection in [('SR-all',[r for r in rows if r['group']!='CR']),('CR',[r for r in rows if r['group']=='CR'])]:
            if not close(sum(float(r['native_yield']) for r in selection),shapes[label]['groups'][group]['native_yield']):raise ValueError('channel sum')
            if sum(int(r['native_selected_nonzero']) for r in selection)!=shapes[label]['groups'][group]['selected_nonzero']:raise ValueError('selected denominator')
        for row in rows:
            if row['official_raw_selected_count'] or row['official_raw_sumw2']:raise ValueError('invented public raw moments')
            if not close(float(row['native_yield']),float(row['native_sumw_pb'])*result['luminosity_pb_inverse']):raise ValueError('channel normalization')
            if not close(float(row['native_mc_error'])**2,float(row['native_sumw2_pb2'])*result['luminosity_pb_inverse']**2):raise ValueError('channel variance')
        diagnostic=reco[label]
        if diagnostic['physics_certified'] or diagnostic['masses_gev']!=[150,140]:raise ValueError('reco diagnostic scope')
        if not close(diagnostic['generated_four_state_tagged_rate_pb'],result['native_tagged_lo_cross_section_pb']) or not close(diagnostic['inclusive_four_state_rate_pb'],inc['rate']['cross_section_pb']):
            raise ValueError('reco diagnostic rate binding')
        ratio=result['native_tagged_lo_cross_section_pb']/inc['rate']['cross_section_pb']
        if not close(ratio,diagnostic['tagged_to_inclusive_rate_ratio']):raise ValueError('reco diagnostic rate ratio')
        if [r['region'] for r in diagnostic['rows']]!=['SR-S-high','SR-S-low']:raise ValueError('reco region denominator')
        for row in diagnostic['rows']:
            group=row['region'].replace('SR-S-','SR-');selected=shapes[label]['groups'][group]['selected_nonzero']
            reference=acceptance_point['regions'][row['region']]
            a=reference['acceptance']['value']*reference['acceptance']['display_to_fraction']
            e=reference['efficiency']['value']*reference['efficiency']['display_to_fraction']
            product=a*e;fraction=selected/n;error=math.sqrt(fraction*(1-fraction)/n)
            if row['selected_events']!=selected or row['public_uncertainty'] is not None or row['status']!='diagnostic_only_unmatched_truth_and_migration_definition':
                raise ValueError('reco selected population/interpretation')
            expected={'conditional_fraction_in_generated_sample':fraction,'conditional_fraction_mc_standard_error':error,
                'estimated_inclusive_four_state_reco_fraction':ratio*fraction,
                'conditional_sampling_standard_error_on_inclusive_fraction':ratio*error,
                'reference_algebraic_acceptance_efficiency_product':product,
                'central_relative_difference':ratio*fraction/product-1}
            if any(not close(row[k],v) for k,v in expected.items()) or not close(reference['acceptance_times_efficiency_product'],product):
                raise ValueError('reco fraction/product/uncertainty algebra')
    sources=load('source-provenance.json')['sources']
    recipe=load('recipe/recipe.json')
    if recipe['compute_authorized'] or recipe['physics_certified']:raise ValueError('recipe is not an approval/certificate')
    if sources[recipe['original_config_source']]['sha256']!=recipe['original_config_sha256']:raise ValueError('recipe original config pin')
    template=tomllib.loads((folder/'recipe/config.toml.template').read_text())
    if template['ravel']['native'].pop('statistics_python')!=recipe['template_replacements']['statistics_python'] or template['ravel']['native']['inputs'].pop('likelihood')!=recipe['template_replacements']['likelihood']:
        raise ValueError('recipe path replacement')
    if template!=recipe['original_config_except_two_relocated_paths']:raise ValueError('recipe changed non-path settings')
    if set(recipe['cards'])!={f'recipe/inputs/cards/{n}' for n in ('process.dat','param.dat','run.dat','shower.cfg','detector.tcl')}:raise ValueError('recipe card denominator')
    for path,record in recipe['cards'].items():
        if digest(contained(folder,path).read_bytes())!=record['sha256'] or sources[record['source']]['sha256']!=record['sha256']:
            raise ValueError('recipe exact card source binding')
    for diagnostic in reco.values():
        for record in diagnostic['inputs']:
            if record['path'] not in sources or sources[record['path']]['sha256']!=record['sha256']:
                raise ValueError('reco input source pin disagreement')
    for name,record in sources.items():
        safe_path(name)
        if not re.fullmatch('[a-f0-9]{64}',record['sha256']):raise ValueError('invalid source hash')
        if source_root is not None:
            data=contained(source_root,name).read_bytes()
            if digest(data)!=record['sha256']:raise ValueError(f'original source mismatch: {name}')
    return {'status':'PASS','bundle_files':len(manifest['files']),'source_files':len(sources),'original_small_sources_checked':source_root is not None,'large_raw_event_files_rehashed':False,'physics_certified':False}

def units(folder):
    """Optional fixed-parameter identity only. No fit/optimizer is invoked."""
    import numpy as np
    import jsonpatch
    import pyhf
    pyhf.set_backend('numpy',precision='64b')
    background=strict(gzip.decompress((folder/'likelihood/background.json.gz').read_bytes()))
    patch=strict(gzip.decompress((folder/'likelihood/anchor20k-patch.json.gz').read_bytes()))
    meta=strict((folder/'likelihood/anchor20k-signal-model.json').read_bytes())
    spec=jsonpatch.apply_patch(background,patch,in_place=False)
    settings={'normsys':{'interpcode':'code4'},'histosys':{'interpcode':'code4p'}}
    w=pyhf.Workspace(spec);model=w.model(modifier_settings=settings);data=w.data(model)
    if not np.all(np.isfinite(data)):raise ValueError('nonfinite original auxiliary/observed data')
    init=np.array(model.config.suggested_init(),dtype=float);bounds=model.config.suggested_bounds();fixed=model.config.suggested_fixed();rng=np.random.default_rng(20260905);points=[]
    for mu in (0,.01,.2,.35,.7,1.5):
        for varied in range(3):
            p=init.copy()
            if varied:p+=rng.normal(0,.05,len(p))
            for i,(lo,hi) in enumerate(bounds):p[i]=min(max(p[i],lo+1e-4),hi-1e-4)
            for i,is_fixed in enumerate(fixed):
                if is_fixed:p[i]=init[i]
            p[model.config.poi_index]=mu;points.append(p)
    def scaled(factor,errors=True):
        changed=copy.deepcopy(spec)
        for channel in changed['channels']:
            for sample in channel['samples']:
                if sample['name']!=meta['sample']:continue
                sample['data']=[x*factor for x in sample['data']]
                for mod in sample['modifiers']:
                    if mod['type'] in ('shapesys','staterror'):
                        if errors:mod['data']=[x*factor for x in mod['data']]
                    elif mod['type'] not in ('normfactor','normsys'):raise ValueError('unsupported signal modifier')
        w=pyhf.Workspace(changed);return w,w.model(modifier_settings=settings)
    results=[]
    for factor in (.5,2.,3.907):
        cw,cm=scaled(factor);cd=cw.data(cm)
        if not np.all(np.isfinite(cd)):raise ValueError('nonfinite transformed auxiliary/observed data')
        if model.config.par_order!=cm.config.par_order or not np.allclose(data,cd,rtol=1e-12,atol=1e-10):raise ValueError('unit constraint mismatch')
        me=mn=0.
        for p in points:
            q=p.copy();q[cm.config.poi_index]/=factor
            original_expected=np.asarray(model.expected_data(p));transformed_expected=np.asarray(cm.expected_data(q))
            original_nll=np.asarray(pyhf.infer.mle.twice_nll(p,data,model));transformed_nll=np.asarray(pyhf.infer.mle.twice_nll(q,cd,cm))
            if not all(np.all(np.isfinite(x)) for x in (original_expected,transformed_expected,original_nll,transformed_nll)):
                raise ValueError('nonfinite fixed-parameter evaluation')
            ed=float(np.max(np.abs(original_expected-transformed_expected)))
            nd=float(np.max(np.abs(original_nll-transformed_nll)))
            if not math.isfinite(ed) or not math.isfinite(nd):raise ValueError('nonfinite identity difference')
            me=max(me,ed);mn=max(mn,nd)
        if me>1e-10 or mn>1e-9:raise ValueError('fixed-parameter identity failed')
        results.append({'scale':factor,'parameter_points':len(points),'max_expected_absolute_error':me,'max_twice_nll_absolute_error':mn})
    nw,nm=scaled(2,False);negative_data=np.asarray(nw.data(nm))
    if not np.all(np.isfinite(negative_data)):raise ValueError('nonfinite negative-control data')
    negative=float(np.max(np.abs(negative_data-data)))
    if not math.isfinite(negative):raise ValueError('nonfinite negative-control difference')
    if negative<=1:raise ValueError('negative control did not discriminate')
    return {'status':'PASS','channels':len(model.config.channels),'parameters':model.config.npars,'checks':results,'negative_control_auxdata_difference':negative,'scope':'18 parameter points x 3 scales; no fit, CLs recomputation, domain equivalence or physics certificate'}

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--rebuild',action='store_true',help='recreate derived files from retained source root')
    parser.add_argument('--source-root',type=Path,help='explicit retained checkout; checks original small files, not raw event ancestors')
    parser.add_argument('--units',action='store_true',help='also run optional pyhf fixed-parameter identity, never a fit')
    args=parser.parse_args()
    if args.rebuild and args.source_root is None:parser.error('--rebuild requires --source-root')
    try:
        result=build(args.source_root.resolve()) if args.rebuild else verify(HERE,args.source_root.resolve() if args.source_root else None)
        if args.units:result['fixed_parameter_units']=units(HERE)
    except (ValueError,KeyError,OSError,TypeError) as exc:
        print(f'FAIL: {exc}',file=sys.stderr);return 1
    print(json.dumps(result,indent=2));return 0

if __name__=='__main__':raise SystemExit(main())
