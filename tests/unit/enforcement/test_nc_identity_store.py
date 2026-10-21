"""Code identity and store custody rows: the controller runs installed code and keeps its own store.

The adversary points selectors at a modified checkout, relocates state with environment
variables, copies or renames a run to shed its custody, and reaches a run through a symlink
alias. Oracles are the identity guard's refusal, the store's binding checks and ownership
lookups; positive controls are an installed identity, the bound directory and the real path.
"""
from __future__ import annotations

import os
from pathlib import Path
import shutil

import pytest

from nc_cases import CONTROLLER, case, require_controller
from nc_controller import controller_run, store_root
from nc_mutations import CONTROLLER as MUTATION_CONTROLLER, Mutation, register


def _installed_identity():
    return {'package_dir': '/fictional/site-packages/ravel', 'kind': 'installed', 'version': '1.3.0',
            'checkout': None, 'writable_by_controller_user': False, 'selectors': {}, 'digest': 'record:' + 'a' * 64}


@case('SW23', binding=CONTROLLER)
def test_SW23_controller_mode_refuses_a_source_checkout_or_a_redirected_root(nc):
    confine = require_controller('confine')
    with pytest.raises(confine.UngovernedInstall):
        confine.require_governed_install()  # this suite runs from a writable source checkout
    checkout = nc.root / 'modified-checkout'
    (checkout / 'src' / 'ravel').mkdir(parents=True)
    nc.patch.setenv('RAVEL_ROOT', str(checkout))
    with pytest.raises(confine.UngovernedInstall, match='RAVEL_ROOT'):
        confine.require_governed_install(identity=dict(_installed_identity(), selectors={'RAVEL_ROOT': str(checkout)}))
    labelled = confine.require_governed_install(development=True)
    assert labelled['governed'] is False and labelled['label'] == confine.NOT_GOVERNED
    accepted = confine.require_governed_install(identity=_installed_identity())  # positive control
    assert accepted['governed'] is True and accepted['label'] is None


def _always_governed(original):
    def require(*, development=False, identity=None):
        found = dict(identity or {'kind': 'installed', 'selectors': {}, 'package_dir': '?'})
        return dict(found, governed=True, label=None, problems=[])
    return require


register(Mutation('M23', ('ravel.controller.confine.identity:require_governed_install',
                          'ravel.controller.confine:require_governed_install'),
                  _always_governed, ('SW23', 'SW29'), binding=MUTATION_CONTROLLER,
                  why='controller mode accepts any code location'),
         Mutation('SW23', ('ravel.controller.confine.identity:require_governed_install',
                           'ravel.controller.confine:require_governed_install'),
                  _always_governed, ('SW23',), binding=MUTATION_CONTROLLER, why='checkouts accepted'),
         Mutation('SW29', ('ravel.controller.confine.identity:require_governed_install',
                           'ravel.controller.confine:require_governed_install'),
                  _always_governed, ('SW29',), binding=MUTATION_CONTROLLER, why='editable installs accepted'))


@case('SW29', binding=CONTROLLER)
def test_SW29_an_editable_install_whose_package_data_is_writable_is_refused(nc):
    confine = require_controller('confine')
    editable = dict(_installed_identity(), kind='editable', writable_by_controller_user=True,
                    package_dir=str(nc.root / 'editable' / 'ravel'))
    with pytest.raises(confine.UngovernedInstall):
        confine.require_governed_install(identity=editable)
    # A provider registry edited in the run tree is never read by the decision gate.
    from ravel.workflow import decision_gate
    installed = decision_gate._registry()
    nc.write_json('run/gates/providers.json', {'providers': [], 'required_providers': {}})
    nc.write_json('run/src/ravel/data/gates/providers.json', {'providers': [], 'required_providers': {}})
    assert decision_gate._registry() == installed
    assert confine.require_governed_install(identity=_installed_identity())['governed'] is True  # positive


@case('SW20', binding=CONTROLLER)
def test_SW20_state_and_work_root_variables_do_not_relocate_the_controller_store(nc):
    store_module = require_controller('store')
    hijack = nc.root / 'worker-writable'
    hijack.mkdir()
    nc.patch.setenv('RAVEL_STATE_DIR', str(hijack / 'state'))
    nc.patch.setenv('RAVEL_WORK_ROOT', str(hijack / 'work'))
    store, run_dir = controller_run(nc)
    assert Path(store.root).is_relative_to(Path(os.path.realpath(store_root(nc))))
    assert not any(hijack.rglob('*')), 'nothing of the controller run lands under the relocated roots'
    assert store_module.controller_owned(run_dir) == store.run_id  # positive control: the run is found


@case('C41', binding=CONTROLLER)
def test_C41_a_copied_or_renamed_run_cannot_shed_its_custody_or_start_fresh(nc):
    store_module = require_controller('store')
    store, run_dir = controller_run(nc)
    store.append('nc-probe', {'spent': 'fictional budget'})
    copy = nc.root / 'runs' / 'copied-run'
    shutil.copytree(run_dir, copy)
    assert store_module.controller_owned(copy) == store.run_id, 'a copy is still the same controller run'
    assert store.check_binding(copy), 'resuming from a copy is refused'
    with pytest.raises(store_module.StoreError):
        store_module.RunStore.create(run_dir)
    renamed = nc.root / 'runs' / 'renamed-run'
    run_dir.rename(renamed)
    assert store.check_binding(renamed), 'a moved directory is not the bound one'
    renamed.rename(run_dir)
    assert store.check_binding(run_dir) == []  # positive control: the bound directory resumes


@case('C25', binding=CONTROLLER)
def test_C25_an_alias_or_an_outside_working_directory_does_not_evade_run_identity(nc):
    store_module = require_controller('store')
    store, run_dir = controller_run(nc)
    alias = nc.root / 'elsewhere' / 'alias'
    alias.parent.mkdir(parents=True)
    alias.symlink_to(run_dir, target_is_directory=True)
    assert store_module.controller_owned(alias) == store.run_id
    assert store_module.controller_owned(alias / 'inputs' / 'anything.json') == store.run_id
    assert store_module.controller_owned(store.root) == store.run_id
    outside = nc.root / 'outside'
    outside.mkdir()
    assert store_module.controller_owned(outside) is None  # positive control: an unrelated directory


def _state_dir_relocates(original):
    """The store root follows RAVEL_STATE_DIR, as legacy custody did."""
    def store_root():
        value = os.environ.get('RAVEL_STATE_DIR')
        return Path(os.path.realpath(value)) / 'controller' if value else original()
    return store_root


register(Mutation('SW20', 'ravel.controller.store:store_root', _state_dir_relocates, ('SW20',),
                  binding=MUTATION_CONTROLLER, why='an environment variable relocates the controller store'))
