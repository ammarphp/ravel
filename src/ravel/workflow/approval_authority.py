"""Evidence-based approval labels; a quote, a terminal or a missing marker never authenticates a human.

An interactive terminal with no agent session marker is evidence that someone at a terminal ran
the command, not that a physicist did: an agent can allocate a pseudo-terminal and unset its
markers. Such a decision is labelled ``terminal_operator_unattested``; legacy gates accept it
where they accepted ``human_operator``. ``human_operator`` is never inferred. Controller-owned
runs take authority only from the controller authority service (``ravel.controller.authority``).
"""
import os
import sys

TERMINAL_UNATTESTED = 'terminal_operator_unattested'
CALLER_UNATTESTED = 'caller_text_unattested'
# A case approval confirmed at the controller's own terminal (``approval_capture``), or approved
# through a controller authority-service record (an operator command).
CONTROLLER_CAPTURE = 'controller_capture'
OPERATOR_COMMAND = 'operator_command'
GOVERNED = (CONTROLLER_CAPTURE, OPERATOR_COMMAND)
# ``human_operator`` stays a known label so historical receipts still read; nothing new carries it.
AUTHORITIES = ('human_operator', 'human_relayed', 'delegated_machine', 'scripted_experiment', TERMINAL_UNATTESTED, CALLER_UNATTESTED,
               CONTROLLER_CAPTURE, OPERATOR_COMMAND, 'unknown')
# Only session markers are inspected; no environment values or credentials are read.
AGENT_MARKERS = ('RAVEL_SESSION_ID', 'CLAUDE_CODE_SESSION_ID', 'CODEX_THREAD_ID', 'CODEX_SESSION_ID', 'RAVEL_AGENT_ID', 'CLAUDECODE')


def classify(*, scripted=False, delegated=False, quote=None, agent_session=None, interactive=None):
    if delegated:
        return 'delegated_machine'
    if scripted:
        return 'scripted_experiment'
    if agent_session is None:
        agent_session = any(name in os.environ for name in AGENT_MARKERS)
    if interactive is None:
        interactive = sys.stdin.isatty() and sys.stdout.isatty()
    if agent_session and isinstance(quote, str) and quote.strip():
        return CALLER_UNATTESTED
    if interactive and not agent_session:
        return TERMINAL_UNATTESTED
    return 'unknown'


def authority(receipt):
    """Read legacy evidence conservatively; absent authority is unknown.

    A historical ``human_operator`` label was inferred from a terminal, so it reads as
    ``terminal_operator_unattested``.
    """
    if not isinstance(receipt, dict):
        return 'unknown'
    if receipt.get('authority') == 'machine_under_user_delegation' or receipt.get('approval_mode') == 'delegated_machine':
        return 'delegated_machine'
    if receipt.get('approval_mode') == 'scripted_yes' or receipt.get('scripted') is True:
        return 'scripted_experiment'
    if receipt.get('authority') == 'human_relayed':
        return CALLER_UNATTESTED
    if receipt.get('authority') == 'human_operator':
        return TERMINAL_UNATTESTED
    return receipt.get('authority') if receipt.get('authority') in AUTHORITIES else 'unknown'


def case_approval(record):
    """The label and governance of one recorded case-approval row; a label, never credit.

    Only a row carrying a controller capture attestation or a controller authority-service
    reference is of a governed kind, and its credit still requires live verification
    (``rdj_loop._human``). Any other row, including a historical ``approve`` row from
    caller text or a ``human_approver: true`` claim, stays readable as ``NOT GOVERNED``.
    """
    if not isinstance(record, dict):
        return {'authority': 'unknown', 'governance': 'NOT GOVERNED'}
    if record.get('attestation') is not None:
        return {'authority': CONTROLLER_CAPTURE, 'governance': 'verify'}
    if record.get('authority') is not None and isinstance(record.get('authority'), dict):
        return {'authority': OPERATOR_COMMAND, 'governance': 'verify'}
    label = CALLER_UNATTESTED if record.get('decision') in ('approve', 'unattested_approve') else 'unknown'
    return {'authority': label, 'governance': 'NOT GOVERNED'}
