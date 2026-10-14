"""Scientific adverse selection and source-preservation controls; no native compute."""
from ravel.physics import reinterpret_db as m
from copy import deepcopy
import json
import sys
import pytest
from types import SimpleNamespace
import os
import signal
import subprocess
import time


def test_parser_defaults_are_not_supplied_decay_widths(tmp_path, monkeypatch):
    card = tmp_path / 'source.slha'
    card.write_text('BLOCK MASS\n  1001 100\n  1002 200\nDECAY 1001 0.0 # explicit stable particle\n')
    parsed = SimpleNamespace(xsections={}, blocks={'MASS': {1001: 100, 1002: 200}},
        decays={1001: SimpleNamespace(totalwidth=0.0, decays=[]),
                1002: SimpleNamespace(totalwidth=0.0, decays=[])})
    monkeypatch.setitem(sys.modules, 'pyslha', SimpleNamespace(readSLHAFile=lambda path: parsed))
    result = m._physical_input(card, 'slha', m.SETTINGS)
    assert [row['pdg'] for row in result['decays']] == [1001]
    assert result['decays'][0]['source_header_lines'] == [4]
    assert result['decays'][0]['width_category'] == 'stable'
    assert [row['pdg'] for row in result['parser_added_decay_defaults']] == [1002]
    assert result['parser_added_decay_defaults'][0]['source_header_lines'] == []
    assert 'not supplied widths' in result['lifetime_note']


def test_duplicate_decay_headers_preserve_consumer_rows_and_literal_provenance(tmp_path, monkeypatch):
    card = tmp_path / 'duplicate.slha'
    source = 'BLOCK MASS\n  1001 100\nDECAY 1001 1.0\n  1.0 2 1 -1\ndecay 1001 2.0\n  0.4 2 2 -2\n'
    card.write_text(source)
    # The qualified consumer overwrites the table on a repeated header. The
    # inventory must preserve its effective row, with every source header visible.
    parsed = SimpleNamespace(xsections={}, blocks={'MASS': {1001: 100}}, decays={
        1001: SimpleNamespace(totalwidth=2.0, decays=[SimpleNamespace(br=0.4, ids=[2, -2])])})
    monkeypatch.setitem(sys.modules, 'pyslha', SimpleNamespace(readSLHAFile=lambda path: parsed))
    result = m._physical_input(card, 'slha', m.SETTINGS)
    assert card.read_text() == source
    assert [row['width_token'] for row in result['literal_decay_headers']] == ['1.0', '2.0']
    assert result['decays'][0]['source_header_lines'] == [3, 5]
    assert result['decays'][0]['width_gev'] == 2.0
    assert result['decays'][0]['channels'] == [{'branching_fraction': 0.4, 'daughter_pdgs': [2, -2]}]
    assert 'duplicate-header semantics are unchanged' in result['decay_consumer_note']


def test_literal_unknown_decay_width_remains_unknown(tmp_path):
    card = tmp_path / 'unknown.slha'
    card.write_text('DECAY 1001 NAN\n')
    header = m._source_decay_headers(card)[0]
    assert header['width_token'] == 'NAN' and header['width_gev'] is None
    assert header['recognized_header'] is True
    json.dumps(header, allow_nan=False)


def row(analysis,dataset,expected,observed,kind='efficiencyMap',xsec=1):
    return {'AnalysisID':analysis,'DataSetID':dataset,'r_expected':expected,'r':observed,
        'dataType':kind,'theory prediction (fb)':xsec}


def test_observed_r_does_not_choose_result():
    a=[row('A','SR1',1,100),row('B','SR2',2,.1)]
    choice=m.select_expected(a);assert a[choice['selected']['record_index']]['AnalysisID']=='B'
    a[0]['r']=None;a[1]['r']=1e10
    assert m.select_expected(a)==choice


def test_missing_expected_is_informational():
    assert m.select_expected([row('A','UL',None,50,'upperLimit')])['selected'] is None


def test_native_combination_preferred_without_observed_selection():
    a=[row('A','SR1',3,10),row('A','combined',2,None,'combined')]
    chosen=m.select_expected(a)['selected'];assert chosen['record_index']==1
    native={'output_status':{'decomposition status':1},'predictions':a,'coverage':[]}
    assert m.summarize(native)['conclusion']['status']=='selected_prediction_inference_unavailable'
    assert m.summarize(native)['conclusion']['excluded'] is None


def test_expected_tie_independent_of_observed_order():
    a=[row('A','SR2',2,50),row('A','SR1',2,.1)]
    assert a[m.select_expected(a)['selected']['record_index']]['DataSetID']=='SR1'
    a.reverse();assert a[m.select_expected(a)['selected']['record_index']]['DataSetID']=='SR1'


def test_no_predictions_is_not_nonexclusion():
    native={'output_status':{'decomposition status':0},'predictions':[],'coverage':[]}
    answer=m.summarize(native)['conclusion']
    assert answer['status']=='no_applicable_prediction' and answer['excluded'] is None


def test_coverage_groups_are_not_summed():
    native={'output_status':{'decomposition status':0},'predictions':[],
        'coverage':[{'label':'missing (all)','total_xsec_fb':2,'signatures':[{'sms':'x'}]}]}
    value=m.summarize(native)
    assert value['coverage']['groups_must_not_be_summed'] is True
    assert value['follow_up'][0]['source_signature']=='x'


def document():
    pin = {'path': 'input.dat', 'sha256': '0'*64}
    return {'schema_version': 1, 'source': 'Explicit synthetic control',
        'model_input': {'file': deepcopy(pin), 'format': 'slha'},
        'database': {'file': deepcopy(pin), 'version': '3.1.1',
            'source_url': 'https://example.org/official311.pcl', 'trusted_pickle': True},
        'runtime': {'python': deepcopy(pin), 'manifest': deepcopy(pin), 'smodels_version': '3.1.1'},
        'model': {'kind': 'mssm', 'file': None}, 'settings': deepcopy(m.SETTINGS),
        'max_seconds': 1, 'max_ram_mib': 512}


def test_zero_condition_sentinel_is_not_strict_filter():
    doc = document();doc['settings']['maxcond'] = 0
    with pytest.raises(ValueError, match='condition'):
        m.validate_document(doc)


@pytest.mark.parametrize('field,value', [('max_seconds', 0), ('max_seconds', True),
    ('max_ram_mib', 8193), ('max_ram_mib', 511)])
def test_resource_contract_rejects_unadmitted_bounds(field, value):
    doc = document();doc[field] = value
    with pytest.raises(ValueError):
        m.validate_document(doc)


def test_distinct_cluster_tie_does_not_follow_observed_printer_order():
    a = row('A', None, 2, 50, 'upperLimit');a['native_sms_ids']=[2]
    b = row('A', None, 2, .1, 'upperLimit');b['native_sms_ids']=[1]
    a['Mass (GeV)']=[['gluino', 600]];b['Mass (GeV)']=[['gluino', 500]]
    records=[a,b]
    assert records[m.select_expected(records)['selected']['record_index']] is b
    records.reverse()
    assert records[m.select_expected(records)['selected']['record_index']] is b


def test_energy_tie_has_deterministic_source_identity():
    a = row('A', None, 2, 50, 'upperLimit');a['AnalysisSqrts (TeV)']=8
    b = row('A', None, 2, .1, 'upperLimit');b['AnalysisSqrts (TeV)']=13
    records=[a,b]
    selected=records[m.select_expected(records)['selected']['record_index']]
    records.reverse()
    assert records[m.select_expected(records)['selected']['record_index']] is selected


def test_bound_file_drift_is_rejected(tmp_path):
    model=tmp_path/'model.slha';model.write_text('original cross sections and decays\n')
    pin=m._pin(model);model.write_text('changed model\n')
    with pytest.raises(ValueError,match='changed'):
        m._bound(pin,tmp_path)


def test_native_supervisor_retains_resource_receipt(tmp_path):
    receipt=m.execute_native([sys.executable,'-c','print("engineering process control")'],tmp_path,document())
    assert receipt['returncode']==0 and receipt['new_events_generated']==0
    assert receipt['resource_violation'] is None
    assert set(receipt['thread_limits'].values()) == {'1'}
    assert json.loads((tmp_path/'native-execution.json').read_text()) == receipt


def test_native_timeout_retains_failure(tmp_path):
    with pytest.raises(ValueError,match='time ceiling'):
        m.execute_native([sys.executable,'-c','import time;time.sleep(5)'],tmp_path,document())
    receipt=json.loads((tmp_path/'native-execution.json').read_text())
    assert receipt['returncode'] != 0 and receipt['resource_violation'] == 'native execution exceeded time ceiling'
    assert receipt['wall_seconds'] < 5


def test_combined_region_witness_keeps_native_zero_fill():
    a=SimpleNamespace(getID=lambda:'A',getLumi=lambda:10)
    b=SimpleNamespace(getID=lambda:'B',getLumi=lambda:20)
    tp=SimpleNamespace(dataType=lambda:'combined',dataset=SimpleNamespace(origdatasets=[a,b]),
        datasetPredictions=[SimpleNamespace(dataset=a,xsection=2)])
    assert m._combined_regions(tp,None)==[
        {'dataset_id':'A','signal_xsec_fb':2.,'signal_yield':20.,'matched_prediction':True},
        {'dataset_id':'B','signal_xsec_fb':0.,'signal_yield':0.,'matched_prediction':False}]


def test_native_node_values_keep_precision_and_infinity():
    assert m._node_quantity(675.123456789,None)==675.123456789
    assert m._node_quantity([0.,float('inf')],None)==[0.,{'native_sentinel':'positive_infinity'}]
    with pytest.raises(ValueError,match='NaN'):
        m._node_quantity(float('nan'),None)


@pytest.mark.parametrize('interrupt', [signal.SIGTERM,signal.SIGINT])
def test_external_interrupt_kills_escaped_resistant_native_group(tmp_path,interrupt):
    ready=tmp_path/'child-ready'
    native_code='import signal,time;from pathlib import Path;signal.signal(signal.SIGTERM,signal.SIG_IGN);Path('+repr(str(ready))+').write_text("ready");time.sleep(30)'
    wrapper='from ravel.physics.reinterpret_db import execute_native;execute_native('+repr([sys.executable,'-c',native_code])+','+repr(str(tmp_path))+','+repr({**document(),'max_seconds':10})+')'
    proc=subprocess.Popen([sys.executable,'-c',wrapper],start_new_session=True,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
    native_pid=None
    try:
        deadline=time.monotonic()+5
        while not ready.exists() and proc.poll() is None and time.monotonic()<deadline:
            time.sleep(.02)
        assert ready.exists()
        native_pid=json.loads((tmp_path/'native-process.json').read_text())['pid']
        start=time.monotonic();os.killpg(proc.pid,interrupt);proc.wait(timeout=2)
        assert time.monotonic()-start < 2 and proc.returncode != 0
        receipt=json.loads((tmp_path/'native-execution.json').read_text())
        assert receipt['received_signals']==[interrupt.name]
        assert 'interrupted' in receipt['resource_violation']
        with pytest.raises(ProcessLookupError):
            os.kill(native_pid,0)
    finally:
        if proc.poll() is None:
            os.killpg(proc.pid,signal.SIGKILL);proc.wait(timeout=2)
        if native_pid is not None:
            try:os.killpg(native_pid,signal.SIGKILL)
            except ProcessLookupError:pass
