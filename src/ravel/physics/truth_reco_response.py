"""Event-bound, bare-lepton Delphes response diagnostic, not ATLAS truth acceptance.

Only stable electrons/muons connected through same-signed-PDG copies to a
same-flavour charged slepton enter the direct-lepton denominator. Reconstructed
objects match by Particle.fUniqueID/TRef, never by proximity. No GenJet, trigger,
photon dressing, or unavailable experimental predicate is inferred here.

ROOT reading requires uproot and awkward; the calculation and tests use stdlib.
Run ``python -m ravel.physics.truth_reco_response --help`` for the standalone CLI.
"""
from __future__ import annotations

import argparse
from bisect import bisect_right
from collections import Counter, defaultdict
import gzip
import hashlib
from importlib import metadata
import json
import math
from pathlib import Path
import platform
import sys
import tempfile

SCHEMA_VERSION = 1
# Fixed before the fresh 20k-event anchor. None denotes an open upper endpoint.
PT_EDGES = (0, 2, 3, 4, 5, 7, 10, 15, 20, 30, 50, 100, None)
ABS_ETA_EDGES = (0, .8, 1.37, 1.52, 2., 2.47, 2.5, None)
FOUR_STATES = frozenset((1000011, 2000011, 1000013, 2000013))
SLEPTONS = FOUR_STATES | {1000015, 2000015}
FLAVOURS = {11: "electron", 13: "muon"}
ORIGINS = ("direct_slepton", "tau_ancestor", "other_slepton_descendant", "other_origin")


def integer(value, label):
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{label} must be an integer")
    return value


def finite(value, label):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError(f"{label} must be finite")
    return float(value)


def fingerprint(path):
    path = Path(path).resolve(strict=True)
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return {"path": str(path), "sha256": digest.hexdigest()}


def verify_fingerprint(record, expected_path=None):
    if expected_path is not None and Path(record["path"]).resolve() != Path(expected_path).resolve():
        raise ValueError("artifact path disagrees with the declared input")
    if fingerprint(record["path"]) != record:
        raise ValueError(f"source hash changed: {record['path']}")


def definitions():
    return {
        "direct_lepton": "status=1, abs(PID)=11 or 13; only same signed lepton PID copies between the stable lepton and one same-flavour, same-sign charged slepton parent",
        "ancestry": "stored Delphes M1/M2 indices; mother endpoints can omit additional incoming particles at vertices with more than two parents",
        "matching": "stored reco Particle TRef UID -> unique same-event Particle.fUniqueID; stable, same flavour required; no geometric fallback; uproot path requires one stored TProcessID namespace",
        "denominator": "all direct stable bare leptons in every input event, including out-of-acceptance leptons and unmatched leptons",
        "four_state_policy": "when requested: the campaign assumes two same-species/opposite-sign eL/eR/muL/muR root sleptons, two stable binos and two direct stable leptons; inconsistent rows are retained and flagged, not discarded; this is not a universal slepton topology requirement",
        "weight": "raw nominal Delphes Event.Weight; no luminosity, cross-section rebase, or K factor applied",
        "dressing": {"status": "not_computed", "primary": "stable bare post-shower leptons"},
        "bins": {"truth_pt_gev": list(PT_EDGES), "truth_abs_eta": list(ABS_ETA_EDGES), "interval": "lower inclusive, upper exclusive; final null is infinity"},
        "uncertainty": "shared-event delta-method ratio moments; leptons in an event are not independent; boundary counts remain precision unresolved",
        "native_join": "event-level predicates only; the native trace has no per-lepton Particle UID, so individual native lepton survival is not asserted",
        "native_source_scope": "selection and diagnostic source bytes verified; RJR binary hash retained as producer metadata, not independently checked by this diagnostic",
        "scope": "source-bound response diagnostic; not an ATLAS acceptance, reconstruction efficiency calibration, trigger emulation, statistical coverage test, or physics certification",
        "omitted": ["photon dressing", "truth jets", "GenJet acceptance", "experimental trigger", "author16", "experimental truth matching"],
    }


def reader_runtime():
    versions = {"python": platform.python_version()}
    for name in ("uproot", "awkward"):
        try:
            versions[name] = metadata.version(name)
        except metadata.PackageNotFoundError:
            versions[name] = None
    return versions


def mothers_and_order(particles):
    """Validate the entire stored mother graph, including particles not selected."""
    size = len(particles)
    mothers = []
    seen = set()
    for index, p in enumerate(particles):
        uid = integer(p["uid"], "particle UID")
        if uid <= 0 or uid in seen:
            raise ValueError("particle UIDs must be positive and unique within an event")
        seen.add(uid)
        integer(p["pid"], "PID")
        integer(p["status"], "status")
        parent = []
        for field in ("m1", "m2"):
            value = integer(p[field], field)
            if value < -1 or value >= size:
                raise ValueError(f"out-of-range mother at particle {index}")
            if value >= 0 and value not in parent:
                parent.append(value)
        mothers.append(parent)
    colors = [0] * size
    order = []
    for start in range(size):
        if colors[start]:
            continue
        stack = [(start, False)]
        while stack:
            current, finishing = stack.pop()
            if finishing:
                colors[current] = 2
                order.append(current)
                continue
            if colors[current] == 1:
                raise ValueError("cycle in stored particle ancestry")
            if colors[current] == 2:
                continue
            colors[current] = 1
            stack.append((current, True))
            for parent in reversed(mothers[current]):
                if colors[parent] == 1:
                    raise ValueError("cycle in stored particle ancestry")
                if colors[parent] != 2:
                    stack.append((parent, False))
    return mothers, order


def vector(p):
    result = {key: finite(p[key], key) for key in ("pt", "eta", "phi")}
    if result["pt"] < 0:
        raise ValueError("negative transverse momentum")
    if "energy" in p:
        result["energy"] = finite(p["energy"], "energy")
        if result["energy"] < 0:
            raise ValueError("negative energy")
    return result


def analyze_event(event, *, expect_four_state=True, native=None):
    """Pure event calculation. Malformed identities/ancestry fail, not disappear."""
    source_entry = integer(event["source_entry"], "source entry")
    if source_entry < 0:
        raise ValueError("negative source entry")
    event_id = integer(event["event_number"], "Delphes event number")
    weight = finite(event["weight"], "nominal weight")
    if type(expect_four_state) is not bool:
        raise ValueError("four-state population policy must be boolean")
    particles = event["particles"]
    mothers, order = mothers_and_order(particles)
    by_uid = {p["uid"]: i for i, p in enumerate(particles)}
    # Two flags suffice for origin labels, without materializing O(N^2) ancestor sets.
    flags = [0] * len(particles)
    direct_paths = [{} for _ in particles]
    for i in order:
        p = particles[i]
        flags[i] = (1 if abs(p["pid"]) == 15 else 0) | (2 if abs(p["pid"]) in SLEPTONS else 0)
        for mother in mothers[i]:
            flags[i] |= flags[mother]
        if abs(p["pid"]) not in FLAVOURS:
            continue
        for mother in mothers[i]:
            ancestor = particles[mother]
            if abs(ancestor["pid"]) in SLEPTONS:
                direct_paths[i][mother] = [i, mother]
            elif ancestor["pid"] == p["pid"]:
                for root, chain in direct_paths[mother].items():
                    direct_paths[i][root] = [i, *chain]
    roots = [i for i, p in enumerate(particles) if abs(p["pid"]) in SLEPTONS
             and not any(particles[m]["pid"] == p["pid"] for m in mothers[i])]
    direct = {}
    for i, p in enumerate(particles):
        if p["status"] != 1 or abs(p["pid"]) not in FLAVOURS or not direct_paths[i]:
            continue
        if len(direct_paths[i]) != 1:
            raise ValueError("ambiguous direct slepton ancestry")
        parent, chain = next(iter(direct_paths[i].items()))
        parent_pid = particles[parent]["pid"]
        if abs(parent_pid) % 1000000 != abs(p["pid"]) or (parent_pid > 0) != (p["pid"] > 0):
            raise ValueError("slepton parent and direct lepton flavour/sign disagree")
        direct[i] = {"particle_index": i, "particle_uid": p["uid"], "pid": p["pid"],
                     "flavour": FLAVOURS[abs(p["pid"])], "bare": vector(p),
                     "slepton_parent_index": parent, "slepton_parent_pid": parent_pid,
                     "copy_chain_indices": chain, "matched_reco": None}
    reco_rows = []
    used = set()
    for reco in event["reco"]:
        uid = integer(reco["ref"], "reco TRef")
        if uid not in by_uid:
            raise ValueError("unresolved reco TRef")
        if uid in used:
            raise ValueError("duplicate reco TRef")
        used.add(uid)
        index = by_uid[uid]
        p = particles[index]
        if reco["flavour"] not in FLAVOURS.values() or FLAVOURS.get(abs(p["pid"])) != reco["flavour"]:
            raise ValueError("reco TRef flavour disagreement")
        if p["status"] != 1:
            raise ValueError("reco TRef does not refer to a stable particle")
        origin = ("direct_slepton" if index in direct else "tau_ancestor" if flags[index] & 1
                  else "other_slepton_descendant" if flags[index] & 2 else "other_origin")
        row = {"flavour": reco["flavour"], "reco_index": integer(reco["index"], "reco index"),
               "particle_index": index, "particle_uid": uid, "origin": origin, "vector": vector(reco)}
        reco_rows.append(row)
        if index in direct:
            direct[index]["matched_reco"] = row
    native_fields = None
    if native is not None:
        if native["event_id"] != event_id:
            raise ValueError("native event ID disagrees with Delphes Event.Number")
        native_fields = {"event_id": native["event_id"], "weight_pb": native["weight_pb"],
                         "predicates": native["predicates"], "objects": native.get("objects"),
                         "accepted_regions": native.get("accepted_regions"), "rjr_status": native.get("rjr_status")}
    violations = []
    stable_lsp = sum(p["status"] == 1 and abs(p["pid"]) == 1000022 for p in particles)
    if expect_four_state:
        if any(abs(particles[i]["pid"]) not in FOUR_STATES for i in roots):
            violations.append("produced charged slepton outside declared four states")
        if len(roots) != 2 or particles[roots[0]]["pid"] != -particles[roots[1]]["pid"]:
            violations.append("declared same-species opposite-sign root slepton pair absent")
        if stable_lsp != 2 or len(direct) != 2:
            violations.append("declared two stable binos and two direct stable leptons absent")
    return {"kind": "event", "source_entry": source_entry, "delphes_event_number": event_id,
            "native_event_id": native_fields["event_id"] if native_fields else None,
            "weight_raw": weight, "particle_entries": len(particles),
            "root_sleptons": [{"particle_index": i, "pid": particles[i]["pid"]} for i in roots],
            "stable_lsp_count": stable_lsp,
            "direct_leptons": list(direct.values()), "reco_leptons": reco_rows,
            "four_state_policy_requested": expect_four_state,
            "four_state_violations": violations, "native": native_fields}


def bin_index(value, edges):
    return bisect_right(edges[:-1], value) - 1


class RatioMoments:
    """Each add is one event; repeated leptons must be counted together."""
    def __init__(self):
        self.raw_denominator = self.raw_numerator = 0
        self.contributing_events = 0
        self.denominator = self.numerator = self.denominator2 = self.numerator2 = self.cross = 0.

    def add(self, denominator, numerator, weight):
        if not 0 <= numerator <= denominator:
            raise ValueError("invalid matched/truth counts")
        self.raw_denominator += denominator
        self.raw_numerator += numerator
        self.contributing_events += denominator > 0 and weight != 0
        d, n = weight * denominator, weight * numerator
        self.denominator += d
        self.numerator += n
        self.denominator2 += d * d
        self.numerator2 += n * n
        self.cross += d * n

    def result(self):
        result = dict(raw_truth=self.raw_denominator, raw_matched=self.raw_numerator,
                      contributing_events=self.contributing_events,
                      truth_sumw=self.denominator, matched_sumw=self.numerator,
                      event_truth_sumw2=self.denominator2, event_matched_sumw2=self.numerator2,
                      event_truth_matched_cross=self.cross, ratio=None, standard_error=None,
                      precision_status="zero_denominator_unresolved")
        if self.denominator == 0:
            return result
        ratio = self.numerator / self.denominator
        result["ratio"] = ratio
        if self.raw_numerator in (0, self.raw_denominator):
            result["precision_status"] = "boundary_count_precision_unresolved"
            return result
        if self.contributing_events < 2:
            result["precision_status"] = "insufficient_event_clusters_unresolved"
            return result
        variance = (self.numerator2 - 2 * ratio * self.cross + ratio * ratio * self.denominator2) / self.denominator**2
        if variance <= 0:
            result["precision_status"] = "zero_empirical_variance_precision_unresolved"
            return result
        result.update(standard_error=math.sqrt(max(0., variance)),
                      precision_status="event_cluster_delta_approximation")
        return result


class ResponseSummary:
    def __init__(self):
        self.events = self.particles = self.negative_weights = 0
        self.sumw = self.sumw2 = 0.
        self.ids = set()
        self.topology = Counter()
        self.parents = Counter({str(x): 0 for x in sorted(SLEPTONS)})
        self.violations = 0
        self.four_state_policy = None
        self.origins = {f: Counter({o: 0 for o in ORIGINS}) for f in FLAVOURS.values()}
        self.bins = {(f, p, e): RatioMoments() for f in FLAVOURS.values()
                     for p in range(len(PT_EDGES)-1) for e in range(len(ABS_ETA_EDGES)-1)}
        self.totals = {f: RatioMoments() for f in FLAVOURS.values()}
        self.migrations = defaultdict(lambda: [0, 0., 0.])

    def add(self, row):
        if self.four_state_policy is not None and self.four_state_policy != row["four_state_policy_requested"]:
            raise ValueError("cannot combine different declared population policies")
        self.four_state_policy = row["four_state_policy_requested"]
        if row["source_entry"] != self.events:
            raise ValueError("source entries must retain the complete ordered input population")
        if row["delphes_event_number"] in self.ids:
            raise ValueError("duplicate Delphes event number")
        self.ids.add(row["delphes_event_number"])
        self.events += 1
        weight = row["weight_raw"]
        self.sumw += weight
        self.sumw2 += weight * weight
        self.negative_weights += weight < 0
        self.particles += row["particle_entries"]
        self.violations += bool(row["four_state_violations"])
        self.topology[(len(row["root_sleptons"]), row["stable_lsp_count"], len(row["direct_leptons"]))] += 1
        self.parents.update(str(abs(p["pid"])) for p in row["root_sleptons"])
        bins, totals, migration = defaultdict(lambda: [0, 0]), defaultdict(lambda: [0, 0]), Counter()
        for p in row["direct_leptons"]:
            f, v, reco = p["flavour"], p["bare"], p["matched_reco"]
            key = (f, bin_index(v["pt"], PT_EDGES), bin_index(abs(v["eta"]), ABS_ETA_EDGES))
            bins[key][0] += 1
            bins[key][1] += reco is not None
            totals[f][0] += 1
            totals[f][1] += reco is not None
            if reco:
                for axis, edges, truth, measured in (("pt", PT_EDGES, v["pt"], reco["vector"]["pt"]),
                        ("abs_eta", ABS_ETA_EDGES, abs(v["eta"]), abs(reco["vector"]["eta"]))):
                    migration[(f, axis, bin_index(truth, edges), bin_index(measured, edges))] += 1
        for key, counts in bins.items():
            self.bins[key].add(*counts, weight)
        for f, counts in totals.items():
            self.totals[f].add(*counts, weight)
        for key, count in migration.items():
            values = self.migrations[key]
            values[0] += count
            values[1] += weight * count
            values[2] += (weight * count)**2
        for p in row["reco_leptons"]:
            self.origins[p["flavour"]][p["origin"]] += 1

    def result(self):
        return {"schema_version": SCHEMA_VERSION, "status": "diagnostic_complete",
                "four_state_population_status": ("not_requested" if not self.four_state_policy else
                    "FAIL" if self.violations else "consistent_with_declared_four_state_population"),
                "four_state_violating_events": self.violations,
                "physics_certified": False, "input_events": self.events, "particle_entries": self.particles,
                "raw_weights": {"sumw": self.sumw, "sumw2": self.sumw2, "negative_events": self.negative_weights},
                "signed_weight_caution": self.negative_weights > 0,
                "root_slepton_counts_both_charges": dict(self.parents),
                "topology": [{"root_sleptons": k[0], "stable_lsp": k[1], "direct_leptons": k[2], "events": v}
                             for k, v in sorted(self.topology.items())],
                "reco_origin_counts": {f: dict(v) for f, v in self.origins.items()},
                "total_response": {f: m.result() for f, m in self.totals.items()},
                "response_bins": [{"flavour": f, "pt_bin": p, "abs_eta_bin": e, **v.result()}
                                  for (f, p, e), v in self.bins.items()],
                "matched_migrations": [{"flavour": k[0], "axis": k[1], "truth_bin": k[2], "reco_bin": k[3],
                                         "count": v[0], "sumw": v[1], "event_sumw2": v[2]}
                                        for k, v in sorted(self.migrations.items())]}


def validate_native_join(delphes_path, native_path, trace_path, *, native_rows):
    """Bind the optional event-level native trace through its actual converter receipt."""
    from . import compressed_validation
    receipt_path = Path(str(native_path) + ".normalization.json")
    receipt = json.loads(receipt_path.read_text())
    if type(receipt.get("schema_version")) is not int or receipt["schema_version"] != 1 or receipt.get("luminosity_applied") is not False:
        raise ValueError("unsupported converter receipt schema or luminosity-applied weights")
    verify_fingerprint(receipt["sources"][0], delphes_path)
    verify_fingerprint(receipt["output"], native_path)
    dependencies = [fingerprint(native_path), fingerprint(trace_path), fingerprint(receipt_path),
                    fingerprint(compressed_validation.__file__)]
    for source in receipt["sources"]:
        verify_fingerprint(source)
        dependencies.append(source)
    if receipt.get("normalization"):
        verify_fingerprint(receipt["normalization"])
        dependencies.append(receipt["normalization"])
    # Reuse the native trace's membership and unknown-predicate validator.
    compressed_validation.summarize_trace(trace_path)
    selection_source = fingerprint(Path(__file__).with_name("native_simpleanalysis.py"))
    dependencies.append(selection_source)
    with gzip.open(trace_path, "rt") as stream:
        header = json.loads(next(stream))
        if (header.get("kind") != "header" or header.get("schema_version") != 1
                or header.get("level") != "reco" or header.get("weight_unit") != "pb"
                or header["metadata"]["input_sha256"] != receipt["output"]["sha256"]):
            raise ValueError("native trace is not bound to the converted input")
        if (header["metadata"].get("selection_source_sha256") != selection_source["sha256"]
                or header["metadata"].get("diagnostic_source_sha256") != fingerprint(compressed_validation.__file__)["sha256"]):
            raise ValueError("native trace source hashes disagree with current source files")
        rows = {}
        for line in stream:
            row = json.loads(line)
            compressed_validation._validated(row)
            key = integer(row["event_id"], "native event ID")
            if key in rows:
                raise ValueError("duplicate native trace event ID")
            rows[key] = row
    native_ids = [integer(row["event_id"], "converted event ID") for row in native_rows]
    if len(set(native_ids)) != len(native_ids) or set(native_ids) != set(rows):
        raise ValueError("native trace population differs from converted input")
    if type(header["metadata"]["input_events"]) is not int or header["metadata"]["input_events"] != len(native_rows):
        raise ValueError("native trace input count disagrees")
    for row in native_rows:
        actual = finite(row["weight_pb"], "converted nominal weight")
        traced = finite(rows[row["event_id"]]["weight_pb"], "traced nominal weight")
        if not math.isclose(actual, traced, rel_tol=1e-10, abs_tol=1e-15):
            raise ValueError("native trace weight disagrees with converted input")
    scale = finite(receipt["scale_pb_per_weight"], "conversion weight scale")
    if scale <= 0:
        raise ValueError("invalid conversion weight scale")
    weights = [row["weight_pb"] for row in native_rows]
    for name, factor in (("normalized", 1.), ("raw", 1. / scale)):
        moment = receipt[name]
        if (type(moment.get("n_events")) is not int or moment["n_events"] != len(weights)
                or type(moment.get("negative_weights")) is not int
                or moment["negative_weights"] != sum(w < 0 for w in weights)):
            raise ValueError("converter receipt population moments disagree")
        expected = {"sumw": math.fsum(w * factor for w in weights),
                    "sumw2": math.fsum((w * factor)**2 for w in weights)}
        for key, value in expected.items():
            if not math.isclose(finite(moment[key], f"receipt {name} {key}"), value, rel_tol=2e-5, abs_tol=1e-15):
                raise ValueError("converter receipt weight moments disagree")
    return rows, scale, dependencies, header


PARTICLE_FIELDS = {"pid": "PID", "status": "Status", "m1": "M1", "m2": "M2", "uid": "fUniqueID",
                   "pt": "PT", "eta": "Eta", "phi": "Phi", "energy": "E"}


def require_single_process_id(classnames):
    namespaces = [name for name, classname in classnames.items() if classname == "TProcessID"]
    if len(namespaces) != 1:
        raise ValueError("UID-only uproot matching requires exactly one stored TProcessID namespace")
    return namespaces[0]


def delphes_events(path, *, step_size=128):
    import awkward as ak
    import uproot
    branches = ["Event.Number", "Event.Weight", *["Particle." + x for x in PARTICLE_FIELDS.values()]]
    branches += [f"{f}.{x}" for f in ("Electron", "Muon") for x in ("Particle", "PT", "Eta", "Phi")]
    with uproot.open(path) as stream:
        require_single_process_id(stream.classnames(recursive=False))
        tree = stream["Delphes"]
        entry = 0
        for chunk in tree.iterate(branches, step_size=step_size, library="ak"):
            for index in range(len(chunk)):
                values = {name: ak.to_list(chunk[name][index]) for name in branches}
                if len(values["Event.Number"]) != 1 or len(values["Event.Weight"]) != 1:
                    raise ValueError("exactly one Delphes event record required")
                arrays = {key: values["Particle." + field] for key, field in PARTICLE_FIELDS.items()}
                if len({len(x) for x in arrays.values()}) != 1:
                    raise ValueError("particle branch length mismatch")
                particles = [dict(zip(arrays, row)) for row in zip(*arrays.values())]
                reco = []
                for branch, flavour in (("Electron", "electron"), ("Muon", "muon")):
                    fields = [values[f"{branch}.{x}"] for x in ("Particle", "PT", "Eta", "Phi")]
                    if len({len(x) for x in fields}) != 1:
                        raise ValueError("reco branch length mismatch")
                    for reco_index, (ref, pt, eta, phi) in enumerate(zip(*fields)):
                        if not isinstance(ref, dict) or set(ref) != {"ref"}:
                            raise ValueError("unsupported TRef representation")
                        reco.append(dict(index=reco_index, flavour=flavour, ref=ref["ref"], pt=pt, eta=eta, phi=phi))
                yield dict(source_entry=entry, event_number=values["Event.Number"][0],
                           weight=values["Event.Weight"][0], particles=particles, reco=reco)
                entry += 1
        if entry != tree.num_entries:
            raise ValueError("incomplete ROOT population")


def read_native_rows(path):
    import awkward as ak
    import uproot
    with uproot.open(path) as stream:
        arrays = ak.to_list(stream["ntuple"].arrays(["Event", "mcWeights"], library="ak"))
    rows = []
    for row in arrays:
        if not row["mcWeights"]:
            raise ValueError("missing converted nominal weight")
        rows.append({"event_id": row["Event"], "weight_pb": row["mcWeights"][0]})
    return rows


def run(input_path, output_dir, *, detector_card, native_input=None, native_trace=None):
    """Write new artifacts only after all rows and input hashes validate."""
    if bool(native_input) != bool(native_trace):
        raise ValueError("native input and trace must be supplied together")
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    output_paths = [output_dir / "truth_reco_response.jsonl.gz", output_dir / "truth_reco_response.json"]
    if any(p.exists() for p in output_paths):
        raise FileExistsError("response artifacts already exist; use a new output directory")
    dependencies = [fingerprint(input_path), fingerprint(__file__), fingerprint(detector_card),
                    fingerprint(sys.executable)]
    native_rows, joined, native_header, scale = [], {}, None, None
    if native_input:
        native_rows = read_native_rows(native_input)
        joined, scale, deps, native_header = validate_native_join(input_path, native_input, native_trace, native_rows=native_rows)
        dependencies.extend(deps)
    header = {"kind": "header", "schema_version": SCHEMA_VERSION, "definitions": definitions(),
              "reader_runtime": reader_runtime(),
              "sources": dependencies, "detector_card_provenance": "supplied card hash; production-stage receipt is outside this diagnostic",
              "native_trace_header": native_header}
    summary = ResponseSummary()
    with tempfile.TemporaryDirectory(prefix=".response-", dir=output_dir) as temporary:
        temporary = Path(temporary)
        staged = temporary / output_paths[0].name
        with gzip.open(staged, "wt") as stream:
            stream.write(json.dumps(header, allow_nan=False) + "\n")
            for event in delphes_events(input_path):
                index = event["source_entry"]
                native = None
                if native_input:
                    if index >= len(native_rows) or native_rows[index]["event_id"] != event["event_number"]:
                        raise ValueError("converted event order/ID differs from original Delphes input")
                    if not math.isclose(native_rows[index]["weight_pb"], event["weight"] * scale, rel_tol=2e-5, abs_tol=1e-15):
                        raise ValueError("converted event weight disagrees with original input and receipt scale")
                    native = joined[event["event_number"]]
                row = analyze_event(event, native=native)
                summary.add(row)
                stream.write(json.dumps(row, allow_nan=False) + "\n")
        if native_input and summary.events != len(native_rows):
            raise ValueError("native and original event populations differ")
        if summary.events == 0:
            raise ValueError("empty Delphes input")
        for source in dependencies:
            verify_fingerprint(source)
        result = summary.result()
        result.update(definitions=definitions(), sources=dependencies,
                      reader_runtime=header["reader_runtime"],
                      detector_card_provenance=header["detector_card_provenance"],
                      native_join_status="verified_full_population_event_level" if native_input else "not_requested",
                      native_trace_header=native_header,
                      event_artifact={"path": output_paths[0].name, "sha256": fingerprint(staged)["sha256"]})
        staged_summary = temporary / output_paths[1].name
        staged_summary.write_text(json.dumps(result, indent=2, allow_nan=False) + "\n")
        # Atomic no-clobber publication, even if two callers race for the same name.
        output_paths[0].hardlink_to(staged)
        try:
            output_paths[1].hardlink_to(staged_summary)
        except BaseException:
            # Remove only the inode this invocation published, never a competing file.
            if output_paths[0].exists() and output_paths[0].samefile(staged):
                output_paths[0].unlink()
            raise
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--detector-card", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--native-input", type=Path)
    parser.add_argument("--native-trace", type=Path)
    args = parser.parse_args(argv)
    result = run(args.input, args.output_dir, detector_card=args.detector_card,
                 native_input=args.native_input, native_trace=args.native_trace)
    print(json.dumps({"status": result["status"], "events": result["input_events"],
                      "total_response": result["total_response"], "physics_certified": False}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
