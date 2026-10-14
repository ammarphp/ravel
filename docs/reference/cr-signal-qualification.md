# Fixed CR signal response qualification

`cr-signal-qualification` connects a supplied complete pyhf workspace and its
previously retained compiled metadata to the ordinary scientific-study workflow.
The task is `{"input": "cr-signal.json"}`. Import, validation and planning perform
no model compilation or evaluation. A fresh ordinary approval is required for run.

The input document declares schema version 1, byte pins `workspace`,
`compiled_reference`, `runtime_inventory`, and a nonempty `grounding` list;
`measurement`, `signal`, the complete declared `all_controls` roster, its literal
`expected_membership`, and the exact exported `PROTOCOL`. Pins have `path` and
`sha256`. Membership rows have `channel`, `signal_sample_present` and `nominal`
(null for an absent signal). The runtime inventory uses the existing parity
schema: schema version 1 and complete admitted `files` with absolute path/hash.
The three new modules contain the contract and are discoverable through the
ordinary `science.adapter` interface and existing scientific-context tools.

The protocol fixes NumPy float64 and pyhf 0.7.6, three compilations, five vectors,
45 evaluator components, 120 seconds for the cooperative mathematical phase and
300 seconds for the scientific adapter, one attempt and zero fits/events/roots.
The ordinary supervisor owns the enforced stage limit and ending source custody.
Captured documents are capped at 16 MiB each and 64 MiB total. The actual encoded
checkpoint is capped at 16 MiB and the compact progress journal at 1 MiB. Runtime
files are streamed through the existing fresh validation-session implementation;
its 50,000-file inventory limit is unchanged. Runtime module-origin observation
is Python import evidence, not a complete OS dynamic-loader census.

The original workspace is one arm. The other two append a fixed unconstrained
normfactor, equal to one or zero, only to the named signal in control channels
where it exists. Absent samples remain absent. All original templates, modifiers,
constraints, observations and fixed/free parameters remain. In particular, a
shared `staterror` constraint is not reconstructed after deleting a sample.
The actual compiled parameter map must differ by exactly that fixed scalar.

The original initial vector and four prescribed simultaneous bounded nuisance
and POI displacements are evaluated in every arm. Each has per-sample means,
complete expected data and twice-NLL. Multiplier one must reproduce the original;
zero must remove exactly the CR signal response while preserving every SR,
background and auxiliary response. Independent scalar Poisson/Normal density
assembly shares the compiled main means. It does not independently implement
HistFactory interpolation. Every started/returned component is persisted before
the next call; returned values survive later numerical or custody failure.
Potential CR-only main-response flat directions are recorded without pruning
constraints or claiming full-NLL flatness.

Successful adapter delivery qualifies these five vectors and the declared
intervention only. It supplies no profile minimum, CLs limit, coverage,
response calibration, MPI attribution or reconstructed author execution.
A later fit needs its own input/model/protocol and independent numerical checks.
The scientific reviews must keep this scope and preserve the original failures.
# Ending output custody

The recorder retains exact expected checkpoint and progress-journal bytes. It
checks complete output membership and contents before each numerical persistence
and after ending input/runtime observations, including a partially failed
qualification. It never adopts changed bytes as the expected record. Fresh
terminal records use exclusive creation and are verified after writing. If late
corruption or partial terminal writing is discovered, the corrupted evidence is
preserved and a separate `delivery-failure.json` records the failed delivery.
An earlier summary is not authoritative over that failure or a failed stage.

The checkpoint and each of at most two terminal records are bounded by 16 MiB;
the journal is bounded by 1 MiB. The maximum expected generated output and its
in-memory byte census are therefore 49 MiB. These checks are fresh observations,
not a guarantee against changes after the final observation; the ordinary
supervisor and later independent review retain their own ending custody.
