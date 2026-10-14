"""Small fictional source table for compatibility callers."""
import hashlib
import json


def supplied_request(tmp_path):
    path = tmp_path/'supplied-rates.json'
    path.write_text(json.dumps({'data':{'100':{'xsec_pb':2}}}))
    return {'schema_version':1,'basis':'state-A','sqrt_s_GeV':12000,'masses':{'mass':100},
            'state_count':1,'charge':None,'convention':{'order':'LO','pdf':'fictional-pdf','scale':'mass'},
            'table':{'path':str(path),'sha256':hashlib.sha256(path.read_bytes()).hexdigest(),
                     'parameters':['mass'],'interpolation':'exact',
                     'provenance':{'kind':'supplied-calculation','reference':'fictional source',
                                   'justification':'Synthetic caller compatibility input.'}}}
