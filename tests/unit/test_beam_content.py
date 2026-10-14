"""Beam/PDF parton content and generator-version selection (no native tools run)."""
from pathlib import Path

import pytest

from ravel.physics import beam_content as bc
from ravel.physics import generator_versions as gv

LUX_FLAVOURS = [-15, -13, -11, -5, -4, -3, -2, -1, 1, 2, 3, 4, 5, 11, 13, 15, 21, 22]
NNPDF30_FLAVOURS = [-5, -4, -3, -2, -1, 1, 2, 3, 4, 5, 21]


def lepton_quark(**settings):
    run = {"ebeam1": 6500, "ebeam2": 6500, "lpp1": 1, "lpp2": 1, "pdlabel": "lhapdf", "lhaid": 82400}
    run.update(settings)
    return {"process": "pl pq > lq", "beam_pdg": [2212, 2212], "run_settings": run,
            "definitions": {"pl": "e+ e- mu+ mu-", "pq": "u d u~ d~"}}


def test_lepton_partons_admitted_with_a_lepton_pdf_under_madgraph_3():
    record, errors = bc.content(lepton_quark(), pdf_flavours=LUX_FLAVOURS, generator_version="3.7.0")
    assert not errors
    assert record["lepton_or_photon_partons"] == [-13, -11, 11, 13]
    assert record["minimum_generator_version"] == "3.0.0"
    assert record["beams"][0]["partons"] == [-13, -11, 11, 13]


def test_lepton_partons_refused_with_a_set_lacking_them():
    _, errors = bc.content(lepton_quark(lhaid=260000), pdf_flavours=NNPDF30_FLAVOURS, generator_version="3.7.0")
    assert any("does not carry partons [-13, -11, 11, 13]" in e for e in errors)


def test_lepton_partons_refused_under_madgraph_2():
    _, errors = bc.content(lepton_quark(), pdf_flavours=LUX_FLAVOURS, generator_version="2.9.27")
    assert any("MadGraph 3.0.0 or later" in e for e in errors)


def test_photon_partons_need_the_photon_flavour_but_not_madgraph_3():
    g = lepton_quark()
    g["definitions"]["pl"] = "a"
    record, errors = bc.content(g, pdf_flavours=LUX_FLAVOURS, generator_version="2.9.27")
    assert not errors and record["minimum_generator_version"] is None
    _, errors = bc.content(g, pdf_flavours=NNPDF30_FLAVOURS, generator_version="2.9.27")
    assert any("[22]" in e for e in errors)


def test_builtin_pdf_cannot_supply_leptons():
    _, errors = bc.content(lepton_quark(pdlabel="nn23lo1", lhaid=247000))
    assert any("pdlabel=lhapdf" in e for e in errors)


@pytest.mark.parametrize("lpp", [0, -1, 2])
def test_declared_proton_beam_with_another_lpp_is_refused(lpp):
    errors = bc.beam_errors([2212, 2212], {"lpp1": 1, "lpp2": lpp})
    assert errors and "beam 2" in errors[0]


def test_lepton_beam_needs_lpp_zero_and_supplies_only_itself():
    g = {"process": "e+ e- > mu+ mu-", "beam_pdg": [-11, 11],
         "run_settings": {"lpp1": 0, "lpp2": 0, "pdlabel": "nn23lo1", "lhaid": 247000}, "definitions": {}}
    record, errors = bc.content(g)
    assert not errors and record["beams"][0]["kind"] == "lepton"
    g["beam_pdg"] = [11, 11]
    assert bc.content(g)[1]


def test_undeclared_multiparticle_in_initial_state_is_refused():
    g = lepton_quark()
    g["definitions"] = {}
    _, errors = bc.content(g)
    assert any("declare the multiparticle" in e for e in errors)


def test_madgraph_default_lpp2_zero_fails_readback():
    # MadGraph's create_default_for_process sets lpp1=1, lpp2=0 for an e u initial state.
    errors = bc.readback_errors([2212, 2212], {"lpp1": 1.0, "lpp2": 0.0}, ["2212", "0", "6500", "6500"])
    assert any("lpp2=0" in e for e in errors)
    assert not bc.readback_errors([2212, 2212], {"lpp1": 1, "lpp2": 1}, ["2212", "2212"])
    assert bc.readback_errors([2212, 2212], {"lpp1": 1}, ["2212", "2212"]) == ["effective run card lacks lpp2"]
    assert not bc.readback_errors([-11, 11], {"lpp1": 0, "lpp2": 0}, ["0", "0"])


def test_idbmup_follows_madgraph():
    assert [bc.idbmup(v) for v in (1, -1, 2, 3, -3, 4, -4, 0)] == [2212, -2212, 2212, 11, -11, 13, -13, 0]


def test_info_flavour_census(tmp_path):
    info = tmp_path / "SET.info"
    info.write_text("SetDesc: synthetic\nFlavors: [-5, -4, -3, -2, -1, 0, 1, 2, 3, 4, 5, 11, 22]\nOrderQCD: 1\n")
    assert bc.read_info_flavours(info) == [-5, -4, -3, -2, -1, 1, 2, 3, 4, 5, 11, 21, 22]
    info.write_text("SetDesc: none\n")
    with pytest.raises(ValueError, match="Flavors"):
        bc.read_info_flavours(info)


def test_pdf_sets_manifest_pins_and_refuses_unknown_ids():
    row = bc.pdf_manifest_row(82400)
    assert row["name"].startswith("LUXlep") and len(row["sha256"]) == 64
    with pytest.raises(ValueError, match="not pinned"):
        bc.pdf_manifest_row(999999)


def fake_install(prefix, versions):
    from ravel.setup import manifest
    entries = gv.installed_madgraph(prefix)
    for entry in entries:
        if entry["version"] not in versions:
            continue
        tree = Path(entry["tree"])
        (tree / "bin").mkdir(parents=True)
        (tree / "bin/mg5_aMC").write_text("# fixture\n")
        (tree / "VERSION").write_text(f"version = {entry['version']}\ndate = fixture\n")
        for key in ("python", "compiler", "lhapdf_config"):
            Path(entry[key]).parent.mkdir(parents=True, exist_ok=True)
            Path(entry[key]).write_text("# fixture\n")
    assert manifest  # imported for the manifest layout
    return gv.installed_madgraph(prefix)


def test_versions_come_from_the_manifest(tmp_path):
    entries = gv.installed_madgraph(tmp_path)
    assert [e["version"] for e in entries] == ["2.9.27", "3.7.0"]
    assert not any(e["installed"] for e in entries)
    assert entries[1]["python"].endswith("envs/mg5-3/bin/python")


def test_auto_selects_by_need(tmp_path):
    entries = fake_install(tmp_path, {"2.9.27", "3.7.0"})
    chosen, record = gv.select("auto", None, entries)
    assert chosen["version"] == "2.9.27" and "no version requirement" in record["reason"]
    chosen, record = gv.select("auto", "3.0.0", entries)
    assert chosen["version"] == "3.7.0" and record["minimum"] == "3.0.0"
    with pytest.raises(ValueError, match="needs MadGraph 3.0.0"):
        gv.select("2.9.27", "3.0.0", entries)


def test_missing_version_is_refused(tmp_path):
    entries = fake_install(tmp_path, {"2.9.27"})
    with pytest.raises(ValueError, match="no installed MadGraph"):
        gv.select("auto", "3.0.0", entries)
    with pytest.raises(ValueError, match="not installed"):
        gv.select("3.7.0", None, entries)
    with pytest.raises(ValueError, match="not declared"):
        gv.select("3.5.1", None, entries)


def test_flavour_scheme_record_and_massless_b():
    g = lepton_quark()
    g["definitions"]["pq"] = "u d b u~ d~ b~"
    record, _ = bc.content(g, pdf_flavours=LUX_FLAVOURS, generator_version="3.7.0")
    assert record["flavour_scheme"] == "5F"
    assert bc.scheme_errors(record, {"MASS": {(5,): 4.7}})
    assert not bc.scheme_errors(record, {"MASS": {(5,): 0.0}})
    g["definitions"]["pq"] = "u d u~ d~"
    record, _ = bc.content(g, pdf_flavours=LUX_FLAVOURS, generator_version="3.7.0")
    assert record["flavour_scheme"] == "4F" and not bc.scheme_errors(record, {"MASS": {(5,): 4.7}})
