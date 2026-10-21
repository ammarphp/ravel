"""Data-shaped sink contract peer.

The fake exercises the controller contract, never physics validity. Installed probes use
sink check/inventory primitives; this is unit integration, not a complete accepted store
or an end-to-end delivery proof. No row ID or expected answer enters either probe.
"""
from __future__ import annotations

from copy import deepcopy
import hashlib
import importlib
import json
from pathlib import Path


def payload(kind, **changes):
    value = dict(kind=kind, refused=False, producer_journal=True, review_history=['unchanged-subject-sha'], review_rounds=1,
                 max_rounds=2, tokens=42, prose=[1.25], source=[1.25], statistic='delta chi2',
                 pinned_statistic='delta chi2', panels=['left', 'right'], required_panels=['left', 'right'],
                 seats={'tier_a': True, 'tier_b': True}, ledger_status='completed',
                 files={'result.json': '1.25'}, worker_files=['result.json'],
                 lineage=['accepted'], certificate_run='current', certification={'status': 'uncertified',
                 'fidelity': 'proxy', 'explanation': 'No detector certificate',
                 'certifiable_route': 'native detector validation', 'flag': 'uncertified'},
                 defaults=['conservative'], presented_defaults=['conservative'],
                 declared=['result.json'], offered=['result.json'], tier='central', certified=False,
                 detector_mode='proxy', exclusion_of_record=False, at_poi_cap=False, resolved=False,
                 rendered=[1.25], defects=[], verdict='FAIL', presented_verdict='FAIL',
                 runtime={'numpy': None}, exported_runtime={'numpy': None},
                 claim='All requested work is complete')
    value.update(changes)
    return value


def guard(p):
    """Pure fake guard over evidence fields, independently mutable from the test oracle."""
    k = p['kind']; errors=[]; notices=[]; disclosures=[]
    if k == 'refusal' and p['refused']: errors.append('refused_attempt')
    if k == 'origin' and not p['producer_journal']: errors.append('receipt_origin')
    if k == 'rounds' and len(p['review_history']) >= p['max_rounds']: errors.append('review_rounds_exhausted')
    if k == 'usage' and p['tokens'] is None: notices.append('tokens_unknown')
    if k == 'prose' and any(x not in p['source'] for x in p['prose']): notices.append('unverified_prose')
    if k == 'statistic' and p['statistic'] != p['pinned_statistic']: errors.append('statistic_mismatch')
    if k == 'panels' and set(p['required_panels'])-set(p['panels']): errors.append('missing_panel')
    if k == 'review' and not all(p['seats'].get(s) for s in ('tier_a','tier_b')): errors.append('review_incomplete')
    if k == 'completion' and p['ledger_status'] != 'completed': errors.append('incomplete_ledger')
    if k == 'inventory': disclosures.extend(sorted(p['files']))
    if k == 'lineage' and any(s != 'accepted' for s in p['lineage']): errors.append('diagnostic_lineage')
    if k == 'certificate' and any(not p['certification'].get(f) for f in ('fidelity','explanation','certifiable_route','flag')): notices.append('uncertified_limitation_missing')
    if k == 'defaults': disclosures.extend(p['defaults'])
    if k == 'population' and set(p['declared']) != set(p['offered']): errors.append('population_mismatch')
    if k == 'certificate_origin' and p['certificate_run'] != 'current': errors.append('certificate_origin')
    if k == 'tail' and p['tier']=='tail' and p['certified']: notices.append('report_only_tail')
    if k == 'fidelity' and p['detector_mode']=='proxy' and p['exclusion_of_record']: notices.append('uncertified_fidelity')
    if k == 'crossing' and p['at_poi_cap'] and p['resolved']: notices.append('uncrossed_bound')
    if k == 'render' and p['rendered'] != p['source']: errors.append('render_mismatch')
    if k == 'defect' and any(d['status']=='open' for d in p['defects']): errors.append('open_defect')
    if k == 'verdict' and p['verdict'] != p['presented_verdict']: errors.append('verdict_mismatch')
    if k == 'environment' and p['runtime'] != p['exported_runtime']: errors.append('unsupported_runtime_pin')
    return dict(errors=errors,notices=notices,disclosures=disclosures)


def fake_probe(nc, p):
    return guard(p)


def real_probe(nc, p):
    """Mandatory installed sink probes. Missing APIs and implementation errors propagate."""
    checks=importlib.import_module('ravel.controller.sink.checks')
    inventory=importlib.import_module('ravel.controller.sink.inventory')
    numbers=importlib.import_module('ravel.controller.sink.numbers')
    root=nc.root / ('sink-unit-'+p['kind'])
    root.mkdir(parents=True,exist_ok=True)
    k=p['kind']; errors=[]; notices=[]; disclosures=[]
    if k in ('certificate','certificate_origin','tail','fidelity','crossing','environment'):
        doc={'certification':p['certification']} if k=='certificate' else {
            'kind':'certificate','rundir':str(root if p['certificate_run']=='current' else root.parent/'other')}
        if k=='environment': doc={'runtime':p['runtime'],'exported_runtime':p['exported_runtime']}
        if k=='tail': doc={'tier':p['tier'],'certified':p['certified']}
        if k=='fidelity': doc={'detector_mode':p['detector_mode'],'exclusion_of_record':p['exclusion_of_record']}
        if k=='crossing': doc={'at_poi_cap':p['at_poi_cap'],'resolved':p['resolved']}
        (root/'result.json').write_text(json.dumps(doc))
        f=checks.Findings()
        checks._scan_run_rows(f,{},[{'artifact':'s:result.json','destination':'result.json'}],root)
        key={'certificate':'C06','certificate_origin':'C33','tail':'E11','fidelity':'E15','crossing':'E19','environment':'E27'}[k]
        violated=any(r['row']==key and r['status']=='violated' for r in f.rows.values())
        code={'certificate':'uncertified_limitation_missing','certificate_origin':'certificate_origin',
              'tail':'report_only_tail','fidelity':'uncertified_fidelity','crossing':'uncrossed_bound','environment':'unsupported_runtime_pin'}[k]
        if violated: (errors if k in ('certificate_origin','environment') else notices).append(code)
    elif k in ('prose','render'):
        refs=numbers.References()
        for x in p['source']: refs.add(x)
        text=('value '+str(p['prose'][0])) if k=='prose' else '| result |\n| --- |\n| '+str(p['rendered'][0])+' |'
        traced=numbers.trace(text,'.md',refs.freeze())
        if traced['unmatched_prose'] and k=='prose': notices.append('unverified_prose')
        if traced['untraced_table'] and k=='render': errors.append('render_mismatch')
    elif k=='statistic':
        f=checks.Findings()
        checks._statistic(f,{'intake':{'reading':{},'contract':{}},'store':_Store([])},
                          {'artifact':'s:result.json','claim_kind':'calculation'}, {'statistic':p['statistic']},
                          p['pinned_statistic'],True,None,None)
        if f.refusals: errors.append('statistic_mismatch')
    elif k=='panels':
        (root/'result.panels.json').write_text(json.dumps({'panels':p['panels']}))
        plan={'steps':[{'id':'s','parameters':{'panels':p['required_panels']}}]}
        if checks._panel_holes(plan,{'step':'s','destination':'result.png'},None,root): errors.append('missing_panel')
    elif k=='origin':
        ev={'dispatches':[{'node_id':'n','attempt':1}] if p['producer_journal'] else [],
            'observations':[{'receipt_sha256':'digest'}] if p['producer_journal'] else []}
        _, problem=checks._producer_journal(ev,{'producer':{'kind':'worker','node_id':'n','attempt':1,'receipt_sha256':'digest'}})
        if problem: errors.append('receipt_origin')
    elif k=='defect':
        if checks._open_defects({'findings':p['defects']}): errors.append('open_defect')
    elif k=='verdict':
        claimed=checks._claimed_verdict({'verdict':p['presented_verdict'],'findings':[]})
        if claimed != p['verdict']: errors.append('verdict_mismatch')
    elif k=='defaults':
        ev={'judgments':[{'chosen':x,'default_option':x,'options':[]} for x in p['defaults']], 'authority':{'defaults':[]}}
        disclosures.extend(x['chosen'] for x in checks.adopted_defaults(ev))
    elif k=='inventory':
        for name,value in p['files'].items(): (root/name).write_text(value)
        disclosures.extend(sorted(inventory.walk(root)['files']))
    elif k=='usage':
        record={'key':'reservation','amounts':{'tokens':p['tokens']}}
        ev=importlib.import_module('ravel.controller.sink.evidence')._budget(_Store([('budget-reservation',record)]))
        if ev['dimensions']['tokens']['unknown_attempts']: notices.append('tokens_unknown')
        # A measured control must include the observed settlement.
        if p['tokens'] is not None:
            ev=importlib.import_module('ravel.controller.sink.evidence')._budget(_Store([
                ('budget-reservation',record),('budget-settlement',{'key':'reservation','status':'settled',
                 'measured':{'tokens':p['tokens']},'charged':{'tokens':p['tokens']}})]))
            notices=[] if not ev['dimensions']['tokens']['unknown_attempts'] else ['tokens_unknown']
    else:
        from nc_controller import controller_run
        sink=importlib.import_module('ravel.controller.sink')
        store, run_dir=controller_run(nc, 'sink-real-'+k)
        # Whole-store checks are mandatory after installation. The peer's receipt
        # is observed; the harness receipt is a separate publication contract.
        if k=='rounds':
            result=sink.bounded_end(store, 'review_rounds_exhausted') if len(p['review_history'])>=p['max_rounds'] else sink.receipt(store)
            if len(p['review_history'])>=p['max_rounds'] and 'review_rounds_exhausted' in json.dumps(result):
                errors.append('review_rounds_exhausted')
        else:
            ev={'store':store,'run_dir':str(root),'custody':{},'custody_rows':[], 'outcomes':{},
                'credits':[], 'refusals':[], 'intake':{'reading':{},'contract':{}},
                'plan':{'problems':[]},'binding':[],'store_problems':[],
                'identity':{'governed':True,'live':{}},'launches':[], 'observations':[],
                'dispatches':[],'wms':[],'budget':{'dimensions':{}},'judgments':[],
                'authority':{'defaults':[]}}
            (root/'steps'/'s').mkdir(parents=True,exist_ok=True)
            path=root/'steps'/'s'/'result.json'; path.write_text('{}')
            sha=hashlib.sha256(path.read_bytes()).hexdigest()
            custody={'artifact':'s:result.json','step_id':'s','attempt':1,'status':'accepted',
                     'destination':'steps/s/result.json','sha256':sha,'inputs':[],
                     'producer':{'kind':'worker','node_id':'n','attempt':1,'receipt_sha256':'digest'}}
            ev['custody']['s:result.json']=custody
            ev['outcomes']['s']={'status':p['ledger_status'],'attempt':1}
            ev['dispatches']=[{'node_id':'n','attempt':1}]
            ev['observations']=[{'receipt_sha256':'digest','status':'ok','tool_inventory':['python']}]
            if p['refused']: ev['refusals']=[{'step_id':'s','attempt':1}]
            if k=='lineage' and any(x!='accepted' for x in p['lineage']):
                custody['inputs']=['old:diagnostic']; ev['custody']['old:diagnostic']={'status':'rejected'}
            plan={'sha256':'plan-digest','steps':[{'id':'s'}],'deliverables':[{'id':'d','status':'mapped','step':'s','output':'result.json'}]}
            inv=inventory.walk(root); hashes=inventory.Hashes(root)
            classified=inventory.classify(ev,plan,inv,hashes)
            if k in ('completion','lineage','population'):
                if k=='population' and 'result.json' not in p['offered']: path.unlink()
                classified=inventory.classify(ev,plan,inventory.walk(root),inventory.Hashes(root))
                bad=any(row['status']!='accepted' for row in classified['declared'])
                if bad: errors.append({'completion':'incomplete_ledger','lineage':'diagnostic_lineage','population':'population_mismatch'}[k])
            else:
                if k=='review':
                    seats={name:{'credited':credited,'verdict':'pass'} for name,credited in p['seats'].items()}
                    ev['store']=_Store([('review',{'purpose':'final','plan_sha256':'plan-digest','seats':seats})])
                    ev['credits']=[{'step_id':'final_review','attempt':1,'own':{'credited':True,'verdict':'pass'}}]
                    classified['declared']=[]
                findings=checks.evaluate(ev,plan,classified,hashes)
                if k=='review':
                    if any(r['code']=='review_incomplete' for r in findings.refusals): errors.append('review_incomplete')
                    return dict(errors=errors,notices=notices,disclosures=disclosures)
                row={'refusal':'A12','review':'D04','environment':'E27'}[k]
                if any(r['row']==row and r['status']=='violated' for r in findings.rows.values()):
                    errors.append({'refusal':'refused_attempt','review':'review_incomplete','environment':'unsupported_runtime_pin'}[k])
    return dict(errors=errors,notices=notices,disclosures=disclosures)


class _Store:
    def __init__(self, rows): self.rows=rows
    def scan(self, kind): return [deepcopy(v) for k,v in self.rows if k==kind]


# Exact cross-owner proposals and proving tests are retained in the fixture manifest.
PATCH_MANIFEST = 'tests/fixtures/enforcement/patches/manifest.json'
