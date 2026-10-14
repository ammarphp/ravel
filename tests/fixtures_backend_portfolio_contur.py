"""Cached import preserves native confidence, ties, raw fields and rounding."""
import hashlib
import json
import sqlite3


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

