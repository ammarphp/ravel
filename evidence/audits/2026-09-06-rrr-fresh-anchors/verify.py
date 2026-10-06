#!/usr/bin/env python3
"""Offline integrity and arithmetic only. No event reader or model fitting dependency."""
from pathlib import Path
import argparse, csv, hashlib, io, json, math, runpy
HERE=Path(__file__).resolve().parent
C=runpy.run_path(str(HERE/'curate.py'))
ORIGINAL_SOURCES=C['ORIGINAL_SOURCES']; strict=C['strict']; safe=C['safe']; encoded=C['encoded']; digest=C['digest']
QUANTILES=C['QUANTILES']; POINTS=C['POINTS']
# Fixed data projections are independent of the mutable transport manifest.
PROJECTION_SHA256 = {'data/evidence.json': '98c2db1c8b4f3775eede4d4195633c249364f84a7f203525c633cd6ecb42a0f3', 'tables/limits.csv': '488c1653d1dd8d2160dc2150595b37f2e0a71ae0013c3ef2d157f9cb3d563401', 'tables/channel-moments.csv': 'd36eb2de2349a7c5aacbb58f71cf411818e36ff8395ecb0d1b7dceb72fa746bd', 'source-map.json': '06de9fba532ea6c9b38be8b82c64352ceac2e7254192be58d6d8931037724b04', 'figures/fresh-anchor-diagnostics.png': 'eae8f0a361759a5e6fb959574477e77fc1bf1d3e02a3058854de01ea6f1f1d68', 'figures/fresh-anchor-diagnostics.pdf': '8b661c86e06df263da108c781a90f0d7845c203d338eab5955d8bfeada33508b', 'tables/anchors.csv': '8f128a8d6bc83f185e5b5f807df7940a15bf3178eab2ac0ec85828a731c5d345', 'tables/fractions.csv': 'dd2cc57731c422e3f0aebb18bdc030ce23baecdb843eaf05c01e2467c195bbd4'}
STAGES=sorted(['prepare','madgraph','unpack_lhe','lhe_check','pythia','normalization','delphes','analysis','simpleanalysis','sa2json','pyhf','native_report'])
CHANNELS=sorted([f'CR{x}_MT2_{y}met_cuts' for x in ('VV','tau','top') for y in ('hgh','low')]+[f'SR{f}_eMT2{b}_{s}' for f in ('ee','mm') for b in 'abcdefgh' for s in ('hghmet_cuts','lowmet_V2_cuts')])

def require(ok,message):
    if not ok: raise ValueError(message)
def same(a,b,message): require(json.dumps(a,sort_keys=True,allow_nan=False)==json.dumps(b,sort_keys=True,allow_nan=False),message)
def number(x):
    require(type(x) in (int,float) and math.isfinite(x),'Nonfinite or nonnumeric operand')
    return x
def close(a,b,message,rtol=2e-11,atol=1e-24): require(math.isclose(number(a),number(b),rel_tol=rtol,abs_tol=atol),message)
def integer(x,minimum=0): require(type(x) is int and x>=minimum,'Invalid count'); return x

def validate_evidence(e):
    require(set(e)=={'schema_version','scope','anchors','fractions','preserved_failures','independent_review_roles'},'Evidence roles')
    same(e['schema_version'],1,'Schema')
    expected_scope={'physics_certified':False,'acceptance_certified':False,'coverage_validated':False,'raw_payloads_included':False,'raw_payloads_reread':False,'new_events':0,'new_fits':0,'nominal_points_completed':3,'nominal_points_total':52,'remaining_nominal_points_uncompleted':49,'reference_errors_supplied':False,'reference_truth_denominator_resolved':False,'reference_migration_resolved':False,'precision_checkpoint':'Formal 5% histogram-MC primary checkpoint is 150/140; 50/45 and100/98 comparisons are analogous diagnostics, not new preregistered gates.'}
    same(e['scope'],expected_scope,'Scope promotion or missingness change')
    require(len(e['anchors'])==3,'Anchor population')
    expected_counts={50:(24,33,17),100:(59,11,22),150:(616,487,11)}
    expected_inc={50:(8.7316,.02029),100:(.574784,.001589),150:(.1350625,.0003703)}
    for a,(mass,lsp,row_index) in zip(e['anchors'],POINTS):
        same([a['parent_GeV'],a['lsp_GeV'],a['delta_m_GeV']],[mass,lsp,mass-lsp],'Mass point')
        require(a['point_id']==f'm{mass}_m{lsp}','Point label')
        same(a['original_events'],60000 if mass==150 else 20000,'Original denominator')
        N=integer(a['original_events'],1);inc=a['inclusive'];K=a['native']['K']
        same(inc['original_events'],1000,'Inclusive original exposure');close(K,1.18,'K applied once')
        close(inc['sigma_lo_pb'],expected_inc[mass][0],'Own mass-specific inclusive rate');close(inc['integration_error_pb'],expected_inc[mass][1],'Inclusive integration uncertainty')
        close(a['native']['one_parton_sigma_after_K_pb'],K*a['native']['one_parton_sigma_lo_pb'],'Tagged units')
        roots=a['fit_roots'];same(roots['status'],{'observed':'resolved','expected':['resolved']*5},'Six resolved roots required')
        require(len(roots['expected'])==5 and all(number(x)>0 for x in [roots['observed']]+roots['expected']),'Root population')
        require(roots['expected']==sorted(roots['expected']) and len(set(roots['expected']))==5,'Expected order')
        nu=a['numerical'];same(nu['fresh_check_evaluations'],16,'Reported fresh check count');same(nu['coverage_validated'],False,'Numerical scope')
        close(nu['level'],.05,'CLs level');require(0<=number(nu['root_cls_max_error'])<=number(nu['root_cls_atol'])<=.0005,'Numerical tolerance')
        require(nu['method']=='asymptotic CLs' and nu['test_stat']=='qtilde' and nu['precision']=='64b','Numerical method')
        ref=a['reference'];require(ref['point_id']==a['point_id'],'Reference identity');same(ref['source_row_index'],row_index,'Primary row')
        close(ref['m_parent_GeV'],mass,'Reference parent');close(ref['m_lsp_GeV'],lsp,'Reference LSP');close(ref['delta_m_GeV'],mass-lsp,'Reference splitting')
        same(ref['expected_bands'],None,'Unsupplied bands')
        for v in ref['source_values']:same(v['public_uncertainty'],None,'Unsupplied reference error')
        primary=a['primary_limit_rows'];require(len(primary)==4,'Primary columns')
        require(all('units: pb' in x['header'] for x in primary[:2]) and all('units: GeV' in x['header'] for x in primary[2:]),'Primary units')
        close(primary[2]['value'],mass,'Primary parent coordinate');close(primary[3]['value'],mass-lsp,'Primary delta coordinate')
        close(primary[0]['value'],ref['observed_sigma95_pb'],'Primary observed');close(primary[1]['value'],ref['median_expected_sigma95_pb'],'Primary expected')
        require(len(a['limits'])==6,'Six quantiles')
        for i,r in enumerate(a['limits']):
            require(r['quantile']==QUANTILES[i],'Quantile label/order');close(r['mu95'],([roots['observed']]+roots['expected'])[i],'Unchanged dimensionless limit')
            pb=r['mu95']*K*inc['sigma_lo_pb'];close(r['inclusive_sigma95_pb'],pb,'Inclusive limit');close(r['inclusive_sigma95_fb'],pb*1000,'pb/fb conversion')
            close(r['generated_one_parton_sigma95_pb'],r['mu95']*a['native']['one_parton_sigma_after_K_pb'],'Separate generated unit')
            close(r['inclusive_generator_integration_only_error_pb'],r['mu95']*K*inc['integration_error_pb'],'Fixed-mu integration term')
            same(r['public_uncertainty'],None,'No invented reference errors')
            if i in (0,3):
                x=ref['observed_sigma95_pb'] if i==0 else ref['median_expected_sigma95_pb'];close(r['reference_sigma95_pb'],x,'Reference units');close(r['ratio_to_reference'],pb/x,'Reference ratio');close(r['residual_percent'],100*(pb/x-1),'Signed residual');require(r['reference_status']=='supplied_central_only','Reference status')
            else:
                for key in ('reference_sigma95_pb','ratio_to_reference','residual_percent'):same(r[key],None,'Missing expected-band comparison')
                require(r['reference_status']=='expected_band_not_supplied','Missing-band status')
        bins=a['channels'];require([x['channel'] for x in bins]==CHANNELS,'Full ordered 38-channel population')
        require(a['mc_policy']=='shapesys','Retained native MC policy');close(a['luminosity_pb_inverse'],139000,'Native luminosity')
        model=a['model_channel_identity'];require([x['channel'] for x in model]==CHANNELS,'Exact signal-model interface')
        zero=0
        for b,m in zip(bins,model):
            n=integer(b['selected_events']);require(n<=N,'Selected count bound');sw=number(b['sumw_pb']);v=number(b['sumw2_pb2']);require(sw>=0 and v>=0,'Signed/unphysical moment outside declared positive scope')
            same(n,m['nonzero_weights'],'Model count');close(sw,m['sumw'],'Model first moment');close(v,m['sumw2'],'Model second moment');close(b['nominal_yield'],m['nominal_yield'],'Model yield');close(b['nominal_yield'],sw*a['luminosity_pb_inverse'],'Rate/yield basis')
            same(b['likelihood_mc_constraint'],m['mc_stat_modifier'],'Model MC constraint')
            streams=b['streams'];same([s['N'] for s in streams],[20000,40000] if mass==150 else [20000],'Original pool strata')
            require(sum(integer(s['selected']) for s in streams)==n,'Pool count closure')
            predicted_sw=0.;predicted_v=0.
            for s in streams:
                sn=integer(s['N'],1);k=integer(s['selected']);require(k<=sn,'Stream selected bound');close(s['K'],K,'Stratum K')
                sigma=number(s['sigma_pb']);require(sigma>0,'Positive stratum cross section')
                alpha=sn/N;w=K*sigma/sn
                predicted_sw+=alpha*w*k;predicted_v+=alpha**2*w*w*k
                if mass==150:
                    close(s['retained_sumw_pb'],w*k,'Parent retained first moment',rtol=2e-6)
                    close(s['retained_sumw2_pb2'],w*w*k,'Parent retained second moment',rtol=2e-6)
            close(sw,predicted_sw,'Original-exposure first moment',rtol=2e-6);close(v,predicted_v,'Squared pooling second moment',rtol=2e-6)
            if n==0:
                zero+=1;same(b['histogram_relative_mc'],None,'Zero precision unresolved');same(b['likelihood_mc_constraint'],None,'No fake zero-bin constraint');require(sw==v==0 and b['diagnostic_5percent']=='unresolved','Zero moment scope')
            else:
                require(sw>0 and v>0 and isinstance(b['likelihood_mc_constraint'],str),'Positive populated bin');rel=math.sqrt(v)/sw;close(b['histogram_relative_mc'],rel,'Histogram precision');require(b['diagnostic_5percent']==('meets_target' if rel<=.05 else 'exceeds_target'),'Unchanged histogram floor')
        same(zero,expected_counts[mass][2],'Zero-selected channel population')
        same([u['category'] for u in a['unions']],['SR_high','SR_low'],'SR unions')
        for u,region,count in zip(a['unions'],('high','low'),expected_counts[mass][:2]):
            members=[b for b in bins if b['channel'].startswith('SR') and ('hghmet' if region=='high' else 'lowmet') in b['channel']]
            require(len(members)==16,'Disjoint 16-bin union');same(u['selected_events'],count,'Union selected count');same(sum(x['selected_events'] for x in members),count,'Union count closure')
            close(u['sumw_pb'],math.fsum(b['sumw_pb'] for b in members),'Union first moment');close(u['sumw2_pb2'],math.fsum(b['sumw2_pb2'] for b in members),'Union second moment');close(u['histogram_relative_mc'],math.sqrt(u['sumw2_pb2'])/u['sumw_pb'],'Union histogram MC')
        if mass!=150:
            pop=a['inherited_receipt_projection'];require(set(pop)=={'fresh','inclusive'},'Receipt families')
            same([x['stage'] for x in pop['fresh']],STAGES,'Twelve native stage names');same([x['stage'] for x in pop['inclusive']],sorted(['prepare','madgraph','unpack_lhe','lhe_check','inclusive_rate']),'Prefix plus diagnostic, not full native')
            for family,items in pop.items():
                for item in items:
                    role=f"anchor{mass}_{family}_receipt_{item['stage']}";require(item['record_role']==role and role in ORIGINAL_SOURCES,'Mandatory receipt role');require(len(item['receipt_sha256'])==64 and all(c in '0123456789abcdef' for c in item['receipt_sha256']),'Receipt digest')
    require(len(e['fractions'])==6,'Six reconstructed fractions')
    for row,(a,region) in zip(e['fractions'],[(a,g) for a in e['anchors'] for g in ('high','low')]):
        same([row['parent_GeV'],row['lsp_GeV'],row['region']],[a['parent_GeV'],a['lsp_GeV'],region],'Fraction coordinates');same(row['original_events'],a['original_events'],'Fraction original exposure')
        u=a['unions'][0 if region=='high' else 1];same(row['selected_events'],u['selected_events'],'Fraction selected count');close(row['selected_rate_after_K_pb'],u['sumw_pb'],'Fraction numerator')
        inc=a['inclusive'];K=a['native']['K'];close(row['inclusive_LO_pb'],inc['sigma_lo_pb'],'Fraction own inclusive denominator');close(row['K'],K,'Fraction K');den=K*inc['sigma_lo_pb'];F=u['sumw_pb']/den
        close(row['inclusive_reco_fraction'],F,'K-cancelling fraction')
        fref=a['fraction_reference'];require(fref['point_id']==a['point_id'],'Fraction reference identity')
        ref=fref['regions']['SR-S-'+region];letters='cd' if region=='high' else 'ef'
        values=[]
        for kind,letter,factor in zip(('acceptance','efficiency'),letters,(.001,1.)):
            primary=a['primary_fraction_rows'][letter];require(len(primary)==3,'Primary fraction table roles');close(primary[1]['value'],a['parent_GeV'],'Fraction primary parent');close(primary[2]['value'],a['delta_m_GeV'],'Fraction primary splitting')
            require(('10^{-3}' in primary[0]['header']) if factor==.001 else ('Efficiency' in primary[0]['header']),'Fraction display unit')
            close(ref[kind]['display_to_fraction'],factor,'Primary unit factor');close(ref[kind]['source_row_index'],a['reference']['source_row_index'],'Fraction source index');require(ref[kind]['source_file']=='figure_32'+letter+'.yaml','Fraction table role');close(ref[kind]['value'],primary[0]['value'],'Primary fraction value');same(ref[kind]['public_uncertainty'],None,'Reference fraction uncertainty');values.append(primary[0]['value']*factor)
        close(row['public_acceptance_fraction'],values[0],'Acceptance scale');close(row['public_efficiency_fraction'],values[1],'Efficiency scale');product=values[0]*values[1];close(row['public_algebraic_product'],product,'Algebraic reference');close(row['central_residual_percent'],100*(F/product-1),'Fraction signed residual');same(row['public_uncertainty'],None,'Fraction error unavailable')
        members=[b for b in a['channels'] if b['channel'].startswith('SR') and ('hghmet' if region=='high' else 'lowmet') in b['channel']]
        variance=0.;N=a['original_events']
        for h in range(len(members[0]['streams'])):
            ss=[b['streams'][h] for b in members];sn=ss[0]['N'];p=sum(s['selected'] for s in ss)/sn;sigma=ss[0]['sigma_pb'];variance+=(sn/N*K*sigma)**2*p*(1-p)/sn
        close(row['fixed_N_conditional_mc_standard_error'],math.sqrt(variance)/den,'Fixed-N stratum variance');close(row['histogram_mc_standard_error'],math.sqrt(u['sumw2_pb2'])/den,'Separate histogram MC');close(row['inclusive_integration_only_standard_error'],F*inc['integration_error_pb']/inc['sigma_lo_pb'],'Fixed-numerator inclusive integration term')
    same(e['independent_review_roles'],['anchor50_review','anchor100_review','anchor150_review','fraction_math_review','fraction_repair_review','figure_review'],'Independent review roles')
    same(e['preserved_failures'],{'fraction_initial_schema_failure':{'source_role':'fraction_initial_failed_reader','log_role':'fraction_initial_failure_log','accepted_science_output':False},'fraction_v1_completion':{'source_role':'fraction_rejected_reader','completion_role':'fraction_rejected_complete','status':'rejected_empty_self_hash','science_unchanged_in_v2':True},'figure_v1':{'source_role':'figure_rejected_renderer','status':'legend_overlapped_footer','v2_change':'legend placement only; CSV unchanged'}},'Preserved failure context')

def verify(root=HERE,source_root=None):
    root=Path(root);require(not root.is_symlink(),'Symlink bundle')
    manifest=strict((root/'manifest.json').read_bytes());same(manifest['schema_version'],1,'Manifest schema');require(set(manifest)=={'schema_version','files'},'Manifest roles')
    files={}
    for p in root.rglob('*'):
        require(not p.is_symlink(),'Symlink bundle member')
        if p.is_file() and p.relative_to(root).as_posix()!='manifest.json':files[p.relative_to(root).as_posix()]=digest(p.read_bytes())
    require(set(files)==set(['README.md', 'curate.py', 'data/evidence.json', 'figures/fresh-anchor-diagnostics.pdf', 'figures/fresh-anchor-diagnostics.png', 'source-map.json', 'source_roles.py', 'tables/anchors.csv', 'tables/channel-moments.csv', 'tables/fractions.csv', 'tables/limits.csv', 'test_verify.py', 'verify.py']),'Exact bundle file roles')
    same(files,manifest['files'],'Exact transport inventory/hashes')
    for name,h in PROJECTION_SHA256.items():require(digest(safe(root,name).read_bytes())==h,'Fixed projection changed: '+name)
    sm=strict((root/'source-map.json').read_bytes());same(sm['original_roles'],ORIGINAL_SOURCES,'Mandatory exact original role/path/hash population');same(sm['copied_artifacts'],C['COPIES'],'Exact copied artifact roles');same(sm['private_execution_context_included'],False,'Private context scope')
    for pin in ORIGINAL_SOURCES.values():safe(Path('.'),pin['path'])
    e=strict((root/'data/evidence.json').read_bytes());validate_evidence(e)
    expected_limits=C['csv_bytes']([{'point_id':a['point_id'],**r} for a in e['anchors'] for r in a['limits']]);require((root/'tables/limits.csv').read_bytes()==expected_limits,'All eighteen CSV limits')
    moments=C['csv_bytes']([{'point_id':a['point_id'],'original_events':a['original_events'],**{k:r[k] for k in ('channel','selected_events','sumw_pb','sumw2_pb2','nominal_yield','histogram_relative_mc','diagnostic_5percent')}} for a in e['anchors'] for r in a['channels']]);require((root/'tables/channel-moments.csv').read_bytes()==moments,'All114 CSV moments')
    fraction=list(csv.DictReader(io.StringIO((root/'tables/fractions.csv').read_text())))
    require(len(fraction)==6,'Fraction CSV count')
    for stored,row in zip(fraction,e['fractions']):
        require(set(stored)==set(row),'Fraction CSV columns')
        for k,v in row.items():
            if v is None:require(stored[k]=='','Fraction CSV missingness')
            elif isinstance(v,str):require(stored[k]==v,'Fraction CSV labels')
            else:close(float(stored[k]),v,'Fraction CSV numeric')
    anchors=list(csv.DictReader(io.StringIO((root/'tables/anchors.csv').read_text())))
    require(len(anchors)==3,'Anchor CSV count')
    for row,a in zip(anchors,e['anchors']):
        # Exact original figure table is also pinned; independently verify its plotted fields below.
        values=[a['parent_GeV'],a['lsp_GeV'],a['original_events'],a['limits'][0]['inclusive_sigma95_fb'],a['limits'][0]['reference_sigma95_pb']*1000,a['limits'][0]['residual_percent'],a['limits'][3]['inclusive_sigma95_fb'],a['limits'][3]['reference_sigma95_pb']*1000,a['limits'][3]['residual_percent'],a['unions'][0]['selected_events'],100*a['unions'][0]['histogram_relative_mc'],a['unions'][1]['selected_events'],100*a['unions'][1]['histogram_relative_mc'],sum(b['selected_events']==0 for b in a['channels'])]
        require(list(row)==['parent_GeV','lsp_GeV','original_events','observed_fb','observed_reference_fb','observed_residual_percent','median_expected_fb','median_expected_reference_fb','median_expected_residual_percent','high_selected_events','high_histogram_mc_percent','low_selected_events','low_histogram_mc_percent','zero_selected_channels'],'Anchor CSV columns')
        for v,w in zip(row.values(),values):close(float(v),w,'Figure-table arithmetic')
    for name in files:
        if name.endswith(('.json','.csv','.md')):
            text=(root/name).read_text()
            for private in ('/Users/','/private/tmp/','environment_sha256','supervisor_pid','authorization_quote'):
                require(private not in text,'Private local context: '+name)
    if source_root is not None:
        for name,payload in C['projections'](Path(source_root)).items():require(safe(root,name).read_bytes()==payload,'Source projection differs: '+name)
    return {'status':'verified_bounded_scalar_projection','anchors':3,'limits':18,'channels':114,'fractions':6,'reported_fresh_checks':48,'raw_payloads_revalidated':False,'new_events':0,'new_fits':0,'physics_certified':False}

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--source-root',type=Path);args=p.parse_args()
    print(json.dumps(verify(source_root=args.source_root),sort_keys=True))
