"""Declarative LHE transforms on tiny synthetic files."""
from copy import deepcopy
import gzip
import json
from pathlib import Path

import pytest

from ravel.physics import lhe_transform as lt
from ravel.physics import svj_lhe_transform as svj

DATA = Path(lt.__file__).resolve().parents[1] / "data/lhe_transforms"

HEAD = """<LesHouchesEvents version="3.0">
<header>
<MGVersion>3.7.0</MGVersion>
<initrwgt><weightgroup name="scale"><weight id="mur2">muR=2</weight></weightgroup></initrwgt>
</header>
<init>
2212 2212 6500 6500 0 0 82400 82400 -4 1
1.25e-2 3.0e-4 1.0 1
</init>
"""
EVENT = """<event>
4 1 +1.25e-02 1.0e+03 7.5e-03 1.1e-01
-11 -1 0 0 0 0 0 0 +4.0e+02 4.0e+02 0.0 0 9
2 -1 0 0 501 0 0 0 -3.0e+02 3.0e+02 0.0 0 9
-11 1 1 2 0 0 {px} 0 +5.0e+01 3.5e+02 0.0 0 9
2 1 1 2 501 0 -{px} 0 +5.0e+01 3.5e+02 0.0 0 9
<rwgt>
<wgt id='mur2'> +1.1e-02 </wgt>
</rwgt>
</event>
"""


def lhe(events=3, gz=False, path=None):
    px = repr((350.0 ** 2 - 50.0 ** 2) ** .5)
    text = HEAD + EVENT.format(px=px) * events + "</LesHouchesEvents>\n"
    if gz:
        path.write_bytes(gzip.compress(text.encode()))
    else:
        path.write_text(text)
    return path


def rules(name="lepton-to-photon-proxy.json"):
    return json.loads((DATA / name).read_text())


@pytest.mark.parametrize("gz", [False, True])
def test_lepton_to_photon_keeps_everything_but_the_declared_fields(tmp_path, gz):
    source = lhe(3, gz, tmp_path / ("in.lhe.gz" if gz else "in.lhe"))
    before = lt.pin(source)
    output = tmp_path / ("out.lhe.gz" if gz else "out.lhe")
    receipt = lt.transform(source, output, rules())
    assert receipt["events"] == 3 and receipt["events_changed"] == 3
    assert receipt["census"] == {"incoming-leptons": {"-11->22": 3}}
    assert receipt["original"] == before == lt.pin(source)
    assert receipt["output"] == lt.pin(output)
    assert receipt["invariants"]["max_momentum_imbalance"] < 1e-12
    assert receipt["required_downstream_settings"] == ["Check:event = off"]
    assert receipt["declared_changes"] == ["changes_charge", "changes_lepton_number"]
    assert "Check:event = off" in receipt["checkin_text"] and receipt["deviations"]
    read = (lambda p: gzip.decompress(p.read_bytes()).decode()) if gz else (lambda p: p.read_text())
    old, new = read(source).splitlines(), read(output).splitlines()
    assert len(old) == len(new)
    diffs = [(a, b) for a, b in zip(old, new) if a != b]
    assert len(diffs) == 3
    for a, b in diffs:
        assert a.split()[0] == "-11" and b.split()[0] == "22"
        assert a.split()[1:10] == b.split()[1:10] and a.split()[11:] == b.split()[11:]
    assert Path(str(output) + ".transform.json").is_file()
    # The outgoing positron is untouched: only status -1 matches.
    assert sum(line.split()[:2] == ["-11", "1"] for line in new) == 3


def test_the_verifier_refuses_any_other_change(tmp_path):
    source = lhe(2, path=tmp_path / "in.lhe")
    lt.transform(source, tmp_path / "out.lhe", rules())
    tampered = tmp_path / "tampered.lhe"
    tampered.write_text((tmp_path / "out.lhe").read_text().replace("+1.1e-02", "+1.2e-02", 1))
    with pytest.raises(ValueError, match="outside the particle rows"):
        lt.verify_pair(source, tampered, rules())
    tampered.unlink()
    tampered.write_text((tmp_path / "out.lhe").read_text().replace("2 -1 0 0 501", "1 -1 0 0 501", 1))
    with pytest.raises(ValueError, match="unmatched particle row"):
        lt.verify_pair(source, tampered, rules())


def test_charge_change_must_be_declared():
    doc = rules()
    doc["rules"][0]["declares"] = ["changes_lepton_number"]
    with pytest.raises(ValueError, match="changes charge"):
        lt.validate_rules(doc)


def test_outgoing_particles_need_a_declaration():
    doc = rules()
    doc["rules"][0]["match"]["status"] = [-1, 1]
    with pytest.raises(ValueError, match="touches_outgoing"):
        lt.validate_rules(doc)


def test_colour_representation_change_is_refused():
    doc = rules()
    doc["rules"][0]["match"]["pdg"] = [2]
    with pytest.raises(ValueError, match="colour"):
        lt.validate_rules(doc)


def test_unknown_particle_needs_declared_quantum_numbers():
    doc = rules()
    doc["rules"][0]["replace_pdg"] = 9000005
    with pytest.raises(ValueError, match="particle_data"):
        lt.validate_rules(doc)


def test_check_event_on_conflicts_with_a_charge_change():
    doc = rules()
    doc["downstream_settings"] = ["Check:event = on"]
    with pytest.raises(ValueError, match="Check:event"):
        lt.validate_rules(doc)


def test_mass_reset_that_breaks_the_mass_shell_is_refused(tmp_path):
    doc = rules()
    doc["rules"][0]["mass_gev"] = 5.0
    source = lhe(1, path=tmp_path / "in.lhe")
    with pytest.raises(ValueError, match="never changes momenta"):
        lt.transform(source, tmp_path / "out.lhe", doc)
    assert not (tmp_path / "out.lhe").exists() and (tmp_path / "failed-out.lhe").exists()


def test_overlapping_rules_are_refused():
    doc = rules()
    second = deepcopy(doc["rules"][0])
    second["id"] = "again"
    doc["rules"].append(second)
    with pytest.raises(ValueError, match="matched by rules"):
        lt.validate_rules(doc)


def test_missing_settings_and_census(tmp_path):
    source = lhe(2, path=tmp_path / "in.lhe")
    receipt = lt.transform(source, tmp_path / "out.lhe", rules())
    assert lt.missing_settings(receipt, ["PartonLevel:MPI = off"]) == ["Check:event = off"]
    assert lt.missing_settings(receipt, ["check:event=OFF"]) == []
    counted = lt.census(source, rules())
    assert counted["census"] == {"incoming-leptons": {"-11->22": 2}} and counted["events"] == 2


def test_svj_remap_runs_as_an_instance(tmp_path):
    doc = rules("svj-dark-flavour.json")
    implied = lt.validate_rules(doc)
    for pdg in svj.PRESENT:
        for sign in (1, -1):
            rule = next(r for r in doc["rules"] if (1, sign * pdg) in {(s, p) for s in r["match"]["status"] for p in r["match"]["pdg"]})
            assert lt.new_pdg(rule, sign * pdg) == sign * svj.TARGET
    assert implied["breaks"] == [] and implied["required_settings"] == []
    text = (HEAD + "<event>\n4 1 +1.0e-02 1.0e+03 7.5e-03 1.1e-01\n"
            "2 -1 0 0 501 0 0 0 +5.0e+02 5.0e+02 0.0 0 9\n"
            "-2 -1 0 0 0 501 0 0 -5.0e+02 5.0e+02 0.0 0 9\n"
            "49001012 1 1 2 0 0 +3.0e+02 0 0 3.0e+02 0.0 0 9\n"
            "-49001013 1 1 2 0 0 -3.0e+02 0 0 3.0e+02 0.0 0 9\n</event>\n</LesHouchesEvents>\n")
    source = tmp_path / "svj.lhe"
    source.write_text(text)
    receipt = lt.transform(source, tmp_path / "svj-out.lhe", doc)
    assert receipt["census"] == {"dark-quarks": {"-49001013->-4900101": 1, "49001012->4900101": 1}}
    assert receipt["required_downstream_settings"] == []


def test_science_mode_protocol(tmp_path):
    source = lhe(2, path=tmp_path / "in.lhe")
    (tmp_path / "rules.json").write_text(json.dumps(rules()))
    task = {"input": "in.lhe", "rules": "rules.json"}
    assert lt.inputs(task, tmp_path) == [source.resolve(), (tmp_path / "rules.json").resolve()]
    result = lt.run(task, tmp_path, tmp_path / "out")
    assert result["status"] == "passed" and result["events_changed"] == 2
    assert (tmp_path / "out/lhe-transform.json").is_file()
    with pytest.raises(ValueError):
        lt.validate({"input": "in.lhe"})


def test_cli_check_is_read_only(tmp_path, capsys):
    source = lhe(1, path=tmp_path / "in.lhe")
    (tmp_path / "rules.json").write_text(json.dumps(rules()))
    assert lt.main(["check", "--rules", str(tmp_path / "rules.json"), "--input", str(source)]) == 0
    assert json.loads(capsys.readouterr().out)["census"] == {"incoming-leptons": {"-11->22": 1}}
    assert sorted(p.name for p in tmp_path.iterdir()) == ["in.lhe", "rules.json"]
