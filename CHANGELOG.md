# Changelog

## v0.1.0 — 2026-08-16

First tagged public snapshot.

- Full reinterpretation chain (MadGraph5 → Pythia8 → Delphes → Rivet/SimpleAnalysis → pyhf)
  with a governed control plane: typed task contracts, human-approval gates, provenance and
  sha-pinned claim evidence, adversarial gate board.
- 7 published-analysis benchmarks reproduced within 8.6% (best 0.2%), CI-re-fit on every run.
- Native ARM64 execution: 8h55m → 41m47s (12.8×) on the identical 50k-event point.
- Native SimpleAnalysis backend: 3 routines validated bit-for-bit against the containerized
  original (EwkCompressed2018 141/141 signal regions; ZeroLeptonDiscovery2018 10/10;
  EwkThreeLeptonERJR2018 9/9) + a declarative engine for cut-based routines.
- Replay-mode quickstart (3 commands, no HEP-stack install) and a 344-test suite, all CI-green.
