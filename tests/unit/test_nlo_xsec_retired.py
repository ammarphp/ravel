"""Legacy imports delegate to selected offline conventions without process defaults."""
import pytest
from ravel.physics import nlo_xsec as legacy


def test_default_cli_refuses_without_an_input(tmp_path):
    out = tmp_path / 'rate.json'
    with pytest.raises(SystemExit):
        legacy.main(['--process','ANA-0001','--mass','700','--out',str(out)])
    assert not out.exists()


@pytest.mark.parametrize('operation', [legacy.load_lo_ref, legacy.hepi_grid, legacy.slepton_k])
def test_bare_legacy_import_refuses_with_typed_missing_input(operation):
    with pytest.raises(ValueError) as error:
        operation()
    assert error.value.reason_code == 'missing_cross_section_input'


def test_no_process_population_or_network_fetch_is_installed():
    assert all(not hasattr(legacy,name) for name in ('FILES','RAW','LO_REF','_get','K_FALLBACK'))


def test_legacy_cli_process_switch_is_typed_missing_input():
    with pytest.raises(SystemExit) as error:
        legacy.main(['--process','ANA-0014','--mass','100'])
    assert getattr(error.value,'reason_code',None) == 'missing_cross_section_input'
