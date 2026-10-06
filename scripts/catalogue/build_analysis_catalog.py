#!/usr/bin/env python3
"""Inventory pinned upstream Git objects, not working-tree files or executable code.

Requires PyYAML only when rebuilding; shipped catalogue queries use the stdlib.
No routines are imported, compiled, copied into Ravel, or certified by this tool.
"""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys
import yaml

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'src'))
from ravel.analysis_catalog import SCHEMA_VERSION, classify, validate_catalog, summarize

LHC_DIRS = {'pluginATLAS', 'pluginCMS', 'pluginALICE', 'pluginLHCb', 'pluginLHCf', 'pluginTOTEM'}
FIELDS = ('Name', 'Year', 'Summary', 'Experiment', 'Collider', 'InspireID', 'Status',
          'References', 'Keywords', 'Beams', 'Energies', 'Options', 'Reentrant',
          'NeedCrossSection', 'RefMatch', 'RefUnmatch', 'ReleaseTests')


def git(root, *args):
    return subprocess.check_output(['git', '-C', str(root), *args])


def tree(root, revision):
    commit = git(root, 'rev-parse', '--verify', revision + '^{commit}').decode().strip()
    result = {}
    for line in git(root, 'ls-tree', '-r', '-z', commit).split(b'\0'):
        if not line: continue
        header, name = line.split(b'\t', 1)
        mode, kind, oid = header.decode().split()
        result[name.decode()] = {'mode': mode, 'kind': kind, 'git_blob': oid}
    return commit, result


def blobs(root, inventory, names):
    names = sorted(set(names))
    raw = subprocess.check_output(['git', '-C', str(root), 'cat-file', '--batch'],
                                 input=('\n'.join(inventory[n]['git_blob'] for n in names)+'\n').encode())
    offset = 0; out = {}
    for name in names:
        end = raw.index(b'\n', offset)
        oid, kind, size = raw[offset:end].split(); size = int(size)
        if kind != b'blob': raise ValueError(f'not a blob: {name}')
        body = raw[end+1:end+1+size]
        if len(body) != size: raise ValueError(f'truncated blob: {name}')
        out[name] = body; offset = end + size + 2
    if offset != len(raw): raise ValueError('unexpected cat-file output')
    return out


def metadata(raw):
    """Read named metadata blocks independently; never repair malformed prose.

    Some official .info descriptions are not valid YAML. Omitting long prose is
    deliberate. A bad selected block stays an explicit warning and raw value.
    BaseLoader also prevents an upstream status 'yes' becoming boolean True.
    """
    text = raw.decode('utf-8')
    matches = list(re.finditer(r'^([A-Za-z][A-Za-z0-9_ ]*):', text, re.M))
    out = {}; issues = []
    for i, match in enumerate(matches):
        key = match[1]
        if key not in FIELDS: continue
        block = text[match.start():matches[i+1].start() if i+1 < len(matches) else len(text)]
        if key in out: issues.append(f'duplicate metadata field: {key}')
        try: out[key] = yaml.load(block, Loader=yaml.BaseLoader)[key]
        except yaml.YAMLError:
            out[key] = block.split(':', 1)[1].strip()
            issues.append(f'unparsed metadata field: {key}')
    return out, issues


def strip_comments(text):
    # Keep quoted literals, since dependency filenames and analysis macros use them.
    pattern = r'"(?:\\.|[^"\\])*"|\'(?:\\.|[^\'\\])*\'|//[^\n]*|/\*[\s\S]*?\*/'
    return re.sub(pattern, lambda m: ' ' if m[0].startswith(('/',)) else m[0], text)


def feature_signals(text, metadata_text=''):
    code = strip_comments(text)
    patterns = {
        'restframes': r'\bRestFrames\b|RestFrames/|\bm_RF_helper\b|\b(?:Lab|Decay|Visible|Invisible)RecoFrame\b',
        'onnx': r'\b(?:addONNX|ONNX|Onnx|ONNXRuntime)\b|\.onnx\b',
        'mva': r'\b(?:addMVA|addBDT|TMVA|MVAUtils|lwtnn)\b|\.xml["\']',
        'fastjet-contrib': r'fastjet/contrib|fastjet::contrib',
        'smearing': r'\b(?:SmearedJets|SmearedParticles|SmearedMET|Smearing)\b|Rivet/Tools/SmearingFunctions',
        'centrality': r'\b(?:CentralityProjection|declareCentrality|centrality)\b',
        'event-mixing': r'\bEventMixing\w*',
        'heavy-ion': r'\b(?:HeavyIon|RHICCentrality|HepMCHeavyIon)\b',
        'lifetime': r'\b(?:decayLength|ctau|properTime|decayVertex|production_vertex)\b',
        'tau-objects': r'\b(?:getTaus|TauFinder|TauJets)\b',
        'large-r-jets': r'\b(?:getFatJets|Recluster|TrimmedJets|SoftDrop|Filter)\b',
    }
    found = {name: sorted(set(m[0] for m in re.finditer(pattern, code)))[:8]
             for name, pattern in patterns.items() if re.search(pattern, code)}
    # Physics-domain cues are labelled separately from literal code dependencies.
    cues = {
        'heavy-ion-domain': r'Pb[+\W_]*Pb|p[+\W_]*Pb|Pb[+\W_]*p\b|XeXe|heavy.ion|\blead\b|\bnuclear\b|[\'\"]Pb[\'\"]',
        'llp-domain': r'disappear|displaced|long.lived|metastable|heavy charged',
        'forward-domain': r'diffraction|diffractive|forward proton|elastic scattering',
        'flavour-domain': r'quarkonium|J/psi|J/\\psi|charm|beauty|bottom|B.meson|D.meson',
    }
    low = metadata_text.lower()
    for name, pattern in cues.items():
        if re.search(pattern, low, re.I): found[name] = ['metadata keyword; requires manual review']
    return found


def fact(path, inv, content=None):
    out = {'path': path, 'git_blob': inv[path]['git_blob'], 'git_mode': inv[path]['mode']}
    if content is not None: out['sha256'] = hashlib.sha256(content).hexdigest()
    return out


def atlas_ids(text):
    return sorted(set(re.findall(r'(?<![A-Z])(?:ATLAS[-_]|ANA-)?((?:SUSY|EXOT|STDM|TOPQ|HIGG|HIGP|BPHY|HION)-\d{4}-\d{2,3})', text)))


def rivet_rows(root, revision):
    commit, inv = tree(root, revision)
    names = [n for n in inv if n.startswith('analyses/plugin') and n.endswith(('.info', '.cc'))]
    raw = blobs(root, inv, names)
    source_names = [n for n in names if n.endswith('.cc')]
    aliases = {}
    for n in source_names:
        code = strip_comments(raw[n].decode())
        for original, alias in re.findall(r'RIVET_DECLARE_ALIASED_PLUGIN\s*\(\s*(\w+)\s*,\s*(\w+)\s*\)', code):
            aliases.setdefault(alias, []).append(n)
    rows=[]; ignored=[]
    for n in sorted(x for x in names if x.endswith('.info')):
        meta, issues = metadata(raw[n]); name = Path(n).stem
        if meta.get('Name', name) != name: issues.append('metadata Name differs from file identity')
        is_lhc = (Path(n).parent.name in LHC_DIRS or
                  re.search(r'\bLHC\b', str(meta.get('Collider',''))) or name.startswith(('FASER_', 'SNDLHC_')))
        if name.startswith('MC_'): is_lhc = False
        if not is_lhc: ignored.append(n); continue
        direct = str(Path(n).with_suffix('.cc'))
        sources = [direct] if direct in inv else aliases.get(name, [])
        if not sources: issues.append('no direct or declared alias source identified')
        if len(sources)>1: issues.append('multiple source implementations identified')
        code = '\n'.join(raw[s].decode() for s in sources)
        summary = str(meta.get('Summary') or name)
        exp = str(meta.get('Experiment') or Path(n).parent.name.removeprefix('plugin'))
        exp = {'LHCB':'LHCb','LHCF':'LHCf','CMS collaboration':'CMS'}.get(exp,exp)
        namespace = name.split('_',1)[0]
        if namespace in ('CMS','ATLAS','ALICE') and namespace not in exp.split(', '):
            issues.append(f'Experiment metadata {exp!r} conflicts with routine namespace {namespace!r}; namespace used for grouping')
            exp = namespace
        inspire = str(meta.get('InspireID',''))
        if not inspire.isdigit():
            match = re.search(r'_I(\d+)', name); inspire = match[1] if match else None
        refs = meta.get('References') or []
        if not isinstance(refs,list): refs=[str(refs)]
        publications = sorted(set('https://arxiv.org/abs/'+x for x in re.findall(r'(?:arXiv:|arxiv.org/abs/)(\d{4}\.\d{4,5})', ' '.join(refs))))
        if inspire: publications.append('https://inspirehep.net/literature/'+inspire)
        base = str(Path(n).with_suffix(''))
        refpaths = sorted(p for p in inv if p.startswith(base+'.') and p.endswith(('.yoda','.yoda.gz','.yoda.bz2')))
        plotpaths = [base+'.plot'] if base+'.plot' in inv else []
        features=feature_signals(code, summary+' '+str(meta.get('Keywords',''))+' '+str(meta.get('Beams','')))
        entry = {'id':'rivet:'+name,'framework':'rivet','name':name,'experiment':exp,
                 'title':summary, 'source_id':'rivet', 'metadata': meta, 'metadata_issues':issues,
                 'analysis_ids':atlas_ids(' '.join(refs)), 'inspire_id':inspire,
                 'publication_urls':publications, 'source_files':[fact(s,inv,raw[s]) for s in sources],
                 'metadata_file':fact(n,inv,raw[n]), 'reference_files':[fact(p,inv) for p in refpaths],
                 'plot_files':[fact(p,inv) for p in plotpaths], 'features':features,
                 'upstream_status':str(meta.get('Status','unknown')), 'model_index_matches':[],
                 'source_relation':'direct' if direct in sources else 'alias' if sources else 'unresolved',
                 'physics_validated_by_ravel':False}
        entry.update(classify(entry)); rows.append(entry)
    covered = {f['path'] for row in rows for f in row['source_files']}
    orphan = [n for n in source_names if Path(n).parent.name in LHC_DIRS and n not in covered]
    return rows, {'repository':'https://gitlab.com/hepcedar/rivet','revision':commit,'requested_ref':revision,
                  'all_info_files':sum(n.endswith('.info') for n in names), 'selected_info_files':len(rows),
                  'excluded_non_lhc_metadata':len(ignored), 'unmatched_lhc_source_files':orphan,
                  'method':'LHC experiment plugin directories plus Collider=LHC metadata and FASER/SNDLHC names; SND at VEPP and generic MC validation routines are excluded.'}


def sa_rows(root, revision):
    commit, inv=tree(root,revision)
    paths=[p for p in inv if p.startswith('SimpleAnalysisCodes/src/') and p.endswith('.cxx')]
    raw=blobs(root,inv,paths); rows=[]; no_macros=[]
    for p in sorted(paths):
        text=raw[p].decode(); code=strip_comments(text)
        names=re.findall(r'\bDefineAnalysis\s*\(\s*(\w+)\s*\)',code)
        if not names: no_macros.append(p)
        for name in names:
            ids=atlas_ids(Path(p).name)
            features=feature_signals(text,name+' '+Path(p).stem)
            # Literal external assets only, not an exhaustive transitive dependency claim.
            assets=sorted(set(re.findall(r'["\']([^"\'\n]+\.(?:onnx|xml|json|root))["\']',code)))
            asset_rows=[]
            for a in assets:
                matches=sorted(n for n in inv if n.startswith('SimpleAnalysisCodes/data/') and Path(n).name==Path(a).name)
                asset_rows.append({'literal':a, 'matches':[fact(n,inv) for n in matches]})
            entry={'id':'simpleanalysis:'+name,'framework':'simpleanalysis','name':name,
                   'experiment':'ATLAS','title':name,'source_id':'simpleanalysis','metadata':{},
                   'metadata_issues':[], 'analysis_ids':ids,'inspire_id':None,
                   'publication_urls':['https://atlas.web.cern.ch/Atlas/GROUPS/PHYSICS/PAPERS/'+i for i in ids],
                   'source_files':[fact(p,inv,raw[p])], 'reference_files':[], 'plot_files':[],
                   'features':features,'external_assets':asset_rows,'upstream_status':'not-declared-per-routine',
                   'model_index_matches':[], 'source_relation':'direct','physics_validated_by_ravel':False}
            entry.update(classify(entry)); rows.append(entry)
    return rows, {'repository':'https://gitlab.cern.ch/atlas-sa/simple-analysis','revision':commit,
                  'requested_ref':revision,'source_files':len(paths),'registered_routines':len(rows),
                  'sources_without_registration':no_macros,
                  'method':'All literal DefineAnalysis registrations in SimpleAnalysisCodes/src/*.cxx; distinct variants retained.'}


def build(rivet_root, sa_root, models_path, retrieved, rivet_ref='rivet-4.1.4', sa_ref='HEAD'):
    r,rs=rivet_rows(rivet_root,rivet_ref); s,ss=sa_rows(sa_root,sa_ref)
    model_bytes=Path(models_path).read_bytes(); models=json.loads(model_bytes)
    if not isinstance(models,list): raise ValueError('model index must be an array')
    for row in r+s:
        for model in models:
            ids=atlas_ids(model.get('link',''))
            rec=re.search(r'/ins(\d+)',model.get('hepdata',''))
            if (set(ids)&set(row['analysis_ids']) or (rec and row['inspire_id']==rec[1])):
                row['model_index_matches'].append({'analysis_ids':ids,'publication_url':model['link'],
                    'hepdata_url':model['hepdata'].rstrip('?'), 'match_basis':'exact analysis or INSPIRE identity',
                    'status':'listed-only; workspace bytes and schema not checked'})
    result={'schema_version':SCHEMA_VERSION,'retrieved_at_utc':retrieved,
            'scope':'Pinned Rivet LHC metadata entries and all public SimpleAnalysis registrations; not every LHC paper or private implementation.',
            'sources':{'rivet':rs,'simpleanalysis':ss,'probability-models':{
                'url':'https://pyhf.github.io/public-probability-models/atlas.json',
                'sha256':hashlib.sha256(model_bytes).hexdigest(),'entries':len(models)}},
            'entries':sorted(r+s,key=lambda row:row['id'])}
    result['summary']=summarize(result)
    validate_catalog(result)
    return result


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--rivet',type=Path,required=True); ap.add_argument('--simpleanalysis',type=Path,required=True)
    ap.add_argument('--models',type=Path,required=True); ap.add_argument('--retrieved-at',required=True)
    ap.add_argument('--rivet-ref',default='rivet-4.1.4'); ap.add_argument('--simpleanalysis-ref',default='HEAD')
    ap.add_argument('--out',type=Path,required=True)
    args=ap.parse_args()
    result=build(args.rivet,args.simpleanalysis,args.models,args.retrieved_at,args.rivet_ref,args.simpleanalysis_ref)
    with args.out.open('x',encoding='utf-8') as f: json.dump(result,f,indent=2,ensure_ascii=False,allow_nan=False); f.write('\n')
    print(json.dumps(result['summary'],indent=2))

if __name__=='__main__': main()
