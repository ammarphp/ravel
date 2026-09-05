# Case study: porting the full reinterpretation chain to native ARM64

**Result: the same 50,000-event physics point runs in 41m47s natively vs 8h55m04s under x86
emulation — 12.8× — with all 141 signal-region outputs bit-identical and the end-to-end
statistical limit reproduced to 0.51%.**

## The problem

The reference pipeline (mapyde, arXiv:2306.11055) runs its analysis stage inside an x86_64 ATLAS
container. On an Apple-silicon laptop that container runs under QEMU emulation inside a podman VM,
and the emulation tax dominates: a single 50,000-event pipeline point took **8h55m04s** wall time,
with MadGraph alone accounting for ~7.9h of it. Points were also serialized behind one shared VM,
so a 52-point parameter scan was effectively a multi-week job.

## What actually changed

No physics was altered. The port replaced the *execution substrate* stage by stage:

| Stage | Before (container) | After (native ARM64) |
|---|---|---|
| MadGraph5_aMC@NLO | x86 binary under QEMU | native install (conda gfortran toolchain) |
| Pythia8 shower | container | native `pythia_shower` driver (HepMC3 bridge, project-authored) |
| Delphes | container | native `DelphesHepMC3` build against native ROOT |
| Delphes→SimpleAnalysis conversion | container tool | `delphes2sa_native.py` (validated bit-identical) |
| SimpleAnalysis (EwkCompressed2018) | ATLAS x86 framework binary | `native_simpleanalysis.py` — a from-scratch Python+uproot reimplementation of the routine's full object selection, overlap removal, and 141-signal-region cascade |
| Recursive-jigsaw variables (R_ISR, M_S) | inside the SA binary | `rjr_resolve.cc` — a native driver reconstructing the identical RestFrames tree, fed the identical selected objects |
| yields → likelihood patch | container tool | `sa2json_native.py` (validated bit-identical) |
| pyhf limit | native already | unchanged |

The only genuinely hard piece was the last analysis mile: the ATLAS SimpleAnalysis framework
builds only on x86 (AnalysisBase 21.2), so the routine's selection logic was reimplemented from
scratch and the recursive-jigsaw reconstruction was rebuilt against a natively compiled
RestFrames.

## Correctness methodology — the part that matters

Speed claims are cheap; the port was accepted only after three independent checks, in order of
increasing strictness:

1. **Bit-identical intermediate conversions.** The native Delphes→SA converter and the yields→
   patch converter were compared byte-for-byte against container outputs on shared inputs.
2. **Bit-identical analysis outputs, 141/141.** On a shared 50k-event detector-level input, the
   native reimplementation's per-signal-region event counts were compared against the container's
   SimpleAnalysis output for **every one of the 141 EwkCompressed2018 signal regions: all 141
   identical** (integer event counts, exact match; the reconstructed recursive-jigsaw variable
   R_ISR agrees to float32 precision, max |ΔR_ISR| ≈ 7e−7). Same-format output files were diffed
   directly.
3. **End-to-end statistical agreement on independent generation.** A fully fresh native run
   (its own MadGraph seed → shower → detector → analysis → likelihood) reproduced the container
   reference's observed µ95 limit to **0.51%** — bounding everything the bit-level checks cannot
   see (generator build, shower, detector build) at the physics-conclusion level.

## The two timing artifacts

Both runs are committed evidence (`logs/STATUS.txt`, per-stage timestamps):

| | start → end | wall | evidence |
|---|---|---|---|
| container (x86 emulated) | 2026-06-07 13:11:19 → 22:06:23 | **8h55m04s** | `trial-runs/2026-06-06_slepton_200-150_50k/logs/STATUS.txt` |
| native ARM64 | 2026-06-16 04:55:56 → 05:37:43 | **41m47s** | `trial-runs/2026-06-16_slepton_200-150_native/logs/STATUS.txt` |

Same model point (slepton 200 GeV, LSP 150 GeV), same 50,000 events, same 8-stage chain.
32104s / 2507s = **12.8×**.

## Consequences

Beyond the single-point speedup, going native removed the shared-VM serialization: scan points
now run in parallel (4-way on a laptop), which is what made the two full 52-point mass-plane
scans (2.08M events total) feasible on local hardware. The 141/141 + 0.51% methodology is now the
repo's standing template for accepting any execution-substrate change (see
`docs/development/change-registry.md`).

*Scope note: the native SimpleAnalysis reimplementation currently covers the EwkCompressed2018
routine (the flagship analysis); other SimpleAnalysis routines fall back to the container path.
The Rivet analysis path is native everywhere.*
