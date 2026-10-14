"""Supplied-binning, event-linked response diagnostics using stored ancestry.

Particle relations, labels and topology requirements are supplied explicitly.
ROOT reading uses the installed uproot/awkward toolchain; calculations use stdlib.
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

SCHEMA_VERSION = 2

class ResponseInputError(ValueError):
    def __init__(self,message,reason='invalid_input'):
        super().__init__(message);self.reason=reason


def study_contract(value):
    required={'study_id','parameter_grid','datasets','output'}
    if not isinstance(value,dict) or not required<=set(value):raise ResponseInputError('supplied study and output specification required','missing_input')
    if set(value)!=required or not isinstance(value['study_id'],str) or not value['study_id'] or not isinstance(value['parameter_grid'],list) or not isinstance(value['datasets'],list) or not value['datasets']:
        raise ResponseInputError('complete study, parameter grid and dataset population required')
    output=value['output']
    if not isinstance(output,dict) or set(output)!={'stem','formats'} or not isinstance(output['stem'],str) or Path(output['stem']).name!=output['stem'] or output['stem'] in ('','.','..') or not isinstance(output['formats'],list) or not output['formats'] or len(set(output['formats']))!=len(output['formats']) or not set(output['formats'])<={'json','markdown'}:
        raise ResponseInputError('safe supplied report stem and formats required')
    json.dumps(value,allow_nan=False)
    return value


def response_contract(contract):
    required={'schema_version','study_id','parameter_grid','datasets','output_format','pt_edges','abs_eta_edges','flavours','parent_relations','ancestor_categories','origin_labels','stable_pids','topology'}
    if not isinstance(contract,dict) or not required<=set(contract):
        raise ResponseInputError('supplied response contract required','missing_input')
    if set(contract)!=required or type(contract['schema_version']) is not int or contract['schema_version']!=1:
        raise ResponseInputError('closed response contract/v1 required')
    for key in ('study_id',):
        if not isinstance(contract[key],str) or not contract[key]:raise ResponseInputError('explicit study identity required')
    if not isinstance(contract['parameter_grid'],list) or not isinstance(contract['datasets'],list) or not contract['datasets']:
        raise ResponseInputError('explicit parameter grid and dataset population required')
    if contract['output_format'] not in ('json','jsonl.gz'):raise ResponseInputError('supported response output format required')
    for key in ('pt_edges','abs_eta_edges'):
        edges=contract[key]
        if not isinstance(edges,list) or len(edges)<2 or edges[0]!=0 or edges[-1] is not None or any(type(v) not in (int,float) or not math.isfinite(v) for v in edges[:-1]) or any(a>=b for a,b in zip(edges[:-2],edges[1:-1])):
            raise ResponseInputError('complete ordered nonnegative binning with open final endpoint required')
    flavours=contract['flavours']
    if not isinstance(flavours,list) or not flavours or any(set(row)!={'pid','label','branch'} or type(row['pid']) is not int or row['pid']<=0 or not isinstance(row['label'],str) or not row['label'] or not isinstance(row['branch'],str) or not row['branch'] for row in flavours) or len({r['pid'] for r in flavours})!=len(flavours) or len({r['label'] for r in flavours})!=len(flavours):
        raise ResponseInputError('complete unique selected particle flavours required')
    relations=contract['parent_relations']
    if not isinstance(relations,list) or not relations or any(set(row)!={'parent_pid','child_pid','same_sign'} or type(row['parent_pid']) is not int or row['parent_pid']<=0 or row['child_pid'] not in {r['pid'] for r in flavours} or type(row['same_sign']) is not bool for row in relations) or len({r['parent_pid'] for r in relations})!=len(relations):
        raise ResponseInputError('explicit unique ancestry relations required')
    cats=contract['ancestor_categories']
    if not isinstance(cats,list) or any(set(row)!={'id','pids'} or not isinstance(row['id'],str) or not row['id'] or not isinstance(row['pids'],list) or any(type(v) is not int or v<=0 for v in row['pids']) for row in cats) or len({r['id'] for r in cats})!=len(cats):raise ResponseInputError('explicit ordered ancestor categories required')
    labels=contract['origin_labels']
    if not isinstance(labels,dict) or set(labels)!={'direct','descendant','other'} or any(not isinstance(v,str) or not v for v in labels.values()) or len(set(labels.values())|{r['id'] for r in cats})!=len(labels)+len(cats):raise ResponseInputError('unique supplied origin labels required')
    if not isinstance(contract['stable_pids'],list) or any(type(v) is not int or v<=0 for v in contract['stable_pids']):raise ResponseInputError('explicit stable-particle population required')
    if not isinstance(contract['topology'],list):raise ResponseInputError('explicit topology rules required')
    for rule in contract['topology']:
        if not isinstance(rule,dict) or set(rule)!={'kind','value'} or rule['kind'] not in ('allowed_roots','root_count','stable_count','direct_count','opposite_signed_pair'):raise ResponseInputError('supported supplied topology rule required')
        if rule['kind']=='allowed_roots':
            if not isinstance(rule['value'],list) or any(type(v) is not int or v<=0 for v in rule['value']):raise ResponseInputError('explicit allowed-root population required')
        elif rule['kind']=='opposite_signed_pair':
            if type(rule['value']) is not bool:raise ResponseInputError('explicit pair requirement required')
        elif type(rule['value']) is not int or rule['value']<0:raise ResponseInputError('nonnegative topology count required')
    return contract


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


def definitions(contract):
    contract=response_contract(contract)
    return {'contract':contract,'matching':'unique same-event stored Particle UID/TRef; no geometric fallback',
            'ancestry':'stored mother endpoints; completeness beyond stored endpoints not inferred',
            'weight':'raw supplied event weight; no exposure scaling inferred',
            'bins':{'truth_pt_gev':contract['pt_edges'],'truth_abs_eta':contract['abs_eta_edges'],'interval':'lower inclusive, upper exclusive; final null is infinity'},
            'uncertainty':'shared-event delta-method ratio moments; boundary counts remain unresolved',
            'scope':'source-bound diagnostic; no detector calibration or physics certification'}


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


def _ancestor_indices(index,mothers):
    seen=set();pending=list(mothers[index])
    while pending:
        current=pending.pop()
        if current not in seen:seen.add(current);pending.extend(mothers[current])
    return seen


def vector(p):
    result = {key: finite(p[key], key) for key in ("pt", "eta", "phi")}
    if result["pt"] < 0:
        raise ValueError("negative transverse momentum")
    if "energy" in p:
        result["energy"] = finite(p["energy"], "energy")
        if result["energy"] < 0:
            raise ValueError("negative energy")
    return result


def analyze_event(event, *, contract=None, native=None):
    """Pure event calculation. Malformed identities/ancestry fail, not disappear."""
    contract=json.loads(json.dumps(response_contract(contract),allow_nan=False))
    flavours={r['pid']:r['label'] for r in contract['flavours']}
    relations={r['parent_pid']:r for r in contract['parent_relations']}
    parent_pids=set(relations)
    source_entry = integer(event["source_entry"], "source entry")
    if source_entry < 0:
        raise ValueError("negative source entry")
    event_id = integer(event["event_number"], "Delphes event number")
    weight = finite(event["weight"], "nominal weight")
    particles = event["particles"]
    mothers, order = mothers_and_order(particles)
    by_uid = {p["uid"]: i for i, p in enumerate(particles)}
    # Two flags suffice for origin labels, without materializing O(N^2) ancestor sets.
    flags = [set() for _ in particles]
    direct_paths = [{} for _ in particles]
    for i in order:
        p = particles[i]
        flags[i] = {r["id"] for r in contract["ancestor_categories"] if abs(p["pid"]) in r["pids"]}
        for mother in mothers[i]:
            flags[i].update(flags[mother])
        if abs(p["pid"]) not in flavours:
            continue
        for mother in mothers[i]:
            ancestor = particles[mother]
            if abs(ancestor["pid"]) in parent_pids:
                direct_paths[i][mother] = [i, mother]
            elif ancestor["pid"] == p["pid"]:
                for root, chain in direct_paths[mother].items():
                    direct_paths[i][root] = [i, *chain]
    roots = [i for i, p in enumerate(particles) if abs(p["pid"]) in parent_pids
             and not any(particles[m]["pid"] == p["pid"] for m in mothers[i])]
    direct = {}
    for i, p in enumerate(particles):
        if p["status"] != 1 or abs(p["pid"]) not in flavours or not direct_paths[i]:
            continue
        if len(direct_paths[i]) != 1:
            raise ValueError("ambiguous direct parent ancestry")
        parent, chain = next(iter(direct_paths[i].items()))
        parent_pid = particles[parent]["pid"]
        relation=relations[abs(parent_pid)]
        if relation["child_pid"] != abs(p["pid"]) or (relation["same_sign"] and (parent_pid > 0) != (p["pid"] > 0)):
            raise ValueError("parent and direct child flavour/sign disagree")
        direct[i] = {"particle_index": i, "particle_uid": p["uid"], "pid": p["pid"],
                     "flavour": flavours[abs(p["pid"])], "bare": vector(p),
                     "parent_index": parent, "parent_pid": parent_pid,
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
        if reco["flavour"] not in flavours.values() or flavours.get(abs(p["pid"])) != reco["flavour"]:
            raise ValueError("reco TRef flavour disagreement")
        if p["status"] != 1:
            raise ValueError("reco TRef does not refer to a stable particle")
        origin = (contract['origin_labels']['direct'] if index in direct else
                  next((r['id'] for r in contract['ancestor_categories'] if r['id'] in flags[index]),
                       contract['origin_labels']['descendant'] if any(abs(particles[m]['pid']) in parent_pids for m in _ancestor_indices(index,mothers)) else contract['origin_labels']['other']))
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
    stable_count=sum(p['status']==1 and abs(p['pid']) in contract['stable_pids'] for p in particles)
    for rule in contract['topology']:
        kind,value=rule['kind'],rule['value']
        actual={'root_count':len(roots),'stable_count':stable_count,'direct_count':len(direct)}
        failed=(any(abs(particles[i]['pid']) not in value for i in roots) if kind=='allowed_roots' else
                (value and (len(roots)!=2 or particles[roots[0]]['pid']!=-particles[roots[1]]['pid'])) if kind=='opposite_signed_pair' else actual[kind]!=value)
        if failed:violations.append(kind)
    return {"kind": "event", "source_entry": source_entry, "delphes_event_number": event_id,
            "native_event_id": native_fields["event_id"] if native_fields else None,
            "weight_raw": weight, "particle_entries": len(particles),
            "root_parents": [{"particle_index": i, "pid": particles[i]["pid"]} for i in roots],
            "stable_particle_count": stable_count,
            "direct_particles": list(direct.values()), "reco_particles": reco_rows,
            "topology_contract": contract["topology"],"contract_sha256":hashlib.sha256(json.dumps(contract,sort_keys=True,allow_nan=False).encode()).hexdigest(),
            "topology_violations": violations, "native": native_fields}


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
    def __init__(self,contract=None):
        self.contract=json.loads(json.dumps(response_contract(contract),allow_nan=False))
        flavours={r["pid"]:r["label"] for r in contract["flavours"]}
        parent_pids={r["parent_pid"] for r in contract["parent_relations"]}
        pt_edges=contract["pt_edges"];eta_edges=contract["abs_eta_edges"]
        self.events = self.particles = self.negative_weights = 0
        self.sumw = self.sumw2 = 0.
        self.ids = set()
        self.topology = Counter()
        self.parents = Counter({str(x): 0 for x in sorted(parent_pids)})
        self.violations = 0
        self.topology_policy = None
        self.origins = {f: Counter({o: 0 for o in [ *contract["origin_labels"].values(),*[r["id"] for r in contract["ancestor_categories"]]]}) for f in flavours.values()}
        self.bins = {(f, p, e): RatioMoments() for f in flavours.values()
                     for p in range(len(self.contract["pt_edges"])-1) for e in range(len(self.contract["abs_eta_edges"])-1)}
        self.totals = {f: RatioMoments() for f in flavours.values()}
        self.migrations = defaultdict(lambda: [0, 0., 0.])

    def add(self, row):
        if row.get("contract_sha256")!=hashlib.sha256(json.dumps(self.contract,sort_keys=True,allow_nan=False).encode()).hexdigest():raise ResponseInputError("cannot combine different supplied response contracts")
        if self.topology_policy is not None and self.topology_policy != row["topology_contract"]:
            raise ValueError("cannot combine different declared population policies")
        self.topology_policy = row["topology_contract"]
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
        self.violations += bool(row["topology_violations"])
        self.topology[(len(row["root_parents"]), row["stable_particle_count"], len(row["direct_particles"]))] += 1
        self.parents.update(str(abs(p["pid"])) for p in row["root_parents"])
        bins, totals, migration = defaultdict(lambda: [0, 0]), defaultdict(lambda: [0, 0]), Counter()
        for p in row["direct_particles"]:
            f, v, reco = p["flavour"], p["bare"], p["matched_reco"]
            key = (f, bin_index(v["pt"], self.contract["pt_edges"]), bin_index(abs(v["eta"]), self.contract["abs_eta_edges"]))
            bins[key][0] += 1
            bins[key][1] += reco is not None
            totals[f][0] += 1
            totals[f][1] += reco is not None
            if reco:
                for axis, edges, truth, measured in (("pt", self.contract["pt_edges"], v["pt"], reco["vector"]["pt"]),
                        ("abs_eta", self.contract["abs_eta_edges"], abs(v["eta"]), abs(reco["vector"]["eta"]))):
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
        for p in row["reco_particles"]:
            self.origins[p["flavour"]][p["origin"]] += 1

    def result(self):
        return {"schema_version": SCHEMA_VERSION, "status": "diagnostic_complete", "contract":self.contract,
                "topology_population_status": ("not_requested" if not self.topology_policy else
                    "FAIL" if self.violations else "consistent_with_supplied_topology"),
                "topology_violating_events": self.violations,
                "physics_certified": False, "input_events": self.events, "particle_entries": self.particles,
                "raw_weights": {"sumw": self.sumw, "sumw2": self.sumw2, "negative_events": self.negative_weights},
                "signed_weight_caution": self.negative_weights > 0,
                "root_parent_counts_both_charges": dict(self.parents),
                "topology": [{"root_parents": k[0], "stable_particles": k[1], "direct_particles": k[2], "events": v}
                             for k, v in sorted(self.topology.items())],
                "reco_origin_counts": {f: dict(v) for f, v in self.origins.items()},
                "total_response": {f: m.result() for f, m in self.totals.items()},
                "response_bins": [{"flavour": f, "pt_bin": p, "abs_eta_bin": e, **v.result()}
                                  for (f, p, e), v in self.bins.items()],
                "matched_migrations": [{"flavour": k[0], "axis": k[1], "truth_bin": k[2], "reco_bin": k[3],
                                         "count": v[0], "sumw": v[1], "event_sumw2": v[2]}
                                        for k, v in sorted(self.migrations.items())]}


def validate_trace_row(row,contract):
    if not isinstance(contract,dict) or not {'predicates','regions','unavailable','sources'}<=set(contract):raise ResponseInputError('supplied trace contract required','missing_input')
    integer(row['event_id'],'trace event ID');finite(row['weight_pb'],'trace weight')
    predicates=row['predicates']
    if not isinstance(predicates,dict) or set(predicates)!=set(contract['predicates']) or any(v is not None and type(v) is not bool for v in predicates.values()):raise ValueError('complete trace predicate population required')
    if any(predicates[k] is not None for k in contract['unavailable']):raise ValueError('unavailable predicate cannot become a measured decision')
    regions=row['accepted_regions']
    if not isinstance(regions,list) or len(set(regions))!=len(regions) or not set(regions)<=set(contract['regions']):raise ValueError('unknown or duplicate accepted region')
    if any(predicates[k] is not True for region in regions for k in contract['regions'][region]):raise ValueError('region lacks passed membership predicates')
    json.dumps(row,allow_nan=False)
    return row


def validate_native_join(delphes_path, native_path, trace_path, *, native_rows, join_contract=None):
    """Bind the optional event-level native trace through its actual converter receipt."""
    if not isinstance(join_contract,dict):raise ResponseInputError("supplied trace contract required","missing_input")
    receipt_path = Path(str(native_path) + ".normalization.json")
    receipt = json.loads(receipt_path.read_text())
    if type(receipt.get("schema_version")) is not int or receipt["schema_version"] != 1 or receipt.get("luminosity_applied") is not False:
        raise ValueError("unsupported converter receipt schema or luminosity-applied weights")
    verify_fingerprint(receipt["sources"][0], delphes_path)
    verify_fingerprint(receipt["output"], native_path)
    dependencies = [fingerprint(native_path), fingerprint(trace_path), fingerprint(receipt_path),
                    fingerprint(__file__)]
    for source in receipt["sources"]:
        verify_fingerprint(source)
        dependencies.append(source)
    if receipt.get("normalization"):
        verify_fingerprint(receipt["normalization"])
        dependencies.append(receipt["normalization"])
    # Reuse the native trace's membership and unknown-predicate validator.
    from . import compressed_validation
    compressed_validation.summarize_trace(trace_path)
    for pin in join_contract['sources'].values():
        verify_fingerprint(pin);dependencies.append(pin)
    with gzip.open(trace_path, "rt") as stream:
        header = json.loads(next(stream))
        from .analysis_packages import selection_source_from_metadata
        selection_source, selection_pins = selection_source_from_metadata(header.get('metadata', {}))
        dependencies.extend(selection_pins)
        if (header.get("kind") != "header" or header.get("schema_version") != 1
                or header.get("level") != "reco" or header.get("weight_unit") != "pb"
                or header["metadata"]["input_sha256"] != receipt["output"]["sha256"]):
            raise ValueError("native trace is not bound to the converted input")
        if any(header['metadata'].get(key)!=pin['sha256'] for key,pin in join_contract['sources'].items()):
            raise ValueError('native trace source hashes disagree with supplied source files')
        rows = {}
        for line in stream:
            row = json.loads(line)
            validate_trace_row(row,join_contract)
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


def delphes_events(path, *, contract=None, step_size=128):
    contract=response_contract(contract)
    import awkward as ak
    import uproot
    branches = ["Event.Number", "Event.Weight", *["Particle." + x for x in PARTICLE_FIELDS.values()]]
    branches += [f"{f}.{x}" for f in [r["branch"] for r in contract["flavours"]] for x in ("Particle", "PT", "Eta", "Phi")]
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
                for branch, flavour in [(r["branch"],r["label"]) for r in contract["flavours"]]:
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


def run(input_path, output_dir, *, detector_card, contract=None, native_input=None, native_trace=None, join_contract=None):
    contract=response_contract(contract)
    """Write new artifacts only after all rows and input hashes validate."""
    if bool(native_input) != bool(native_trace):
        raise ValueError("native input and trace must be supplied together")
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    output_paths = [output_dir / ("truth_reco_response.jsonl.gz" if contract["output_format"]=="jsonl.gz" else "truth_reco_events.json"), output_dir / "truth_reco_response.json"]
    if any(p.exists() for p in output_paths):
        raise FileExistsError("response artifacts already exist; use a new output directory")
    dependencies = [fingerprint(input_path), fingerprint(__file__), fingerprint(detector_card),
                    fingerprint(sys.executable)]
    native_rows, joined, native_header, scale = [], {}, None, None
    if native_input:
        native_rows = read_native_rows(native_input)
        joined, scale, deps, native_header = validate_native_join(input_path, native_input, native_trace, native_rows=native_rows,join_contract=join_contract)
        dependencies.extend(deps)
    header = {"kind": "header", "schema_version": SCHEMA_VERSION, "definitions": definitions(contract),
              "reader_runtime": reader_runtime(),
              "sources": dependencies, "detector_card_provenance": "supplied card hash; production-stage receipt is outside this diagnostic",
              "native_trace_header": native_header}
    summary = ResponseSummary(contract)
    with tempfile.TemporaryDirectory(prefix=".response-", dir=output_dir) as temporary:
        temporary = Path(temporary)
        staged = temporary / output_paths[0].name
        opener=gzip.open if contract["output_format"]=="jsonl.gz" else open
        with opener(staged, "wt") as stream:
            if contract["output_format"]=="json":stream.write("["+json.dumps(header,allow_nan=False))
            else:stream.write(json.dumps(header, allow_nan=False) + "\n")
            for event in delphes_events(input_path,contract=contract):
                index = event["source_entry"]
                native = None
                if native_input:
                    if index >= len(native_rows) or native_rows[index]["event_id"] != event["event_number"]:
                        raise ValueError("converted event order/ID differs from original Delphes input")
                    if not math.isclose(native_rows[index]["weight_pb"], event["weight"] * scale, rel_tol=2e-5, abs_tol=1e-15):
                        raise ValueError("converted event weight disagrees with original input and receipt scale")
                    native = joined[event["event_number"]]
                row = analyze_event(event,contract=contract,native=native)
                summary.add(row)
                stream.write(("," if contract["output_format"]=="json" else "")+json.dumps(row, allow_nan=False) + "\n")
            if contract["output_format"]=="json":stream.write("]\n")
        if native_input and summary.events != len(native_rows):
            raise ValueError("native and original event populations differ")
        if summary.events == 0:
            raise ValueError("empty Delphes input")
        for source in dependencies:
            verify_fingerprint(source)
        result = summary.result()
        result.update(definitions=definitions(contract), sources=dependencies,
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
    parser.add_argument("--contract", required=True, type=Path)
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--detector-card", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--join-contract", type=Path)
    parser.add_argument("--native-input", type=Path)
    parser.add_argument("--native-trace", type=Path)
    args = parser.parse_args(argv)
    result = run(args.input, args.output_dir, detector_card=args.detector_card,contract=json.loads(args.contract.read_text()),
                 native_input=args.native_input, native_trace=args.native_trace,join_contract=json.loads(args.join_contract.read_text()) if args.join_contract else None)
    print(json.dumps({"status": result["status"], "events": result["input_events"],
                      "total_response": result["total_response"], "physics_certified": False}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
