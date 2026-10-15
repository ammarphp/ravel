# Shipped analysis assets

Source-pinned descriptors and source bundles for the engines that take supplied descriptors.
Each file is bound by sha256; a different byte stream is refused. Nothing here is native
output, a built plugin, a calibration or a physics validation.

| Directory | Holds | Consumer |
|---|---|---|
| `six-b/` | released six-b routine, its six classifier models, reference YODA, Rivet support sources, `descriptor.json` (reversible source edits, trace manifest, model roster, build), `contracts.json` | `analysis_response_features`, `hhh_response`, `hhh_native_trace` |
| `group-fills/` | fill-site schemas (anchors, arity, multiplicity rules, output tables) for three released routines | `native_group_fills` |
| `response/` | direct slepton-lepton response contract | `truth_reco_response` |
| `cutflow/` | compressed-selection predicate flows and region membership | `compressed_validation` |

`ravel.physics.shipped_assets` resolves these to the absolute pins the engines take.
`six-b/COPYING` is the upstream GPL-3 licence of the copied Rivet files (see
`THIRD-PARTY-NOTICES.md`). `review-note.md` is the evidence file the reviewed records pin.
