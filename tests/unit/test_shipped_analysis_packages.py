"""The shipped analysis packages: discovery finds them with no environment, they stay pending, and
nothing in discovery certifies them or executes their source."""
import hashlib
import json
from pathlib import Path
import re

import pytest

from ravel.physics import analysis_packages as packages
from ravel.physics import native_capabilities as capabilities
from ravel.physics.analysis_packages import PackageInputError, discover, load_package
from ravel.physics.sa_routines import REGISTRY

from analysis_package_fixtures import qualify_fixture

SHIPPED = Path(packages.SHIPPED_ROOT)
ROUTINES = ('EwkCompressed2018', 'EwkThreeLeptonERJR2018', 'ZeroLeptonDiscovery2018', 'DirectStau2018Calibrated')


def directory(name):
    """A package's directory is the lower-case hyphenated slug of its identity."""
    slug = re.sub(r'(?<=[a-z0-9])(?=[A-Z])|(?<=[A-Za-z])(?=\d)|(?<=\d)(?=[A-Za-z])', '-', name)
    return SHIPPED / slug.lower()


@pytest.fixture(autouse=True)
def no_supplied_roots(monkeypatch):
    for name in (packages.DISCOVERY_ENV, packages.PACKAGE_ENV, capabilities.ALIAS_ENV):
        monkeypatch.delenv(name, raising=False)


def test_default_discovery_finds_every_shipped_package_without_environment():
    found = discover()
    assert tuple(sorted(found)) == tuple(sorted(ROUTINES))
    assert {p.name for p in SHIPPED.iterdir() if p.is_dir()} == {directory(n).name for n in ROUTINES}
    for name, package in found.items():
        assert Path(package['manifest_path']).parent == directory(name).resolve()
        assert package['analysis_ids'][0] == name
        assert package['qualification'] == {'status': 'pending', 'evidence': []}
        assert package['physics_certified'] is False and package['compute_authorized'] is False


def test_shipped_manifests_pin_their_exact_source_bytes():
    for name in ROUTINES:
        manifest = json.loads((directory(name) / 'manifest.json').read_text())
        source = directory(name) / manifest['routine']['path']
        assert hashlib.sha256(source.read_bytes()).hexdigest() == manifest['routine']['sha256']
        assert load_package(directory(name))['source_pins'][1]['sha256'] == manifest['routine']['sha256']


def test_a_request_for_each_shipped_routine_resolves_to_its_package_and_is_not_certified():
    rows = capabilities.discover_capabilities()
    for name in ROUTINES:
        assert capabilities.adapter_for(name, {}) == name
        assert Path(rows[name]['analysis_package']).parent == directory(name).resolve()
        assert rows[name]['qualification']['status'] == 'pending' and rows[name]['physics_certified'] is False
        assert REGISTRY[name] == rows[name]['analysis_package']


def test_qualification_is_required_before_a_native_binding_is_admitted():
    for name, row in capabilities.discover_capabilities().items():
        binding = (row['models'][0], row['preparations'][0], row['detector'], row['statistics'][0])
        with pytest.raises(PackageInputError) as refused:
            capabilities.resolve_capability(name, *binding, aliases={})
        assert refused.value.reason == 'missing_package_qualification'


def test_declared_compatibility_is_enforced_once_a_report_binds_the_bytes(tmp_path):
    for name, row in capabilities.discover_capabilities().items():
        (tmp_path / name).mkdir()
        supplied = qualify_fixture(tmp_path / name, directory(name) / 'manifest.json')
        binding = (row['models'][0], row['preparations'][0], row['detector'], row['statistics'][0])
        resolved = capabilities.resolve_capability(name, *binding, aliases={}, analysis_package=supplied)
        assert resolved['routine'] == name and resolved['physics_certified'] is False
        with pytest.raises(PackageInputError) as refused:
            capabilities.resolve_capability(name, binding[0], binding[1], binding[2], 'no-such-statistics',
                                            aliases={}, analysis_package=supplied)
        assert refused.value.reason == 'unsupported_package_binding'


def test_a_supplied_package_with_a_shipped_identity_and_other_bytes_refuses(tmp_path, monkeypatch):
    clone = tmp_path / 'clone'
    clone.mkdir()
    for member in directory(ROUTINES[0]).iterdir():
        (clone / member.name).write_bytes(member.read_bytes())
    document = json.loads((clone / 'manifest.json').read_text())
    source = clone / document['routine']['path']
    source.write_bytes(source.read_bytes() + b'\n# changed\n')
    document['routine']['sha256'] = hashlib.sha256(source.read_bytes()).hexdigest()
    (clone / 'manifest.json').write_text(json.dumps(document))
    monkeypatch.setenv(packages.DISCOVERY_ENV, str(clone))
    with pytest.raises(PackageInputError) as refused:
        discover()
    assert refused.value.reason == 'ambiguous_analysis_package'


def test_a_qualified_restatement_over_the_shipped_bytes_replaces_the_pending_package(tmp_path, monkeypatch):
    qualified = qualify_fixture(tmp_path, directory(ROUTINES[0]) / 'manifest.json')
    monkeypatch.setenv(packages.DISCOVERY_ENV, str(qualified.parent))
    found = discover()
    assert tuple(sorted(found)) == tuple(sorted(ROUTINES))
    assert found[ROUTINES[0]]['qualification']['status'] == 'qualified'
    assert found[ROUTINES[0]]['manifest_path'] == str(qualified.resolve())
    assert all(found[n]['qualification']['status'] == 'pending' for n in ROUTINES[1:])
    row = capabilities.discover_capabilities()[ROUTINES[0]]
    binding = (row['models'][0], row['preparations'][0], row['detector'], row['statistics'][0])
    assert capabilities.resolve_capability(ROUTINES[0], *binding, aliases={})['physics_certified'] is False


def test_a_root_that_reaches_a_shipped_manifest_twice_counts_it_once(monkeypatch):
    monkeypatch.setenv(packages.DISCOVERY_ENV, str(SHIPPED))
    assert sorted(discover()) == sorted(ROUTINES)


def test_explicit_roots_replace_the_shipped_packages(tmp_path):
    assert discover([tmp_path]) == {}
