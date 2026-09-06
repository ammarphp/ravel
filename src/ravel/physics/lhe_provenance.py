"""Original-LHA content identity for newly produced nominal HepMC3 streams.

The exact LHA parsing/identity primitives derive from the independently reviewed
original-v1 replay verifier. This module performs no replay byte comparison and
makes no assertion about detector fidelity, normalization or signed-weight MC
estimators. An owned successful producer and execution receipt remain necessary.
"""
from __future__ import annotations

import gzip
import hashlib
import json
import math
import os
from pathlib import Path
import re
import stat

MAX_LINE = 4 * 1024 * 1024

def require(c,m):
 if not c:raise ValueError(m)

def integer(v,label):
 require(type(v)is int,label+' must be an exact integer');return v

def number(v,label):
 require(type(v)in(int,float)and math.isfinite(v),label+' must be finite numeric');return float(v)

def strict_json(text):
 def pairs(items):
  d={}
  for k,v in items:
   require(k not in d,'Duplicate JSON key');d[k]=v
  return d
 def bad(v):raise ValueError('Nonfinite JSON constant')
 v=json.loads(text,object_pairs_hook=pairs,parse_constant=bad)
 json.dumps(v,allow_nan=False);return v

def event_value(header,particles,label):
 require(type(header)is list and len(header)==6,label+': six header fields required')
 n=integer(header[0],label+' NUP');integer(header[1],label+' IDPRUP')
 require(0<n<=10000 and type(particles)is list and len(particles)==n,label+': exact NUP population required')
 header=[*header[:2],*[number(x,label+' header')for x in header[2:]]]
 converted=[]
 for row in particles:
  require(type(row)is list and len(row)==13,label+': thirteen particle fields required')
  ints=[integer(x,label+' integer particle field')for x in row[:6]]
  values=[number(x,label+' floating particle field')for x in row[6:]]
  require(0<=ints[2]<=ints[3]<=n and(ints[2]==0)==(ints[3]==0),label+': invalid mother range')
  require(values[3]>0 and values[4]>=0 and values[5]>=0,label+': unphysical particle energy/mass/lifetime')
  converted.append(ints+values)
 return {'header':header,'particles':converted}

def identity(event):
 """Exact binary64 values, including signed zero; no rounding or ordering fallback."""
 header=event['header'];parts=event['particles']
 return (tuple(header[:2])+tuple(float(x).hex()for x in header[2:]),tuple(tuple(p[:6])+tuple(float(x).hex()for x in p[6:])for p in parts))

def lhe_events(stream):
 """Strict nominal LHE event payload, comments allowed; no auxiliary XML weights.

    The complete document must be framed and all event blocks closed. The
    separately pinned physics reader remains responsible for model validation.
 """
 opened=False;closed=False;inside=False;record=[];ordinal=0
 for raw in stream:
  require(isinstance(raw,bytes)and len(raw)<=MAX_LINE,'Bounded binary LHE lines required')
  require(raw.endswith(b'\n'),'Incomplete LHE line')
  line=raw.decode('utf-8').strip()
  if re.fullmatch(r'<LesHouchesEvents(?:\s[^>]*)?>',line):
   require(not opened and not closed,'Duplicate LHE document start');opened=True
  elif line=='</LesHouchesEvents>':
   require(opened and not closed and not inside,'Invalid LHE document end');closed=True
  elif re.fullmatch(r'<event(?:\s[^>]*)?>',line):
   require(opened and not closed and not inside,'Invalid/nested LHE event start');inside=True;record=[raw]
  elif line=='</event>':
   require(inside,'Unmatched LHE event end');record.append(raw);inside=False
   numeric=[]
   for rawline in record[1:-1]:
    text=rawline.decode().split('#',1)[0].strip()
    if not text:continue
    require('<'not in text and'>'not in text,'Auxiliary LHE event metadata requires separately reviewed support')
    numeric.append(text.split())
   require(numeric and len(numeric[0])==6,'Malformed LHE event header')
   h=numeric[0];require(all(re.fullmatch(r'[+-]?\d+',x)for x in h[:2]),'LHE header integer required')
   header=[*map(int,h[:2]),*map(float,h[2:])];parts=[]
   for fields in numeric[1:]:
    require(len(fields)==13 and all(re.fullmatch(r'[+-]?\d+',x)for x in fields[:6]),'LHE particle record fields differ')
    parts.append([*map(int,fields[:6]),*map(float,fields[6:])])
   value=event_value(header,parts,'LHE ordinal '+str(ordinal));value.update(ordinal=ordinal,raw_event_sha256=hashlib.sha256(b''.join(record)).hexdigest())
   yield value;ordinal+=1
  elif inside:record.append(raw)
  elif closed:require(not line,'Trailing LHE document payload')
  elif '<event'in line or '</event'in line:raise ValueError('Malformed event framing')
 require(opened and closed and not inside,'Incomplete LHE document')

def sidecar_rows(stream):
 for raw in stream:
  require(isinstance(raw,bytes)and len(raw)<=MAX_LINE and raw.endswith(b'\n'),'Bounded complete sidecar line required')
  require(raw.strip(),'Blank sidecar row')
  value=strict_json(raw);require(type(value)is dict,'Sidecar row must be an object');yield value


def file_identity(path):
    """Observable identity; scientific artifact leaf aliases are unsupported.

    The current pathname's file identity is checked after every complete read.
    A caller needing a symlink-free runtime tree enforces that separate policy.
    """
    path = Path(path)
    require(not path.is_symlink(), f"Symlink artifact is unsupported: {path}")
    value = path.stat()
    require(stat.S_ISREG(value.st_mode), f"Regular file required: {path}")
    return (value.st_dev, value.st_ino, value.st_mode, value.st_size,
            value.st_mtime_ns, value.st_ctime_ns)


def pin(path):
    path = Path(path).absolute()
    before = file_identity(path)
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        require(_fd_identity(stream) == before, f"Input changed before read: {path}")
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
        require(_fd_identity(stream) == before, f"Input changed during read: {path}")
    require(file_identity(path) == before, f"Input changed after read: {path}")
    return {"path": str(path), "bytes": before[3], "sha256": digest.hexdigest()}


def _fd_identity(stream):
    value = os.fstat(stream.fileno())
    return (value.st_dev, value.st_ino, value.st_mode, value.st_size,
            value.st_mtime_ns, value.st_ctime_ns)


class HashedLines:
    """Bound memory before allocating a line; consume and hash through EOF."""
    def __init__(self, stream):
        self.stream = stream
        self.digest = hashlib.sha256()
        self.size = 0
        self.eof = False

    def __iter__(self):
        return self

    def __next__(self):
        raw = self.stream.readline(MAX_LINE + 1)
        if not raw:
            self.eof = True
            raise StopIteration
        require(isinstance(raw, bytes) and len(raw) <= MAX_LINE,
                "Oversized or nonbinary event line")
        self.digest.update(raw)
        self.size += len(raw)
        return raw

    def record(self):
        require(self.eof, "Full decoded EOF required")
        return {"sha256": self.digest.hexdigest(), "bytes": self.size,
                "complete_eof": True}


def scan_hepmc(stream, expected_events):
    """Verify ASCII-v3 framing and particle populations, not graph physics.

    WriterAscii can encode a vertex implicitly through a particle parent ID.
    Explicit V rows therefore need not equal the E header's vertex count.
    Their IDs are checked, while complete particle rows must equal that header.
    Attributes are retained in the full content hash, not interpreted as physics.
    """
    require(type(expected_events) is int and expected_events > 0, "Positive exact event count")
    lines = HashedLines(stream)
    version = started = ended = False
    current = None
    events = 0
    particle_total = 0

    def finish_event():
        if current is not None:
            require(current["particles"] == current["declared_particles"],
                    "HepMC particle population differs from event header")
            require(current["units"], "HepMC event units missing")

    for raw in lines:
        require(raw.endswith(b"\n"), "Incomplete HepMC line")
        line = raw.decode("ascii").strip()
        if not line:
            continue
        if line.startswith("HepMC::Version "):
            require(not version and not started and not ended and
                    re.fullmatch(r"HepMC::Version 3\.\d+\.\d+", line),
                    "Invalid HepMC version framing")
            version = True
        elif line == "HepMC::Asciiv3-START_EVENT_LISTING":
            require(version and not started and not ended, "Invalid HepMC start framing")
            started = True
        elif line == "HepMC::Asciiv3-END_EVENT_LISTING":
            require(started and not ended, "Invalid HepMC end framing")
            finish_event()
            ended = True
        else:
            require(started and not ended, "HepMC payload outside listing")
            fields = line.split()
            kind = fields[0]
            if kind == "E":
                finish_event()
                require(len(fields) in (4, 9) and all(re.fullmatch(r"[+-]?\d+", x)
                        for x in fields[1:4]), "Malformed HepMC event header")
                event, vertices, particles = map(int, fields[1:4])
                require(event == events and vertices >= 0 and particles > 0,
                        "Noncontiguous HepMC event ID or invalid populations")
                if len(fields) == 9:
                    require(fields[4] == "@" and all(math.isfinite(float(x)) for x in fields[5:]),
                            "Invalid HepMC event position")
                events += 1
                require(events <= expected_events, "Excess HepMC events")
                current = {"particles": 0, "declared_particles": particles,
                           "declared_vertices": vertices, "vertices": set(), "units": False}
            elif current is None:
                require(kind in {"W", "T", "A"}, "HepMC event payload before first event")
            elif kind == "P":
                require(len(fields) == 10 and all(re.fullmatch(r"[+-]?\d+", fields[i])
                        for i in (1, 2, 3, 9)), "Malformed HepMC particle row")
                require(int(fields[1]) == current["particles"] + 1,
                        "Noncontiguous/duplicate HepMC particle ID")
                require(all(math.isfinite(float(x)) for x in fields[4:9]),
                        "Nonfinite HepMC particle field")
                current["particles"] += 1
                particle_total += 1
                require(current["particles"] <= current["declared_particles"],
                        "Excess HepMC particles")
            elif kind == "V":
                require(len(fields) >= 4 and re.fullmatch(r"-\d+", fields[1]),
                        "Malformed HepMC vertex row")
                vertex = int(fields[1])
                require(-current["declared_vertices"] <= vertex < 0 and
                        vertex not in current["vertices"], "Invalid/duplicate explicit HepMC vertex ID")
                current["vertices"].add(vertex)
            elif kind == "U":
                require(not current["units"] and len(fields) == 3 and
                        fields[1] in {"GEV", "MEV"} and fields[2] in {"MM", "CM"},
                        "Missing/duplicate/unsupported HepMC units")
                current["units"] = True
            else:
                require(kind in {"W", "A", "T"}, "Unsupported HepMC record kind")
    require(version and started and ended and events == expected_events,
            "Incomplete HepMC framing/event population")
    return {**lines.record(), "encoding": "HepMC3 ASCII", "events": events,
            "event_numbers": list(range(events)), "particles": particle_total,
            "complete_framing": True, "particle_populations_verified": True,
            "graph_physics_validated": False}


def join_lhe_sidecar(lhe, sidecar, expected_events):
    """Exact ordered content comparison, with uniqueness checked separately.

    Ordinals only confirm an already exact full-content match. They never
    supply or repair a missing original-LHA identity.
    """
    require(type(expected_events) is int and expected_events > 0, "Positive exact event count")
    lhe_lines, sidecar_lines = HashedLines(lhe), HashedLines(sidecar)
    originals = iter(lhe_events(lhe_lines))
    rows = iter(sidecar_rows(sidecar_lines))
    begin = next(rows, None)
    require(type(begin) is dict and set(begin) == {
        "type", "schema_version", "requested_events", "floating_precision", "source"},
        "Exact sidecar begin record required")
    require(begin["type"] == "begin" and type(begin["schema_version"]) is int and
            begin["schema_version"] == 1 and type(begin["requested_events"]) is int and
            begin["requested_events"] == expected_events and type(begin["floating_precision"]) is int and
            begin["floating_precision"] == 17 and begin["source"] == "existing_Pythia_getLHAupPtr",
            "Sidecar schema/count/precision/source differs")
    seen = set()
    joins = []
    negative = 0
    for i in range(expected_events):
        original, row = next(originals, None), next(rows, None)
        require(original is not None, "Missing original LHE event")
        require(type(row) is dict and set(row) == {
            "type", "loop_index", "successful_index", "hepmc_event_number", "header", "particles"},
            "Missing/malformed sidecar event")
        require(row["type"] == "event", "Non-event sidecar record")
        for name in ("loop_index", "successful_index", "hepmc_event_number"):
            require(integer(row[name], name) == i, "Sidecar event order/population differs")
        value = event_value(row["header"], row["particles"], "HepMC Event " + str(i))
        key = identity(original)
        require(key not in seen, "Ambiguous duplicate full original LHE event content")
        require(identity(value) == key, "Captured original LHA content differs from original LHE")
        seen.add(key)
        negative += original["header"][2] < 0
        joins.append({"hepmc_event_number": i, "original_lhe_ordinal": original["ordinal"],
                      "original_lhe_event_sha256": original["raw_event_sha256"],
                      "full_content_sha256": hashlib.sha256(repr(key).encode()).hexdigest(),
                      "original_weight": original["header"][2],
                      "original_particle_count": original["header"][0]})
    require(next(originals, None) is None, "Excess original LHE events")
    end = next(rows, None)
    require(type(end) is dict and set(end) == {
        "type", "events_written", "attempted", "next_failures", "complete"}, "Exact sidecar end required")
    require(end["type"] == "end" and end["complete"] is True and
            integer(end["events_written"], "Written") == expected_events and
            integer(end["attempted"], "Attempted") == expected_events and
            integer(end["next_failures"], "Failures") == 0, "Incomplete/failed sidecar population")
    require(next(rows, None) is None, "Trailing sidecar record")
    return {"original_events": expected_events, "joined_events": len(joins),
            "negative_original_weights": negative, "rows": joins,
            "lhe_content": lhe_lines.record(), "sidecar_content": sidecar_lines.record(),
            "identity": "Exact complete original LHA header and all thirteen particle fields, including signed zero; unique content and serialized HepMC Event order agree."}


def verify_new_generation(lhe, sidecar, hepmc, *, expected_events, encoding="plain"):
    """Verify actual output files, including encoded/decoded hashes and EOF.

    This is a content observation. The producing native stage binds the command,
    successful exit, immutable input snapshots and this report into its receipt.
    """
    require(encoding in {"plain", "gzip"}, "Unsupported HepMC encoding")
    paths = {name: Path(path).absolute() for name, path in
             (("lhe", lhe), ("sidecar", sidecar), ("hepmc", hepmc))}
    require(len({str(x.resolve()) for x in paths.values()}) == 3, "Provenance artifacts alias")
    before = {name: (file_identity(path), pin(path)) for name, path in paths.items()}
    with paths["lhe"].open("rb") as original, paths["sidecar"].open("rb") as captured:
        joined = join_lhe_sidecar(original, captured, expected_events)
    # Bind the descriptor actually decoded. A pathname can temporarily resolve
    # through another parent directory and be restored before final path checks.
    with paths["hepmc"].open("rb") as encoded:
        require(_fd_identity(encoded) == before["hepmc"][0],
                "HepMC opened descriptor differs from pinned source")
        if encoding == "gzip":
            with gzip.GzipFile(fileobj=encoded, mode="rb") as decoded:
                framed = scan_hepmc(decoded, expected_events)
        else:
            framed = scan_hepmc(encoded, expected_events)
            require(framed["sha256"] == before["hepmc"][1]["sha256"] and
                    framed["bytes"] == before["hepmc"][1]["bytes"],
                    "Plain HepMC decoded content differs from encoded pin")
        require(_fd_identity(encoded) == before["hepmc"][0],
                "HepMC descriptor changed during decoding")
    require(joined["lhe_content"]["sha256"] == before["lhe"][1]["sha256"] and
            joined["sidecar_content"]["sha256"] == before["sidecar"][1]["sha256"],
            "Content read differs from pinned original or sidecar")
    for name, path in paths.items():
        require(file_identity(path) == before[name][0] and pin(path) == before[name][1],
                f"Provenance artifact changed during verification: {name}")
    return {"schema_version": 1, "kind": "new_generation_original_lha_provenance",
            "status": "content_verified", "policy": "original-v1", "encoding": encoding,
            "replay_byte_equality_performed": False, "source_files": {
                name: item[1] for name, item in before.items()}, "hepmc_content": framed,
            **joined, "scope": "Original-LHA identity and produced HepMC content/framing only. No replay byte equality, physics certification, normalization or signed-MC estimator claim."}
