"""Absent-policy compatibility: recover before interpreting malformed current plan."""
import sys
import pytest
from ravel.workflow import stage_supervisor,science


def test_absent_policy_recovery_precedes_science_review_lookup(tmp_path,monkeypatch):
    (tmp_path/'inputs').mkdir();(tmp_path/'inputs/science.json').write_text('{}')
    from method_decision_fixture import admit_method
    admit_method(tmp_path, refresh=False)
    calls=[]
    class Recovered(Exception):pass
    def recover(*args):calls.append('recovery');raise Recovered()
    def current(*args):calls.append('current-review');raise ValueError('malformed current plan')
    monkeypatch.setattr(stage_supervisor,'_recover_previous_attempt',recover)
    monkeypatch.setattr(science,'review_enabled',current)
    monkeypatch.setattr(stage_supervisor.subprocess,'Popen',lambda *a,**k:calls.append('Popen'))
    with pytest.raises(Recovered):
        stage_supervisor.supervise('science',tmp_path,0,'logs/science.log',[sys.executable,'-c','pass'],kill_secs=1,outputs=['out'])
    assert calls==['recovery']
