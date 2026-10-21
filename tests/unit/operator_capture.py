"""Test stand-in for the operator at the controller terminal.

Production captures come only from ``approval_capture.capture_terminal`` reading the controlling
terminal. Tests replace that terminal exchange; the capture ledger, bindings and verification
remain the production code.
"""
from ravel.workflow import approval_capture


def confirm(purpose, binding):
    """Record the operator's confirmation of exactly this decision, as the terminal exchange would."""
    return approval_capture._record(purpose, approval_capture.binding_digest(binding), '0' * 64,
                                    {'name': None, 'rdev': 0})


def operator_at_terminal(monkeypatch, *, confirms=True):
    """Answer every terminal confirmation: confirm it, or refuse it. Returns the calls made."""
    calls = []

    def capture(purpose, binding, *, summary):
        calls.append({'purpose': purpose, 'binding': binding, 'summary': summary})
        if not confirms:
            raise approval_capture.CaptureRefused('the operator refused at the terminal; nothing was recorded')
        return confirm(purpose, binding)
    monkeypatch.setattr(approval_capture, 'capture_terminal', capture)
    return calls


def ledger_rows():
    from ravel.workflow import rdj_custody
    return rdj_custody._read(approval_capture._ledger())
