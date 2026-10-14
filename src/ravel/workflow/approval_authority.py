"""Evidence-based approval labels; a quote never authenticates human identity."""
import os
import sys

AUTHORITIES = ('human_operator', 'human_relayed', 'delegated_machine', 'scripted_experiment', 'unknown')
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
        return 'human_relayed'
    if interactive and not agent_session:
        return 'human_operator'
    return 'unknown'


def authority(receipt):
    """Read legacy evidence conservatively; absent authority is unknown."""
    if not isinstance(receipt, dict):
        return 'unknown'
    if receipt.get('authority') == 'machine_under_user_delegation' or receipt.get('approval_mode') == 'delegated_machine':
        return 'delegated_machine'
    if receipt.get('approval_mode') == 'scripted_yes' or receipt.get('scripted') is True:
        return 'scripted_experiment'
    return receipt.get('authority') if receipt.get('authority') in AUTHORITIES else 'unknown'
