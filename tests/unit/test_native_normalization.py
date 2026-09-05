import json
import math
import pytest
from ravel.physics import native_normalization as norm


def sources(tmp_path,weights=(2.,-1.,3.),rate=2.):
    lhe=tmp_path/'events.lhe'
    events=''.join(f'<event>\n1 1 {weight} 1 1 1\n1 1 0 0 0 0 0 0 0 1 0 0 9\n</event>\n' for weight in weights)
    lhe.write_text(f'<LesHouchesEvents>\n<init>\n2212 2212 6500 6500 0 0 0 0 3 1\n{rate} 0.1 1 1\n</init>\n{events}</LesHouchesEvents>\n')
    mg=tmp_path/'mg.log';mg.write_text(f'Cross-section : {rate} +- 0.1 pb\n')
    shower=tmp_path/'shower.log';shower.write_text(f'pythia_shower: wrote {len(weights)} events; sigma = {rate/1e9} mb\n')
    return lhe,mg,shower


def test_lhe_units_signed_weights_and_one_subunit_correction(tmp_path):
    record=norm.resolve_normalization(*sources(tmp_path),.8,3)
    assert record['applied_cross_section_pb']==1.6 and record['generation']['sumw']==4 and record['generation']['sumw2']==14
    assert record['generation']['negative_weights']==1 and record['luminosity_applied'] is False
    path=tmp_path/'normalization.json';path.write_text(json.dumps(record));assert norm.load_normalization(path)==record
    record['applied_cross_section_pb']*=.8;path.write_text(json.dumps(record))
    with pytest.raises(ValueError,match='exactly once'):norm.load_normalization(path)


def test_missing_log_rate_uses_actual_lhe_evidence(tmp_path):
    lhe,mg,shower=sources(tmp_path);mg.write_text('reused existing generator integration\n')
    assert norm.resolve_normalization(lhe,mg,shower,1.,3)['cross_section_pb']==2.
    lhe.write_text(lhe.read_text().replace('<init>','<missing>'))
    with pytest.raises(ValueError):norm.resolve_normalization(lhe,mg,shower,1.,3)


@pytest.mark.parametrize('failure',['wrong_units','wrong_xs','shower_loss','shower_xs','missing_shower','truncated','wrong_requested_count'])
def test_normalization_failures_remain_unresolved(tmp_path,failure):
    lhe,mg,shower=sources(tmp_path);n=3
    if failure=='wrong_units':mg.write_text('Cross-section : 2 fb\n')
    if failure=='wrong_xs':mg.write_text('Cross-section : 4.000 pb\n')
    if failure=='shower_loss':shower.write_text('pythia_shower: wrote 2 events; sigma = 2e-9 mb\n')
    if failure=='shower_xs':shower.write_text('pythia_shower: wrote 3 events; sigma = 4e-9 mb\n')
    if failure=='missing_shower':shower.write_text('no rate\n')
    if failure=='truncated':lhe.write_text(lhe.read_text().replace('</LesHouchesEvents>',''))
    if failure=='wrong_requested_count':n=7
    with pytest.raises(ValueError):norm.resolve_normalization(lhe,mg,shower,1.,n)


@pytest.mark.parametrize('weights',[(1.,-1.),(-1.,-2.),(math.nan,), (math.inf,), (1e308,1e308), ()])
def test_invalid_physical_weight_normalizations_fail(tmp_path,weights):
    with pytest.raises(ValueError):norm.resolve_normalization(*sources(tmp_path,weights),1.,len(weights))


@pytest.mark.parametrize('correction',[None,False,0,-1,math.nan,math.inf])
def test_no_correction_default(tmp_path,correction):
    with pytest.raises(ValueError):norm.resolve_normalization(*sources(tmp_path),correction,3)


def test_per_event_conversion_detects_double_correction_and_sign_loss():
    audit=norm.reconcile_weights([2.,-1.,3.],[.8,-.4,1.2],1.6)
    assert audit['raw']['sumw']==4 and audit['normalized']['sumw']==pytest.approx(1.6) and audit['luminosity_applied'] is False
    with pytest.raises(ValueError):norm.reconcile_weights([2.,-1.,3.],[.64,-.32,.96],1.6)
    with pytest.raises(ValueError):norm.reconcile_weights([2.,-1.,3.],[.8,.4,.4],1.6)


def test_converter_does_not_inherit_upstream_defaults():
    from ravel.physics.delphes2sa_native import main
    with pytest.raises(ValueError,match='unresolved'):main(['--input','absent.root','--output','absent-out.root','--lumi','1'])
    with pytest.raises(SystemExit):main(['--input','absent.root','--output','absent-out.root','--XS','1'])


def test_normalization_recomputes_headline_rate_from_evidence(tmp_path):
    record=norm.resolve_normalization(*sources(tmp_path),.8,3)
    record['cross_section_pb']=200;record['applied_cross_section_pb']=160
    path=tmp_path/'normalization.json';path.write_text(json.dumps(record))
    with pytest.raises(ValueError,match='reconcile'):norm.load_normalization(path)
    record['sources']=record['sources'][:1];path.write_text(json.dumps(record))
    with pytest.raises(ValueError,match='evidence'):norm.load_normalization(path)
