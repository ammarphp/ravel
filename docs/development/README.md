# Developer guide

Start with [CONTRIBUTING.md](../../CONTRIBUTING.md) for setup and checks. Use this
section to understand the implementation and maintain the repository.

| Topic | Guide |
|---|---|
| How requests, engines, and checks connect | [Architecture](architecture.md) |
| Where code, tests, documentation, and evidence belong | [Repository layout](repository-layout.md) |
| Current engineering state and open work | [Status](status.md) and [roadmap](roadmap.md) |
| Public exports and release checks | [Distribution](distribution.md) |
| Documentation conventions | [Documentation](documentation.md) |
| Recorded fixes and their verification | [Change registry](change-registry.md) |

## Sources of truth

`src/ravel/` contains the implementation. `benchmarks/cases.json` defines the
registered statistical checks; `benchmarks/results.json` is their historical
baseline. Fresh replay output is a separate record. `benchmarks/capabilities.json`
contains internal capability classifications, which are rendered by
`scripts/gen_status.py` into the relevant documentation.

The [results overview](../validation/results.md) presents artifact-linked numerical
claims. The publication checks validate these declared claims and known scope
constraints. They cannot certify arbitrary prose or substitute for scientific
review. See [evidence documentation](../validation/evidence.md).

## Historical records

The [repository hygiene audit](history/2026-09-05-repository-hygiene.md) records the
source/public migration and preservation checks. The [September hardening audit](history/2026-09-05-hardening.md) distinguishes the
fresh cached replay from historical results and records the missing-artifact
breaches. Older plans, audits, and environment-change records remain in `history/`
so earlier decisions can be traced. Their dated claims do not override current
code, capability state, or validation outcomes.

Prospective scientific studies and competitive comparisons belong in
[research](../research/README.md); operational instructions belong in the
[workflow guide](../workflow/README.md).
