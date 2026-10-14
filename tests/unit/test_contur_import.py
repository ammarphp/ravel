"""Cached import preserves native confidence, ties, raw fields and rounding."""
import csv
from copy import deepcopy
import hashlib
import io
import json
import sqlite3

import pytest

from ravel.physics import contur_import as bridge


def database(path):
    with sqlite3.connect(path) as c:
        c.execute('CREATE TABLE model_point (id INTEGER PRIMARY KEY,model_id INTEGER,run_point TEXT,yoda_files TEXT)')
        c.execute('CREATE TABLE parameter_value (model_point_id INTEGER,name TEXT,value DOUBLE)')
        c.execute('CREATE TABLE run (id INTEGER PRIMARY KEY,model_point_id INTEGER,map_id INTEGER,events_num INTEGER,'
                  'stat_type TEXT,combined_exclusion DOUBLE,nll DOUBLE,llr DOUBLE,mu_lower_limit DOUBLE,'
                  'mu_upper_limit DOUBLE,mu_hat DOUBLE,addition_argument TEXT)')
        c.execute('CREATE TABLE exclusions (id INTEGER PRIMARY KEY,run_id INTEGER,pool_name TEXT,stat_type TEXT,'
                  'exclusion DOUBLE,histos TEXT,nll DOUBLE,llr DOUBLE,mu_lower_limit DOUBLE,mu_upper_limit DOUBLE,mu_hat DOUBLE)')
        c.execute("INSERT INTO model_point VALUES (1,1,'0000',\"['/original/13TeV/0000/native.yoda.gz']\")")
        c.executemany('INSERT INTO parameter_value VALUES (1,?,?)',[('mZp',1000.),('cotH',1.5)])
        for k, mode in enumerate(bridge.MODES, 1):
            c.execute('INSERT INTO run VALUES (?,?,?,?,?,?,?,?,?,?,?,?)',
                      (k,1,1,30000,mode,.95,3.25,2.34567,-.1234,.5678,.0123,'CACHED'))
            for p, (name, confidence, llr) in enumerate([('FIRST',.97,1.),('SECOND',.97,100.),('OTHER',.7,200.)],1):
                c.execute('INSERT INTO exclusions VALUES (?,?,?,?,?,?,?,?,?,?,?)',
                          (k*10+p,k,name,mode,confidence,'/'+name,2.,llr,None,None,None))
        # Older duplicate mode is not silently combined with the latest run.
        c.execute('INSERT INTO run VALUES (0,1,1,1,\'SMBG\',.1,NULL,NULL,NULL,NULL,NULL,\'OLD\')')


def contract(tmp_path):
    path=tmp_path/'results.db';database(path)
    pin=lambda p:{'path':p.name,'sha256':hashlib.sha256(p.read_bytes()).hexdigest()}
    source={'version':bridge.VERSION,'commit':bridge.COMMIT}
    for role in bridge.SOURCE_ROLES:
        p=tmp_path/(role+'.py');p.write_text('# synthetic source-identity control\n'+role)
        source[role]=pin(p)
    value={'schema_version':1,'database':pin(path),'source':source,'modes':list(bridge.MODES),
           'run_selection':{'policy':'latest_id_per_point_and_stat_type'},'scope':'Synthetic cached-import arithmetic control only'}
    inp=tmp_path/'input.json';inp.write_text(json.dumps(value))
    return inp,value


def test_complete_import_keeps_raw_fits_complement_and_tied_pool_candidates(tmp_path):
    path=tmp_path/'results.db';database(path)
    points=bridge.decode_database(path)
    assert len(points)==1 and len(points[0]['runs'])==3
    assert points[0]['original_yoda_paths']==['/original/13TeV/0000/native.yoda.gz']
    for run in points[0]['runs']:
        assert run['native_exclusion_confidence']==.95
        assert run['conventional_cls_complement']==pytest.approx(.05)
        assert run['raw']['mu_lower_limit']==-.1234
        assert run['raw']['llr']==2.34567
        assert len(run['pools'])==3 and len(run['dominant_candidates'])==2
        assert run['csv_dominant']['pool_name']=='FIRST'
        assert run['csv_dominant']['llr']!=max(p['llr'] for p in run['pools'])
    rows=list(csv.DictReader(io.StringIO(bridge.export_csv(points))))
    assert len(rows)==1
    row=rows[0]
    for mode in bridge.MODES:
        assert float(row['CL'+mode])==.95
        assert float(row['MULO'+mode])==-.12
        assert float(row['MUUP'+mode])==.57
        assert float(row['MUHAT'+mode])==.01
        assert float(row['LLR'+mode])==2.346
        assert row['dominant-pool-histo'+mode]==row['dominant-pool-llr'+mode]=='/FIRST'


def test_bound_result_writes_no_inference_and_refuses_source_drift(tmp_path):
    _,value=contract(tmp_path)
    task={'schema_version':1,'input':'input.json'}
    result=bridge.run(task,tmp_path,tmp_path/'output')
    assert result['inference'] is None and result['fresh_inference'] is False and result['physics_validated'] is False
    assert result['source']==value['source']
    with pytest.raises(FileExistsError):bridge.run(task,tmp_path,tmp_path/'output')
    (tmp_path/value['source']['depot_export']['path']).write_text('changed')
    with pytest.raises(ValueError,match='bytes changed'):bridge.inputs(task,tmp_path)


@pytest.mark.parametrize('fault,match',[
    ("UPDATE run SET combined_exclusion=1.1 WHERE id=1",'confidence range'),
    ("DELETE FROM run WHERE stat_type='EXP'",'three requested'),
    ("INSERT INTO parameter_value VALUES (1,'cotH',2.)",'duplicate'),
    ("UPDATE exclusions SET pool_name='FIRST' WHERE id=12",'duplicated'),
    ("UPDATE exclusions SET stat_type='UNKNOWN' WHERE id=11",'mode differs'),
    ("UPDATE exclusions SET exclusion=NULL WHERE id=11",'absent cached pool'),
    ("UPDATE model_point SET yoda_files='__import__(\"os\")'",'YODA list'),
])
def test_malformed_or_ambiguous_stored_results_are_refused(tmp_path,fault,match):
    path=tmp_path/'results.db';database(path)
    with sqlite3.connect(path) as c:c.execute(fault)
    with pytest.raises(ValueError,match=match):bridge.decode_database(path)


def test_semantic_source_and_selection_are_explicit(tmp_path):
    inp,value=contract(tmp_path)
    for mutate in [lambda d:d['source'].update(version='3.1.4'),
                   lambda d:d.update(run_selection={'policy':'choose_best_exclusion'}),
                   lambda d:d.update(modes=['SMBG'])]:
        changed=deepcopy(value);mutate(changed);inp.write_text(json.dumps(changed))
        with pytest.raises(ValueError):bridge.inputs({'schema_version':1,'input':'input.json'},tmp_path)
