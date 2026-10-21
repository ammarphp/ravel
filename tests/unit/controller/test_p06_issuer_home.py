"""Issuer state follows the test lock domain, so test runs never write into the user's real home."""
import os
from pathlib import Path
import pwd

from ravel.controller.authority import issuer, operator
from ravel.workflow import machine_lease


def test_issuer_state_stays_inside_the_test_domain():
    path, kind = machine_lease._resolve()
    assert kind == 'test'
    assert issuer.home() == Path(path) / 'ravel-authority'
    real = Path(pwd.getpwuid(os.getuid()).pw_dir) / '.local/state/ravel-authority'
    assert issuer.home() != real


def test_issuer_and_operator_homes_share_the_domain():
    path, _ = machine_lease._resolve()
    assert issuer.home().parent == operator.controller_home().parent == Path(path)
