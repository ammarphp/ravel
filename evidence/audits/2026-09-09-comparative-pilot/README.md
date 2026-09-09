# Comparative pilot evidence

This bundle records bounded exploratory execution controls. It is not a full RRR reproduction, a blinded success-rate study or a ranking of scientific accuracy. The [assessment](../../../docs/research/2026-09-09-comparative-pilot.md) describes scope, availability and proposed capability work.

Open the [figure gallery](index.html) for the actual producer outputs. The
[outcomes](outcomes.json) retain all six assigned subject/task runs, plus the
excluded initial MadAgents harness failure and separate operator control.
Scope refusals receive no delivery-success credit. All pilot check-ins use
scripted affirmative permission, never substantive expert review.

## Contents and scope

- [Protocol](protocol.json) and [exact task text](prompts/drell-yan.txt), including
  the [single-bin counting request](prompts/atlas-2jl-counting-control.txt) and
  [experimental operating policy](prompts/experimental-policy.txt).
- [Public repository pins](repository-pins.json), [source availability](source-availability.json),
  [effective generation settings](effective-recipes.json), and [approval audit](approval-audit.json).
- Independently read LHE audits for [ColliderAgent](collideragent/drell-yan/lhe-audit.json),
  [HEPTAPOD](heptapod/drell-yan/lhe-audit.json) and the explicitly
  [operator-assisted MadAgents control](madagents-operator-control/drell-yan/lhe-audit.json).
  Each retains the original compressed-event-file hash and all 100 pair masses.
- [Counting audit](independent-counting-audit.json), the two original serialized
  likelihoods, reported numerical limits, curves and PNG/PDF figures.
- [Routing census](routing-census.json) and [focused routing repair](routing-repair-check.json).
- [Verification record](verification.json) and [bundle checksums](checksums.json).

Both counting components return approximately 43.6513 observed and 54.8857
median-expected signal events. Each full statistical workflow remains unmet.
ColliderAgent's native generation route delivers the requested artifacts;
HEPTAPOD requires integration workarounds. Ravel's generation-control route is
unsupported. MadAgents' timed run is confounded by evaluator thread admission
and native linker failures; its subsequent operator-assisted generation works.

The [private-record manifest](private-record-manifest.json) binds the archived
full logs, exact framework prompts and run receipts. Raw generator events,
cards, runtime logs and third-party checkouts are retained locally, outside the
public source distribution. Public hashes establish an identity to compare
against those originals; they do not make private event files or sessions
publicly inspectable. No third-party implementation code is included in this bundle.

## Rechecking the numerical control

With the project's replay dependencies and pyhf 0.7.6 installed, run:

```sh
python3 evidence/audits/2026-09-09-comparative-pilot/verify_counting.py
```

This independently invokes the same statistical library on both serialized
workspaces and verifies 22 conditions across inputs, interior roots, local
crossings and units. It does not establish frequentist coverage or recreate the
ATLAS control-region likelihood. The LHE audit command is documented in the
[comparative protocol](../../../benchmarks/comparative/README.md); it requires
the corresponding original LHE file.
