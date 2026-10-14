"""Response algebra controls without importing upstream Python or native ROOT."""
from fractions import Fraction
import hashlib
import json

import pytest

from ravel.physics import eft_functions as eft


SOURCE = '''from HiggsAnalysis.CombinedLimit.PhysicsModel import *
import re
class fM0(PhysicsModel):
    def doParametersOfInterest(self):
        self.modelBuilder.doVar("fm0[0.0,-15,15]")
        pois = 'fm0'
        self.modelBuilder.doSet("POI",pois)
        self.modelBuilder.factory_('expr::scale("(0.999999999+0.01234567890123456789*@0+2e-3*@0*@0+-3e-8*@0*@0*@0+4e-10*@0*@0*@0*@0+5e-12*@0*@0*@0*@0*@0)",fm0)')
    def getYieldScale(self,bin,process):
        if process=="BSM":
            return "scale"
        elif process=="unused":
            return "undefined"
        return 1
model = fM0()
'''
CARD = b'''imax 2
bin SR CR
observation 10 20
bin SR SR CR CR
process BSM background BSM background
process 0 1 0 1
rate 2.5 10 0.25 20
shared lnN 1.1 1.2 1.1 1.2
'''


def test_exact_quintic_signed_domain_and_literal_tokens():
    model = eft.parse_source(SOURCE)
    fn = model["functions"]["scale"]
    assert fn["degree"] == 5
    assert "0.01234567890123456789" in fn["decimal_literals"]
    assert Fraction(fn["coefficients"][1]) == Fraction("0.01234567890123456789")
    assert Fraction(fn["coefficients"][5]) == Fraction("5e-12")
    assert model["domain"]["literal"] == "fm0[0.0,-15,15]"
    assert eft.evaluate(model, "0")["scale"] == Fraction("0.999999999")
    witness = eft.algebra_witness(model)
    assert [p["point"] for p in witness["points"]] == ["-15/1", "-15/2", "0/1", "15/2", "15/1"]
    for point in ["-15", "-7.5", "0", "7.5", "15", "1/3"]:
        assert eft.evaluate(model, point) == eft.evaluate(model, point, direct=True)
    # No coefficient-dependent denominator or forced zero-point normalization.
    assert eft.evaluate(model, "1")["scale"] != Fraction(1) + Fraction("0.01234567890123456789") + Fraction("2e-3")


def test_used_card_mapping_default_background_and_unused_undefined():
    bound = eft.bind_card(eft.parse_source(SOURCE), eft.parse_datacard(CARD))
    assert [c["scale"] for c in bound["columns"]] == ["scale", 1, "scale", 1]
    assert bound["channels"] == ["SR", "CR"]
    assert bound["unused_undefined_mappings"] == [{"process": "unused", "scale": "undefined", "source_line": 12}]
    with pytest.raises(ValueError, match="undefined"):
        eft.bind_card(eft.parse_source(SOURCE), eft.parse_datacard(CARD.replace(b"BSM", b"unused")))
    with pytest.raises(ValueError, match="lacks an explicit"):
        eft.bind_card(eft.parse_source(SOURCE), eft.parse_datacard(CARD.replace(b"BSM", b"unmapped")))


@pytest.mark.parametrize("change", [
    lambda s: s + "open('/tmp/side_effect', 'w')\n",
    lambda s: s.replace("import re", "import os"),
    lambda s: s.replace("pois = 'fm0'", "pois = make_poi()"),
    lambda s: s.replace("process==\"BSM\"", "process.startswith(\"BSM\")"),
    lambda s: s.replace("+5e-12*@0*@0*@0*@0*@0", "+sin(@0)"),
    lambda s: s.replace("+5e-12*@0*@0*@0*@0*@0", "+@1"),
    lambda s: s.replace("+5e-12*@0*@0*@0*@0*@0", "+5e-12*@0*@0*@0*@0*@0*@0"),
    lambda s: s.replace("return 1", "return 0"),
    lambda s: s.replace("2e-3", "1e99999999"),
])
def test_unsupported_source_refuses_without_execution(change):
    with pytest.raises(ValueError):
        eft.parse_source(change(SOURCE))


@pytest.mark.parametrize("point", ["-15.0000000001", "15.0000000001", "nan", "inf", 0.1, True])
def test_signed_domain_and_exact_number_refusals(point):
    with pytest.raises(ValueError):
        eft.evaluate(eft.parse_source(SOURCE), point)


def test_complete_card_census_rejects_malformed_or_duplicate_columns():
    for card in [CARD.replace(b"rate 2.5 10 0.25 20", b"rate 2.5 10 0.25"),
                 CARD.replace(b"bin SR SR CR CR", b"bin SR SR SR SR"),
                 CARD + b"process 0 1 0 1\n", CARD.replace(b"rate 2.5", b"rate -2.5")]:
        with pytest.raises(ValueError):
            eft.parse_datacard(card)


def test_file_bridge_input_custody_and_delivery(tmp_path):
    source, card = tmp_path / "model.py", tmp_path / "card.txt"
    source.write_text(SOURCE)
    card.write_bytes(CARD)
    def pin(path):
        return {"path": path.name, "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}
    doc = {"schema_version": 1, "model": pin(source), "cards": [pin(card)],
           "coefficient_unit": "TeV^-4", "one_coefficient_basis": "Synthetic one-at-a-time control; all other coefficients zero.",
           "evaluation_points": ["-15", "0", "15"]}
    path = tmp_path / "input.json"
    path.write_text(json.dumps(doc))
    task = {"input": path.name}
    assert eft.inputs(task, tmp_path) == [path, source, card]
    result = eft.run(task, tmp_path, tmp_path / "out")
    assert result["status"] == "passed" and result["physics_validated"] is False
    assert result["evaluations"][1]["scales"]["scale"] == eft._ratio(Fraction("0.999999999"))
    source.write_text(SOURCE + "\n")
    with pytest.raises(ValueError, match="bytes changed"):
        eft.inputs(task, tmp_path)


def test_generated_native_bridge_contains_verbatim_factories():
    model = eft.parse_source(SOURCE)
    bridge = eft.native_bridge_source(model)
    # Inspect generated Python without importing native libraries.
    import ast
    tree = ast.parse(bridge)
    literals = [n.value for n in ast.walk(tree) if isinstance(n, ast.Constant) and isinstance(n.value, str)]
    assert model["domain"]["literal"] in literals
    assert model["functions"]["scale"]["factory"] in literals
    assert "undefined" in literals
