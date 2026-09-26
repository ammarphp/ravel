#!/usr/bin/env python3
"""Deterministic, offline catalogue browser and CSV; no remote JavaScript or plotting claims."""
from __future__ import annotations
import argparse
import csv
import hashlib
import html
import json
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'src'))
from ravel.analysis_catalog import load_catalog, adaptation_packet, source_url


def render(catalog, out):
    out.mkdir(parents=True,exist_ok=True)
    rows=catalog['entries']
    with (out/'routines.csv').open('w',newline='',encoding='utf-8') as f:
        fields=['id','experiment','framework','family','title','analysis_ids','upstream_status','source_relation','source_url','reference_files','model_index_matches','features','metadata_issues']
        writer=csv.DictWriter(f,fieldnames=fields,lineterminator="\n");writer.writeheader()
        for r in rows:
            writer.writerow({**{k:r[k] for k in fields if k in r},
                'analysis_ids':'; '.join(r['analysis_ids']),
                'source_url':'; '.join(source_url(catalog,r,p['path']) for p in r['source_files']),
                'reference_files':len(r['reference_files']),'model_index_matches':len(r['model_index_matches']),
                'features':'; '.join(r['features']),'metadata_issues':'; '.join(r['metadata_issues'])})
    data=[]
    for r in rows:
        data.append({'id':r['id'],'name':r['name'],'title':r['title'],'experiment':r['experiment'],
            'framework':r['framework'],'family':r['family'],'features':list(r['features']),
            'identities':r['analysis_ids']+r['publication_urls'], 'packet':adaptation_packet(catalog,r)})
    escaped=json.dumps(data,ensure_ascii=False,separators=(',',':')).replace('<','\\u003c').replace('>','\\u003e').replace('&','\\u0026')
    summary=html.escape(json.dumps(catalog['summary'],indent=2))
    page=r'''<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>RAVEL · Public analysis landscape</title>
<style>
:root{color-scheme:light;--ink:#152c39;--muted:#49616d;--line:#ccdae1;--blue:#135a7b}*{box-sizing:border-box}body{margin:0;font:16px/1.55 system-ui,sans-serif;color:var(--ink);background:#f5f8fa}header{padding:36px 4vw 24px;background:white;border-bottom:1px solid var(--line)}h1{font-size:clamp(28px,4vw,44px);line-height:1.15;letter-spacing:-1px;margin:8px 0 16px}p{max-width:960px}a{color:var(--blue)}.eyebrow{color:var(--muted);font-size:13px;letter-spacing:1px}.metrics{display:flex;gap:30px;flex-wrap:wrap;margin:20px 0}.metrics strong{font-size:28px;display:block}.metrics span{color:var(--muted);font-size:14px}main{padding:24px 4vw}.filters{display:flex;flex-wrap:wrap;gap:12px;align-items:end;background:white;padding:18px;border:1px solid var(--line);border-radius:8px}label{display:flex;flex-direction:column;font-size:13px;gap:5px}input,select,button{font:inherit;padding:9px 12px;background:white;border:1px solid #8fa8b5;border-radius:4px}input{min-width:300px}button{color:var(--blue);cursor:pointer}button:hover,button:focus{background:#e9f3f7}#count{font-weight:600;margin:18px 0}.layout{display:grid;grid-template-columns:minmax(450px,1.1fr) minmax(370px,1fr);gap:24px}.tablewrap{max-height:72vh;overflow:auto;background:white;border:1px solid var(--line)}table{border-collapse:collapse;width:100%;font-size:13px}th{position:sticky;top:0;background:#eaf0f4;text-align:left;padding:12px;z-index:1}td{padding:12px;border-bottom:1px solid #e2eaef;vertical-align:top}td button{font-size:12px;text-align:left;overflow-wrap:anywhere;border:0;padding:0}small{display:block;color:var(--muted)}#detail{background:white;border:1px solid var(--line);border-radius:8px;padding:22px;max-height:72vh;overflow:auto}#detail h2{overflow-wrap:anywhere;font-size:21px;line-height:1.3}#detail h3{font-size:16px;margin-top:24px}#detail ul{padding-left:21px}#detail li{margin:8px 0}#detail a{overflow-wrap:anywhere}.flag{padding:10px 14px;border-left:3px solid #b78820;background:#fff9e9}pre{overflow:auto;font-size:12px}footer{padding:28px 4vw;font-size:14px;color:var(--muted)}@media(max-width:980px){.layout{grid-template-columns:1fr}.tablewrap{max-height:55vh}#detail{max-height:none}input{min-width:180px;width:100%}}
</style>
<header><div class="eyebrow">RAVEL · PINNED SOURCE SURVEY · 26 SEPTEMBER 2026</div>
<h1>The public analysis landscape</h1>
<p>A map of public routines and the work needed to adapt them. Entries are routine/metadata records, including variants and auxiliary calibrations; they are <strong>not independent papers or validated RAVEL analyses</strong>.</p>
<div class="metrics"><div><strong>633</strong><span>catalogue entries</span></div><div><strong>554 + 79</strong><span>Rivet + SimpleAnalysis</span></div><div><strong>24</strong><span>probability-index matches</span></div><div><strong>0</strong><span>new physics validations</span></div></div>
<p><a href="routines.csv">Download all rows (CSV)</a> · <a href="../../../docs/research/2026-09-26-analysis-landscape.md">Survey and implementation roadmap</a> · <a href="../../../docs/research/2026-09-26-competitor-capability-map.md">Competitor assessment</a></p>
</header><main>
<div class="filters"><label>Find a routine, paper or topic<input id="query" type="search" placeholder="e.g. SUSY-2018-16, photon, LHCb"></label><label>Experiment<select id="experiment"><option value="">All</option></select></label><label>Framework<select id="framework"><option value="">Both</option><option>rivet</option><option>simpleanalysis</option></select></label><label>Adaptation family<select id="family"><option value="">All</option></select></label><button id="reset">Reset</button></div>
<p id="count" role="status" aria-live="polite"></p><div class="layout"><div class="tablewrap"><table><thead><tr><th>Routine / title</th><th>Experiment</th><th>Adaptation</th></tr></thead><tbody id="rows"></tbody></table></div><section id="detail" aria-label="Selected routine"></section></div>
<details><summary>Scope and denominator audit</summary><p>This snapshot enumerates the selected Rivet 4.1.4 Git tree and the pinned public SimpleAnalysis tree. Family assignment and dependency signals are conservative automated triage, not a per-paper scientific review. Reference-file presence does not establish a usable covariance or likelihood; no-index-match means unknown. External PAD, CheckMATE and private codes are outside this census.</p><pre>SUMMARY</pre></details>
<noscript>JavaScript is needed for filtering. All rows are available in the linked CSV and the JSON catalogue shipped with RAVEL.</noscript></main>
<footer>Read-only discovery. No compile, event generation, fit or approval is triggered. RRR shape, acceptance and full-contour closure remain unresolved.</footer>
<script id="data" type="application/json">DATA</script>
<script>
const data=JSON.parse(document.getElementById('data').textContent);
const byId=id=>document.getElementById(id), q=byId('query'), ex=byId('experiment'), fw=byId('framework'), fa=byId('family');
for(const [sel,key] of [[ex,'experiment'],[fa,'family']]) for(const value of [...new Set(data.map(r=>r[key]))].sort()){const o=document.createElement('option');o.value=value;o.textContent=value;sel.append(o)}
function el(tag,text,parent){const e=document.createElement(tag);if(text!==undefined)e.textContent=text;if(parent)parent.append(e);return e}
function select(row){const p=row.packet,d=byId('detail');d.replaceChildren();el('h2',row.id,d);el('p',row.title,d);el('p','Discovery only · physics not validated · compute not authorized',d).className='flag';el('p','Upstream status: '+p.upstream_status+' · reference files: '+p.reference_files_present+' · indexed models: '+p.probability_model_index_matches.length,d);el('p','Source revision: '+p.source_revision,d);el('p','Features to review: '+(row.features.join(', ')||'No lexical signal; manual dependency review still required.'),d);el('h3','Known blockers',d);let u=el('ul',undefined,d);for(const x of p.blockers)el('li',x,u);el('h3','Required adaptation and validation',d);u=el('ul',undefined,d);for(const x of p.requirements)el('li',x,u);el('h3','Source and publication',d);u=el('ul',undefined,d);for(const url of [...p.source_urls,...p.publication_urls]){const a=el('a',url,el('li',undefined,u));a.href=url;a.rel='noopener';a.target='_blank'}el('h3','Next action',d);el('p',p.next_action,d)}
function update(){const tokens=q.value.toLowerCase().trim().split(/\s+/).filter(Boolean);const rows=data.filter(r=>(!ex.value||r.experiment===ex.value)&&(!fw.value||r.framework===fw.value)&&(!fa.value||r.family===fa.value)&&tokens.every(t=>[r.id,r.title,r.experiment,...r.identities].join(' ').toLowerCase().includes(t)));byId('count').textContent=rows.length+' of '+data.length+' entries';const body=byId('rows');body.replaceChildren();for(const r of rows){const tr=el('tr',undefined,body),td=el('td',undefined,tr),b=el('button',r.id,td);b.onclick=()=>select(r);el('small',r.title,td);el('td',r.experiment,tr);el('td',r.family,tr)}if(rows.length)select(rows[0]);else{byId('detail').replaceChildren();el('p','No matching entry in this snapshot. This does not establish that a public implementation is unavailable elsewhere.',byId('detail'))}}
for(const input of [q,ex,fw,fa])input.addEventListener('input',update);byId('reset').onclick=()=>{q.value=ex.value=fw.value=fa.value='';update()};update();
</script></html>'''.replace('SUMMARY',summary).replace('DATA</script>',escaped+'</script>')
    (out/'index.html').write_text(page,encoding='utf-8')
    return {'rows':len(rows),'csv_sha256':hashlib.sha256((out/'routines.csv').read_bytes()).hexdigest(),
            'html_sha256':hashlib.sha256((out/'index.html').read_bytes()).hexdigest()}


if __name__=='__main__':
    ap=argparse.ArgumentParser(description=__doc__);ap.add_argument('--out',type=Path,required=True)
    args=ap.parse_args();print(json.dumps(render(load_catalog(),args.out),indent=2))
