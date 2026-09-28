"""Independent LHE census oracle: definitions, the public Drell-Yan files and the truncated fixture.

Inputs: the two complete public Drell-Yan LHE files of the 2026-09-09 scoped-workflow controls
(RAVEL-generated development samples, referenced by path and sha256 in
fixtures/lhe/fixtures.json), the content-truncated fixture derived from one of them
(fixtures/lhe/, built by build_fixture.py), and SYNTHETIC in-test LHE documents (software-test
inputs, not generated events). Every expected number was recomputed from the files on
2026-09-26; none is an agent result or empirical evidence.
"""
import ast
import gzip
import importlib.util
import io
import json
import math
import re
import shutil
import subprocess
import sys
import xml.etree.ElementTree as ET
import zlib
from decimal import Decimal
from fractions import Fraction
from pathlib import Path

import pytest

from governance.canonical import ContractError, canonical_bytes, sha256_bytes
from governance.oracle import lhe_census

ROOT = Path(__file__).resolve().parents[2]
FIXTURES = ROOT / "tests" / "governance" / "fixtures" / "lhe"
PINNED = json.loads((FIXTURES / "fixtures.json").read_text())
TRUNCATED = "dy-1730-content-truncated.lhe.gz"
# the stored fixture bytes live with the harness that reads them (tasks/builder.SAMPLES; decision E-152)
STORED = ROOT / "benchmarks" / "governance" / "tasks" / "data"
CENSUS_SOURCE = ROOT / "benchmarks" / "governance" / "oracle" / "lhe_census.py"
# The design's selection (revised design section 2 P4): status-1 e+ e- pair mass in the open window (81, 101) GeV.
SELECTION = {"observable": "pair_invariant_mass", "unit": "GeV", "pdg_ids": [-11, 11], "status": 1,
             "multiplicity": "exactly_one_each", "window": [81, 101], "edges": "exclusive"}


def referenced(label):
    entry = PINNED["referenced"][label]
    return entry, (ROOT / entry["path"]).read_bytes()


def truncated_bytes():
    return (STORED / TRUNCATED).read_bytes()


@pytest.fixture(scope="module")
def dy1729():
    entry, data = referenced("dy-1729")
    return lhe_census.census(data, selection=SELECTION, expected_sha256=entry["sha256"])


@pytest.fixture(scope="module")
def dy1730():
    entry, data = referenced("dy-1730")
    return lhe_census.census(data, selection=SELECTION, expected_sha256=entry["sha256"])


# --------------------------------------------------------------------------- pinned inputs

def test_referenced_public_files_match_their_pins():
    scoped = ROOT / "evidence/audits/2026-09-09-scoped-workflows"
    projection = json.loads((scoped / "event-projection.json").read_text())
    for label, control in (("dy-1729", "drell-yan"), ("dy-1730", "drell-yan-replica")):
        entry, data = referenced(label)
        assert sha256_bytes(data) == entry["sha256"] == projection[control]["public_file_sha256"]
        assert len(data) == entry["bytes"] < 1_000_000
        # The recorded event-block hash (verify.py's definition) covers the event bytes only: they are
        # unchanged. It does not cover the init block, which carries XSECUP; sigma is corroborated
        # separately by the run-time result.json and by the uniform weights (test_dy_17xx_census).
        content = gzip.decompress(data)
        blocks = re.findall(rb"<event(?:\s[^>]*)?>.*?</event>", content, re.S)
        assert sha256_bytes(b"".join(blocks)) == projection[control]["event_blocks_sha256"]
        census = lhe_census.census(data)
        result = json.loads((scoped / control / "result.json").read_text())
        assert census["cross_section_pb"] == result["cross_section_pb"]


def test_stored_fixture_matches_its_pin():
    entry = PINNED["stored"][TRUNCATED]
    data = truncated_bytes()
    assert sha256_bytes(data) == entry["sha256"] and len(data) == entry["bytes"] == 10462
    assert entry["sha256"].startswith("c45eea92cf78")          # the design's recorded prefix
    assert sorted(path.name for path in STORED.iterdir() if path.suffix == ".gz") == [TRUNCATED]
    assert not [path.name for path in FIXTURES.iterdir() if path.suffix == ".gz"]    # no test-tree copy


def load_builder():
    spec = importlib.util.spec_from_file_location("lhe_fixture_builder", FIXTURES / "build_fixture.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_builder_reproduces_the_fixture_content():
    builder = load_builder()
    full = builder.source_content()
    content = builder.truncated_content(full)
    entry = PINNED["stored"][TRUNCATED]
    assert builder.cut_offset(full) == entry["cut_offset"] == 54179
    assert gzip.decompress(truncated_bytes()) == content == full[:54179]
    assert sha256_bytes(content) == entry["content_sha256"]
    result = builder.check()
    assert result["problems"] == []
    assert entry["built_with_zlib"] in entry["reproduced_with_zlib"]
    if zlib.ZLIB_RUNTIME_VERSION in entry["reproduced_with_zlib"]:
        assert result["rebuilt_bytes_identical"]      # deflate bytes are zlib-build dependent
        # the builder's record() is fixtures.json, apart from the zlib fields
        rebuilt = builder.record(builder.gzip_member(content), content, builder.cut_offset(full))

        def strip(record):
            entry = {k: v for k, v in record["stored"][TRUNCATED].items()
                     if k not in ("built_with_zlib", "reproduced_with_zlib")}
            return {**record, "stored": {TRUNCATED: entry}}

        assert strip(rebuilt) == strip(PINNED)


def test_builder_write_leaves_a_matching_fixture_record_untouched(tmp_path, monkeypatch):
    # --write on a checkout whose stored fixture already matches must not rewrite fixtures.json (and so
    # must not replace built_with_zlib with the running zlib).
    builder = load_builder()
    (tmp_path / TRUNCATED).write_bytes(truncated_bytes())
    (tmp_path / "fixtures.json").write_bytes((FIXTURES / "fixtures.json").read_bytes())
    monkeypatch.setattr(builder, "HERE", tmp_path)
    monkeypatch.setattr(builder, "STORED", tmp_path)
    before = (tmp_path / "fixtures.json").read_bytes()
    if builder.gzip_member(builder.truncated_content(builder.source_content())) != truncated_bytes():
        pytest.skip(f"zlib {zlib.ZLIB_RUNTIME_VERSION} does not reproduce the pinned deflate bytes")
    assert builder.main(["--write"]) == 0
    assert (tmp_path / "fixtures.json").read_bytes() == before


# --------------------------------------------------------------------------- complete public files

def test_dy_1729_census(dy1729):
    c = dy1729
    assert c["gzip_complete"] and c["gzip_members"] == 1 and c["stream_error"] is None
    assert c["document_complete"] and not c["open_event_at_end"]
    assert c["complete_events"] == c["header_nevents"] == c["run_card_nevents"] == 100
    assert c["sha256_matches_record"] is True
    assert c["physics_status"] == "computed" and c["physics_withheld_reasons"] == []
    assert c["header"]["idwtup"] == -4 and c["header"]["beam_ids"] == [2212, 2212]
    assert c["event_norm"] == "average" and c["run_card"]["iseed"] == "1729"
    exact = c["exact"]
    assert exact["cross_section_pb"] == "760.535" and c["cross_section_pb"] == 760.535
    assert exact["integration_error_pb"] == "6.492428"
    assert exact["mean_weight"] == "760.535"                  # every weight is +7.6053500e+02
    assert exact["sum_weights"] == "76053.5"
    assert Fraction(exact["sum_weights_sq"]) == 100 * Fraction("760.535") ** 2
    assert c["selected_events"] == 87 and exact["selected_fraction"] == "0.87"
    assert Fraction(exact["selected_sum_weights"]) == 87 * Fraction("760.535")
    assert c["momentum_conserved"] and c["max_conservation_ratio"] <= 1
    assert round(c["min_edge_distance_gev"], 3) == 0.809     # nearest pair mass to 81 or 101 GeV


def test_dy_1729_yield_identity_is_exact(dy1729):
    luminosity = Fraction("0.05")                              # synthetic development luminosity
    expected = Fraction("33083.2725")
    assert lhe_census.predicted_yield(dy1729, "0.05") == expected
    assert lhe_census.predicted_yield(dy1729, 0.05) == expected      # JSON float via its repr
    assert lhe_census.exact_decimal(expected) == "33083.2725"
    # the same identity written with the average-normalized weights: L * 10^3 * sum_sel(w) / N
    exact = dy1729["exact"]
    assert luminosity * lhe_census.FB_PER_PB * Fraction(exact["selected_sum_weights"]) / 100 == expected
    # the design's fault values (section 2 P4) follow exactly from the same census quantities
    assert expected / 1000 == Fraction("33.0832725")                                     # pb_as_fb
    assert luminosity * 1000 * Fraction(exact["selected_sum_weights"]) == Fraction("3308327.25")
    assert luminosity * Fraction(exact["selected_sum_weights"]) == Fraction("3308.32725")  # both errors
    # relative effects against the 0.01 yield tolerance: the nearest fault is "both errors" (Y x 10^-1,
    # 90 %, 90x), then pb_as_fb (Y x 10^-3, 99.9 %) and weight_sum_misread (Y x 10^2, 9900 %)
    effects = {name: abs(value - expected) / expected for name, value in (
        ("both_errors", Fraction("3308.32725")), ("pb_as_fb", Fraction("33.0832725")),
        ("weight_sum_misread", Fraction("3308327.25")))}
    assert effects == {"both_errors": Fraction(9, 10), "pb_as_fb": Fraction(999, 1000),
                       "weight_sum_misread": Fraction(99)}
    assert min(effects.values()) / Fraction("0.01") == 90 >= 3             # EFFECT_FACTOR floor
    with pytest.raises(ContractError):
        lhe_census.predicted_yield(dy1729, "0")


def test_dy_1730_census(dy1730):
    c = dy1730
    assert c["complete_events"] == c["header_nevents"] == 100 and c["physics_status"] == "computed"
    assert c["run_card"]["iseed"] == "1730" and c["sha256_matches_record"] is True
    assert c["exact"]["cross_section_pb"] == "761.52" and c["exact"]["integration_error_pb"] == "6.525022"
    assert c["exact"]["mean_weight"] == "761.52" and c["exact"]["sum_weights"] == "76152"
    assert c["selected_events"] == 89 and c["momentum_conserved"]
    assert round(c["min_edge_distance_gev"], 4) == 0.0357


def half_unit(token):
    return Fraction(1, 2) * Fraction(10) ** Decimal(token).as_tuple().exponent


@pytest.mark.parametrize("label, floor", [("dy-1729", 4.0e7), ("dy-1730", 1.5e7)])
def test_selection_edges_are_robust_to_the_printed_precision(label, floor):
    # Test-side check (no oracle code): for every event, the distance of the e+ e- pair mass from the
    # nearer window edge over the largest mass change the printed half-units of the pair's momentum
    # components allow (first order in m^2 plus the quadratic term). The selection cannot depend on the
    # unprinted generator digits. Measured minimum over the 100 events: DY 1729 4.1e7 (event 68, a boosted
    # pair 4.1 GeV above 101 GeV); DY 1730 1.5e7 (event 29, 0.30 GeV above 101 GeV). The nearest-edge
    # events give 3.9e8 and 1.8e7 (the design's "about 10^7"): boosted pairs have larger rounding bounds.
    # The margin against oracle-kernel float disagreement over the same printed decimals (about 1e11, in
    # test_oracle_crosscheck) is a different figure.
    _, data = referenced(label)
    ratios = []
    for block in re.findall(r"<event>\n(.*?)</event>", gzip.decompress(data).decode("ascii"), re.S):
        rows = [line.split() for line in block.splitlines() if line.strip() and not line.lstrip().startswith(("<", "#"))]
        pair = [row for row in rows[1:] if row[1] == "1" and row[0] in ("11", "-11")]
        assert sorted(int(row[0]) for row in pair) == [-11, 11]
        p = [sum(Fraction(row[6 + c]) for row in pair) for c in range(4)]
        h = [sum(half_unit(row[6 + c]) for row in pair) for c in range(4)]
        m2 = p[3] ** 2 - p[0] ** 2 - p[1] ** 2 - p[2] ** 2
        dm2 = sum(2 * abs(p[c]) * h[c] + h[c] ** 2 for c in range(4))
        mass = math.sqrt(m2)
        ratios.append(min(abs(mass - 81), abs(mass - 101)) / (float(dm2) / (2 * mass)))
    assert len(ratios) == 100 and min(ratios) > floor


def test_census_without_selection_has_null_selection_fields():
    _, data = referenced("dy-1729")
    c = lhe_census.census(data)
    assert c["physics_status"] == "computed" and c["selection"] is None
    assert c["selected_events"] is None and c["exact"]["selected_fraction"] is None
    assert c["sha256_matches_record"] is None
    with pytest.raises(ContractError, match="selection"):
        lhe_census.predicted_yield(c, "0.05")


def test_census_record_is_canonical_and_deterministic(dy1729):
    _, data = referenced("dy-1729")
    again = lhe_census.census(data, selection=SELECTION, expected_sha256=PINNED["referenced"]["dy-1729"]["sha256"])
    assert canonical_bytes(again) == canonical_bytes(dy1729)
    assert set(lhe_census.PHYSICS_FIELDS) <= set(dy1729)


# --------------------------------------------------------------------------- content-truncated fixture

def test_truncated_fixture_census():
    record_sha = PINNED["referenced"]["dy-1730"]["sha256"]
    c = lhe_census.census(truncated_bytes(), selection=SELECTION, expected_sha256=record_sha)
    assert c["gzip_complete"] and c["stream_error"] is None       # a valid gzip member
    assert c["complete_events"] == 41 and c["open_event_at_end"]
    assert not c["document_complete"] and c["header_nevents"] == 100
    assert c["sha256_matches_record"] is False
    assert c["decompressed_bytes"] == 54179
    assert c["physics_status"] == "withheld"
    assert c["physics_withheld_reasons"] == ["document_incomplete", "event_count_mismatch"]
    # no prefix physics (provisional decision D-CP)
    assert all(c[field] is None for field in lhe_census.PHYSICS_FIELDS)
    assert all(value is None for value in c["exact"].values())


def test_truncated_fixture_prefix_diagnostics_give_the_fault_values():
    prefix = lhe_census.prefix_selection(truncated_bytes(), SELECTION)
    assert prefix["role"] == "fault_value_diagnostic"
    assert prefix["complete_events"] == 41 and prefix["selected_events"] == 37   # truncated_selection
    assert round(Fraction(37, 41) * 100) == 90                                     # extrapolated_selection
    assert float(Fraction(37, 41) * 100) == pytest.approx(90.2439, abs=1e-4)       # unrounded: 3700/41
    assert prefix["opened_event_blocks"] == 42                                     # open-tag count


def test_truncated_fixture_under_other_counting_rules():
    # Every byte-level decompressor gives the same content (next test); it has 41 closed event blocks.
    # Other counting rules on that content: opening tags give 42 (the cut 42nd block is open), a
    # whole-document XML parse raises, and an incremental XML parse yields 41 events and then raises.
    content = gzip.decompress(truncated_bytes())
    assert content.count(b"<event>") == 42 == lhe_census.scan_content(content)["opened_event_blocks"]
    tool = shutil.which("grep")
    if tool:
        grep = subprocess.run([tool, "-c", "<event>"], input=content, capture_output=True, check=False)
        assert grep.stdout.strip() == b"42"
    with pytest.raises(ET.ParseError, match="no element found"):
        ET.fromstring(content)
    closed = 0
    with pytest.raises(ET.ParseError, match="no element found"):
        for _, element in ET.iterparse(io.BytesIO(content), events=("end",)):
            closed += element.tag == "event"
    assert closed == 41
    _, complete = referenced("dy-1730")
    scan = lhe_census.scan_content(gzip.decompress(complete))
    assert scan["opened_event_blocks"] == scan["complete_events"] == 100


def complete_events(content):
    return lhe_census.scan_content(content)["complete_events"]


def test_truncated_fixture_count_is_reader_independent():
    data = truncated_bytes()
    readers = {}
    stream = zlib.decompressobj(16 + zlib.MAX_WBITS)
    readers["zlib streaming (1 KiB chunks)"] = b"".join(stream.decompress(data[i:i + 1024])
                                                       for i in range(0, len(data), 1024)) + stream.flush()
    assert stream.eof and not stream.unused_data
    readers["gzip.decompress"] = gzip.decompress(data)
    with gzip.GzipFile(fileobj=io.BytesIO(data)) as handle:
        readers["gzip line iteration"] = b"".join(line for line in handle)
        assert sum(line.strip() == b"</event>" for line in io.BytesIO(readers["gzip line iteration"])) == 41
    tool = shutil.which("gzip")
    if tool:
        result = subprocess.run([tool, "-dc"], input=data, capture_output=True, check=False)
        assert result.returncode == 0
        readers["gzip -dc"] = result.stdout
    content = lhe_census.decompress(data)["content"]
    for name, out in readers.items():
        assert out == content, name
        assert complete_events(out) == 41, name


def test_gzip_level_cut_is_reader_dependent_so_never_scored():
    # Documentation test (revised design section 2 P5 and 8): cutting the compressed file of a
    # complete sample leaves an incomplete gzip stream whose complete-event count depends on how
    # much a reader salvages. The census reports it as truncated and withholds physics.
    _, data = referenced("dy-1730")
    cut = data[:10528]                                            # 60 % of the compressed bytes
    counts = {"maximal zlib prefix": complete_events(lhe_census.decompress(cut)["content"])}
    try:
        counts["gzip.decompress"] = complete_events(gzip.decompress(cut))
    except EOFError:
        counts["gzip.decompress"] = 0                             # nothing is returned
    for size in (4096, 65536):
        out, handle = b"", gzip.GzipFile(fileobj=io.BytesIO(cut))
        try:
            while chunk := handle.read(size):
                out += chunk
        except EOFError:
            pass
        counts[f"GzipFile.read({size})"] = complete_events(out)
    tool = shutil.which("gzip")
    if tool:
        counts["gzip -dc"] = complete_events(subprocess.run([tool, "-dc"], input=cut, capture_output=True).stdout)
    assert counts["maximal zlib prefix"] == 41 and counts["gzip.decompress"] == 0
    assert len(set(counts.values())) > 1, counts
    c = lhe_census.census(cut, selection=SELECTION)
    assert not c["gzip_complete"] and c["stream_error"] == "truncated_stream"
    assert c["physics_status"] == "withheld" and "gzip_incomplete" in c["physics_withheld_reasons"]


# --------------------------------------------------------------------------- synthetic documents

def number(value):
    return f"{float(value):+.10e}"


def particle(pdg, status, px, py, pz, energy, mass=0):
    return (f"{pdg:>9} {status:>2} 0 0 0 0 {number(px)} {number(py)} {number(pz)} {number(energy)} "
            f"{number(mass)} 0.0000e+00 9.0000e+00")


def pair_event(mass, weight="+1.0000000e+02", leptons=(-11, 11), shift="0"):
    """SYNTHETIC u u~ -> l l event at rest with pair mass `mass` (exact decimals).

    Leptons after the first two carry zero four-momentum, so every event conserves momentum
    unless `shift` moves the first lepton's px.
    """
    half = Fraction(str(mass)) / 2
    return [
        "<event>",
        f" {2 + len(leptons)}      1 {weight} 9.1000000e+01 7.5467710e-03 1.2977700e-01",
        particle(2, -1, 0, 0, half, half), particle(-2, -1, 0, 0, -half, half),
        particle(leptons[0], 1, half + Fraction(shift), 0, 0, half),
        particle(leptons[1], 1, -half, 0, 0, half),
        *[particle(pdg, 1, 0, 0, 0, 0) for pdg in leptons[2:]],
        "</event>",
    ]


def synthetic_lhe(events, *, event_norm="average", xsecup="1.000000e+02", xmaxup=None, nevents=None, closing=True):
    """A minimal SYNTHETIC LHE document (software-test input; no generator was run)."""
    nevents = sum(line == "<event>" for line in events) if nevents is None else nevents
    lines = ['<LesHouchesEvents version="3.0">', "<header>", "<!-- SYNTHETIC test document -->",
             "<MGRunCard>", "<![CDATA[", f"  {nevents}\t= nevents ! requested", f"  {event_norm}\t= event_norm ! norm",
             "]]>", "</MGRunCard>", "<MGGenerationInfo>", f"#  Number of Events        :       {nevents}",
             "#  Integrated weight (pb)  :       100", "</MGGenerationInfo>", "</header>", "<init>",
             "2212 2212 6.500000e+03 6.500000e+03 0 0 10042 10042 -4 1",
             f"{xsecup} 1.000000e+00 {xmaxup or xsecup} 1", "</init>", *events]
    if closing:
        lines.append("</LesHouchesEvents>")
    return ("\n".join(lines) + "\n").encode()


def gz(content):
    return gzip.compress(content, mtime=0)


def selection(low, high, **changes):
    return {**SELECTION, "window": [low, high], **changes}


def test_selection_window_edges_are_exclusive():
    content = synthetic_lhe(pair_event(81) + pair_event(91) + pair_event(101))
    assert lhe_census.census(gz(content), selection=selection(81, 101))["selected_events"] == 1
    assert lhe_census.census(gz(content), selection=selection("80.999", "101.001"))["selected_events"] == 3
    assert lhe_census.census(gz(content), selection=selection(91, 101))["selected_events"] == 0
    assert lhe_census.census(gz(content), selection=selection(81, 101))["min_edge_distance_gev"] == 0.0


def test_selection_requires_exactly_one_of_each_lepton():
    content = synthetic_lhe(pair_event(91) + pair_event(91, leptons=(-11, 11, 11)) + pair_event(91, leptons=(-13, 13)))
    c = lhe_census.census(gz(content), selection=SELECTION)
    assert c["complete_events"] == 3 and c["selected_events"] == 1 and c["exact"]["selected_fraction"] == "1/3"


def test_pair_masses_follow_the_complete_events_in_file_order():
    content = synthetic_lhe(pair_event(81) + pair_event("91.1876") + pair_event(91, leptons=(-13, 13))
                            + pair_event(101))
    assert lhe_census.pair_masses(gz(content), SELECTION) == [81.0, 91.1876, None, 101.0]
    # a cut fragment is never an event, so the list is the complete events only
    assert lhe_census.pair_masses(gz(content[:content.rindex(b"</event>")]), SELECTION) == [81.0, 91.1876, None]
    _, data = referenced("dy-1729")
    masses = lhe_census.pair_masses(data, SELECTION)
    assert len(masses) == 100 and None not in masses
    assert sum(81 < m < 101 for m in masses) == 87


def recoil_event():
    """SYNTHETIC u u~ -> e+ e- g event: the pair (mass 90 GeV) recoils against the gluon, so its
    total px is 48 GeV and its energy 102 GeV (90^2 + 48^2 = 102^2; every lepton is massless)."""
    return ["<event>", " 5      1 +1.0000000e+02 9.1000000e+01 7.5467710e-03 1.2977700e-01",
            particle(2, -1, 0, 0, 75, 75), particle(-2, -1, 0, 0, -75, 75),
            particle(-11, 1, 24, 45, 0, 51), particle(11, 1, 24, -45, 0, 51), particle(21, 1, -48, 0, 0, 48),
            "</event>"]


def test_pair_mass_uses_the_whole_pair_four_momentum():
    # At LO without recoil the pair has no transverse momentum, so the public files cannot tell a
    # transverse component missing from m^2; this event can (m = 90 GeV; without px it would be 102).
    c = lhe_census.census(gz(synthetic_lhe(recoil_event())), selection=SELECTION)
    assert c["physics_status"] == "computed" and c["momentum_conserved"] and c["selected_events"] == 1
    assert lhe_census.pair_masses(gz(synthetic_lhe(recoil_event())), SELECTION) == [90.0]
    assert c["min_edge_distance_gev"] == 9.0


def test_cross_section_is_xsecup_not_xmaxup():
    # MadGraph writes XMAXUP = XSECUP for unweighted events, so the public files cannot tell them apart.
    content = synthetic_lhe(pair_event(91) + pair_event(95), xmaxup="1.500000e+02")
    c = lhe_census.census(gz(content), selection=SELECTION)
    assert c["physics_status"] == "computed" and c["exact"]["cross_section_pb"] == "100"
    assert c["weight_normalization_consistent"]


@pytest.mark.parametrize("change", [
    {"edges": "inclusive"}, {"window": [101, 81]}, {"window": [81]}, {"window": [True, 101]},
    {"window": [-1, 101]}, {"window": ["81 GeV", 101]}, {"pdg_ids": [11, 11]}, {"pdg_ids": [-11]},
    {"status": "1"}, {"unit": "MeV"}, {"multiplicity": "at_least_one_each"}, {"observable": "pt"},
    {"extra": 1}])
def test_selection_rejects_other_definitions(change):
    with pytest.raises(ContractError):
        lhe_census.parse_selection({**SELECTION, **change})
    missing = dict(SELECTION)
    missing.pop("edges")
    with pytest.raises(ContractError):
        lhe_census.parse_selection(missing)


def test_momentum_imbalance_beyond_printed_precision_withholds_physics():
    fine = lhe_census.census(gz(synthetic_lhe(pair_event(91) + pair_event(91))), selection=SELECTION)
    assert fine["momentum_conserved"] and fine["max_conservation_ratio"] == 0
    broken = lhe_census.census(gz(synthetic_lhe(pair_event(91) + pair_event(91, shift="1e-6"))), selection=SELECTION)
    assert broken["physics_status"] == "withheld"
    assert broken["physics_withheld_reasons"] == ["momentum_not_conserved"]
    # px prints to 1e-10 (u, u~) and 1e-9 (leptons): the rounding bound is 2 * 5e-11 + 2 * 5e-10
    inside = lhe_census.census(gz(synthetic_lhe(pair_event(91, shift="1e-9"))), selection=SELECTION)
    assert inside["momentum_conserved"] and inside["max_conservation_ratio"] == float(Fraction(10, 11))
    outside = lhe_census.census(gz(synthetic_lhe(pair_event(91, shift="2e-9"))), selection=SELECTION)
    assert outside["physics_withheld_reasons"] == ["momentum_not_conserved"]


@pytest.mark.parametrize("kwargs, events, reason", [
    ({"event_norm": "unity"}, 2, "unsupported_event_norm"),
    ({"xsecup": "1.010000e+02"}, 2, "weight_normalization_inconsistent"),
    ({"nevents": 3}, 2, "event_count_mismatch"),
    ({"closing": False}, 2, "document_incomplete"),
    ({}, 0, "no_complete_events"),
])
def test_physics_withheld_reasons(kwargs, events, reason):
    content = synthetic_lhe(sum((pair_event(91) for _ in range(events)), []), **kwargs)
    c = lhe_census.census(gz(content), selection=SELECTION)
    assert c["physics_status"] == "withheld" and reason in c["physics_withheld_reasons"]
    assert all(c[field] is None for field in lhe_census.PHYSICS_FIELDS)


def test_event_norm_sum_checks_the_weight_sum():
    content = synthetic_lhe(pair_event(91, weight="+5.0000000e+01") + pair_event(95, weight="+5.0000000e+01"),
                            event_norm="sum")
    c = lhe_census.census(gz(content), selection=SELECTION)
    assert c["physics_status"] == "computed" and c["exact"]["sum_weights"] == "100"
    assert lhe_census.predicted_yield(c, "2") == 2 * 100 * 1000


@pytest.mark.parametrize("fragment, events, open_event", [
    (b"<eve", 1, False), (b"<event>", 1, True), (b"</event>", 2, False), (b"</eve", 1, True),
    (b"</LesHouches", 2, False)])
def test_cut_inside_the_last_line_is_a_fragment_not_content(fragment, events, open_event):
    body = synthetic_lhe(pair_event(91) + pair_event(92), closing=False)
    first = body.index(b"<event>", body.index(b"</event>"))           # start of the second event
    if fragment == b"</event>":
        content = body.rstrip(b"\n")                                  # "</event>" unterminated
    elif fragment == b"</eve":
        content = body[:body.rindex(b"</event>")] + fragment
    elif fragment == b"</LesHouches":
        content = body + fragment
    else:
        content = body[:first] + fragment
    scan = lhe_census.scan_content(content)
    assert scan["complete_events"] == events and scan["open_event_at_end"] == open_event
    assert not scan["document_complete"] and scan["partial_last_line"]


def second_init(text):
    init = text.split("<init>\n")[1].split("</init>")[0]
    return text.replace("</init>\n", "</init>\n<init>\n" + init + "</init>\n", 1)


@pytest.mark.parametrize("mutate, match", [
    (lambda t: t.replace(" 4      1 +1.0", " 5      1 +1.0", 1), "fewer particle lines than NUP"),
    (lambda t: t.replace(" 4      1 +1.0", " 3      1 +1.0", 1), "unexpected line after the particle lines"),
    (lambda t: t.replace("+4.5500000000e+01", "4.55e+01x", 1), "expected a decimal number"),
    (lambda t: t.replace("+4.5500000000e+01", "4.55D+01", 1), "expected a decimal number"),   # Fortran exponent
    (lambda t: t + "trailing text\n", "content after </LesHouchesEvents>"),
    (second_init, "second <init> block"),
    (lambda t: t.replace("<init>", "<event>\n</event>\n<init>", 1), "event before the init block"),
    (lambda t: t.replace("2212 2212 6.5", "2212 6.5", 1), "init beam line"),
    (lambda t: t.replace("  2\t= nevents", "  2\t= nevents\n  3\t= nevents", 1), "duplicate key"),
    (lambda t: t.replace("</header>\n", "</header>\nstray\n", 1), "expected <header> or <init>|unexpected content"),
])
def test_malformed_content_raises(mutate, match):
    text = synthetic_lhe(pair_event(91) + pair_event(91)).decode()
    mutated = mutate(text)
    assert mutated != text
    with pytest.raises(ContractError, match=match):
        lhe_census.census(gz(mutated.encode()), selection=SELECTION)


def test_stream_integrity_facts():
    content = synthetic_lhe(pair_event(91) + pair_event(92))
    whole = gz(content)
    reference = lhe_census.census(whole, selection=SELECTION)
    assert reference["physics_status"] == "computed" and reference["gzip_members"] == 1
    split = content.index(b"</event>") + 3
    two = lhe_census.census(gz(content[:split]) + gz(content[split:]), selection=SELECTION)
    assert two["gzip_members"] == 2 and two["gzip_complete"]
    assert {k: v for k, v in two.items() if k not in ("file_sha256", "file_bytes", "gzip_members")} == \
        {k: v for k, v in reference.items() if k not in ("file_sha256", "file_bytes", "gzip_members")}
    trailing = lhe_census.census(whole + b"junk", selection=SELECTION)
    assert trailing["stream_error"] == "trailing_data" and trailing["complete_events"] == 2
    assert trailing["physics_withheld_reasons"] == ["gzip_incomplete"]
    bad_crc = whole[:-8] + bytes([whole[-8] ^ 0xFF]) + whole[-7:]
    corrupt = lhe_census.census(bad_crc, selection=SELECTION)
    assert corrupt["stream_error"] == "corrupt_stream" and corrupt["complete_events"] == 2
    assert corrupt["physics_status"] == "withheld"
    plain = lhe_census.census(content, selection=SELECTION)
    assert plain["stream_error"] == "not_gzip" and plain["complete_events"] == 0
    for data in (whole[:5], whole[:len(whole) // 2]):
        cut = lhe_census.census(data, selection=SELECTION)
        assert cut["stream_error"] == "truncated_stream" and not cut["gzip_complete"]


def test_decompression_is_bounded(monkeypatch):
    monkeypatch.setattr(lhe_census, "MAX_CONTENT_BYTES", 1000)
    _, data = referenced("dy-1729")
    with pytest.raises(ContractError, match="exceeds"):
        lhe_census.census(data)


def test_census_rejects_invalid_arguments():
    _, data = referenced("dy-1729")
    for call in (lambda: lhe_census.census("text"), lambda: lhe_census.census(data, expected_sha256="ABC"),
                 lambda: lhe_census.census(data, selection=[]), lambda: lhe_census.predicted_yield({}, "1"),
                 lambda: lhe_census.predicted_yield(lhe_census.census(data, selection=SELECTION), float("nan"))):
        with pytest.raises(ContractError):
            call()


@pytest.mark.parametrize("value, text", [(Fraction(1, 3), "1/3"), (Fraction(-5, 2), "-2.5"), (Fraction(7), "7"),
                                         (Fraction("0.0125"), "0.0125"), (Fraction(0), "0")])
def test_exact_decimal(value, text):
    assert lhe_census.exact_decimal(value) == text


# --------------------------------------------------------------------------- independence

def test_census_module_imports_only_stdlib_and_canonical():
    tree = ast.parse(CENSUS_SOURCE.read_text())
    modules = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules |= {alias.name.split(".")[0] for alias in node.names}
        elif isinstance(node, ast.ImportFrom):
            modules.add((node.module or "").split(".")[0])
    assert modules <= {"__future__", "hashlib", "math", "re", "zlib", "fractions", "pathlib", "governance"}
    script = ("import sys; sys.path[:0] = [sys.argv[1]]; import governance.oracle.lhe_census as c; "
              "c.census_file(sys.argv[2]); print(sorted(m for m in ('pyhf', 'numpy', 'scipy', 'ravel', "
              "'xml', 'gzip') if m in sys.modules))")
    out = subprocess.run([sys.executable, "-c", script, str(ROOT / "benchmarks"),
                          str(ROOT / PINNED["referenced"]["dy-1729"]["path"])],
                         capture_output=True, text=True, check=True)
    assert out.stdout.strip() == "[]"
