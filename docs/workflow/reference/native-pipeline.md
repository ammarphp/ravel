# Reference — the NATIVE (VM-free) pipeline backend

The September 2026 [native fidelity audit](../../../evidence/audits/2026-09-05-native-fidelity/README.md)
corrects the eRJR invisible-momentum boost against the ATLAS paper. Its SR-low
selection intentionally differs from the older container oracle; the recorded
9/9 comparison is historical. The unchanged compressed and zero-lepton selections
were replayed separately. Selection parity alone does not certify physics fidelity.


The default execution backend for the scan (`scan_orchestrator launch --backend native`, step 8) and a
drop-in for a single point. It runs every stage in a **native arm64 conda env — no podman, no VM, no x86
emulation, no ATLAS AnalysisBase** — which makes a full-chain point **~30–50 min** (not ~9 h; the
MadGraph stage itself is minutes) and lets scan points run
**in parallel**. This is what unlocked local scans → contours.

## The chain (all native, `run-pipeline-native.sh <run-dir-abs> <config-rel>`)
| Stage | Tool / env | Notes |
|---|---|---|
| madgraph | `mg5_aMC` (mg5) | runs `output/run.mg5`; LHE only (`shower=OFF`) |
| pythia | `pythia_shower` (rivet) | LHE → HepMC3 (Monash default) |
| delphes | `DelphesHepMC3` (recast, ROOT 6.40) | the ATLAS card; native libDelphes |
| analysis | `delphes2sa_native.py` (recast) | Delphes→SA ntuple — **bit-identical to the container** |
| simpleanalysis | `native_simpleanalysis.py` (rivet) + `rjr_resolve` (recast) | **native EwkCompressed2018**: full object selection in Python, RestFrames RJR (`R_ISR`/`M_S`) via the natively-built `libRestFrames`; reproduces the container per-SR yields **bit-for-bit (141/141 SRs)** |
| sa2json | `sa2json_native.py` (rivet) | SA `.root` → pyhf signal patch (bit-identical) |
| pyhf | `pyhf_exclude.py` (rivet) | → `output/exclusion.json` (the harvest target) |

Validated end-to-end: a fresh native generation of slepton (200,150) reproduced the container's observed
µ₉₅ to **0.51%** (6.333 vs 6.366). The driver reads the mapyde TOML (`read_toml`, `python -c` not a
heredoc — `conda run <<heredoc` passes no stdin), parses σ from the MadGraph log × the k-factor, and
writes the same `logs/STATUS.txt` + `output/` layout as `run-pipeline.sh`, so `scan_orchestrator`
status/assemble are unchanged.

**Evidence:** the shipped `output/EwkCompressed2018.txt` (141/141 SR yields) and `output/exclusion.json`
(the 0.51% µ₉₅ comparison) back the two claims above — see `docs/validation/evidence.md`'s
`HEADLINE_native_141_bitforbit` / `HEADLINE_native_mu95_0p51pct` rows for the exact shipped path and
sha256 (the source run directory itself is a dev-only record per `docs/development/distribution.md`).

## Per-point input materialization — `prepare_native_slepton.py`
`run-pipeline-native.sh` expects `output/{run.mg5,shower.cfg,*_card.dat}` to exist; the orchestrator's
native launch calls `prepare_native_slepton.py --rundir <abs> --m-parent <M> --m-lsp <M> --nevents <N>
--toml <point-config.toml>` first. It renders the param card from the point's masses (the base
`SleptonBino.slha` has `{{MSLEP}}`/`{{MN1}}` placeholders + explicit BR=1 decay rows → no width-only
decay trap), the run card — applying the TOML's **`[madgraph.run.options]` block first, fail-loud on
any unmatched key** (`ptj1min=50` etc.; CR-002: dropping it silently generated at ptj1min=0, a ×2.14
σ_tag drift vs the container reference — `docs/development/change-registry.md`), then `{{ecms}}`→6500 GeV,
`{{nevents}}`/`{{iseed}}`, `pdlabel=cteq6l1` so no LHAPDF is needed (acc×eff is σ-independent so the
PDF set does not bias the cert) — `run.mg5` from the fixed slepton process template
(`src/ravel/data/templates/slepton_isrslep_generate.mg5`), and `shower.cfg`. A fail-loud guard rejects any unrendered
`{{…}}` placeholder. NOTE: every native sample generated BEFORE 2026-07-06 predates the run.options
fix (ptj1min=0); the 52-point fig3 grid rescan at ptj1min=50 is tracked as CR-004.

## Port-fidelity invariant — lepton-ID cuts are deliberate NO-OPS (do not "complete" them)
mapyde's share converter script `Delphes2SA` (consumed by both backends) writes `el_id`/`mu_id` =
`0x7FFFFFFF` — every quality bit set — for every lepton, because Delphes emulates no ID quality.
The native SA (`native_simpleanalysis.py`) accordingly reads the id fields but **never cuts on
them**, exactly like the container chain: that is part of WHY the yields are bit-for-bit
(141/141 SRs). A maintainer "completing" the port with real ID/quality cuts from the ATLAS
analysis source would silently change every SR yield and break the validated parity. Any future
ID-quality emulation is a DETECTOR-model change: it goes through the step-3.5 fidelity gate +
re-certification, not through the SA port.

## SCOPE + when to use the container instead
Two native SA paths now exist:
- **`native_simpleanalysis.py` + `rjr_resolve`** — the RJR-complex EwkCompressed2018 port,
  bit-for-bit vs the container (141/141 SRs). This is the worked example for analyses needing
  recursive jigsaw or bespoke variables; each such analysis is a per-analysis port (the `--objects`
  RJR interface already generalizes the jigsaw solve).
- **`native_sa_generic.py`** (CR-005, 2026-07-07) — a DECLARATIVE engine for the ~85% of SA
  analyses that are **cut-and-count on standard objects** (the 4 archetypes: 0ℓ jets+MET, 1ℓ+jets,
  2ℓ, monojet). It reuses the same validated primitives (imported from `native_simpleanalysis.py`)
  and runs a JSON analysis spec (object defs → overlap-removal order → signal tightenings → a
  derived-variable library → a declarative SR cut cascade) against a Delphes ROOT. Porting a
  cut-based analysis is a spec file, not a rewrite. `--selftest` PASS; the real-input path is
  `run --delphes <root> --spec <spec.json> --xs-pb <σ>`.
  **Remaining before it is the default for a given cut-based analysis:** an end-to-end validation of
  the generic path on a real Delphes ROOT vs a container SA run (bit-parity for the declarative
  engine, same class as the EwkCompressed2018 141/141 proof).

For an analysis the native paths do not yet cover (RJR not ported, or the generic engine not yet
validated for it) → `--backend container` (the mapyde VM path, `docs/workflow/analysis-simpleanalysis/`), general
but slow + sequential. `prepare_native_slepton.py` (the input materializer) is still slepton-card-
specific — generalizing it beyond slepton cards is the remaining CR-005 driver work.

## Build prerequisites (one-time, regenerable)
- Native RestFrames: `bash native/scripts/restframes-native-build.sh` installs under the selected native
  build directory's tools/restframes-native subdirectory (see `native/scripts/paths.sh`).
- The RJR resolver: `$CONDA run -n recast bash native/scripts/rjr-resolve-build.sh`.
Both are gitignored/regenerable; `run-pipeline-native.sh` assumes they exist.

## §porting — the CR-005 recipe: add the NEXT routine natively (~half a session, proven twice)
1. **Pick + read** the routine's ANA-…cxx source (SimpleAnalysisCodes/src under the
   SA source tree in the build tools). Disqualify (for THIS
   recipe) anything needing RestFrames, fat jets, photons, taus, or ML weights — those take a
   dedicated port (the flagship's RJR path) or a different route.
2. **Transcribe** into `src/ravel/physics/sa_routines/<name>.py` on `sa_native_core`
   (NAME/BRANCHES/FLAVOUR_FLAGS/`sr_order()`/`select(arrays, i)`), with an **ambiguity ledger**
   in the docstring. NON-NEGOTIABLE traps (each cost a real port a silent diff or nearly did):
   - **ID bits are copied header-verbatim from `AnalysisObject.h` enums — never guessed** (e.g.
     `EIsoFixedCutTight` is 1<<10, not 1<<14; `EGood` is a 7-bit combination).
   - **SA's `a + b` on collections SORTS by pT after concatenating** (`AnalysisObject.cxx`) —
     use `core.concat_sorted`, never python list `+`. Load-bearing wherever the combined list
     feeds `[i].Pt()` cuts (e.g. 0-lepton "corrected jets" = jets + 50 GeV leptons).
   - `sumObjectsPt`/`minDphi` take **first-N in list order** with a pt floor
     (`core.sum_objects_pt` / `core.min_dphi_n`); `aplanarity` = 1.5×λ_min of the |p|^(r−2)
     momentum tensor (`core.aplanarity`); variable-radius OR = `core.overlapRemovalVR`.
   - `getMCVeto()` is 0 on Delphes2SA input (no mcVetoCode); lepton-ID cuts are no-ops
     (el/mu_id = 0x7FFFFFFF) — transcribe them anyway, identically no-op in the oracle.
3. **Register** it in `src/ravel/physics/sa_routines/__init__.py::REGISTRY`; run via
   `native_simpleanalysis.py --routine <Name> --input <Delphes2SA.root> --output <dir>`.
4. **Sample**: materialize a rundir from a tracked card whose topology populates the routine
   (copy a smoke rundir's `output/{run_card,shower}.cfg` pattern; fix `Beams:LHEF`; drop
   `[madgraph.masses]` so the lhe_check gate derives expectations `--expect-from-card`), then
   `run-pipeline-native.sh` through the `analysis` stage.
5. **ORACLE GATE (mandatory)**: provision the container per-use (`podman machine init/start`
   via the NATIVE podman 5.8.2 bundled in the build tools (podman-native) — the conda podman's vfkit
   fails; source `pipeline-env.sh` under BASH, its `BASH_SOURCE` corrupts under zsh — then pull
   `simple-analysis:master`), and run
   `python3 scripts/run.py ravel.validation.validate_native_parity --rundir <dir> --config <toml> --routine <Name> --native-txt <txt>`.
   **100% of SR integer counts must match** (the container writes `<Name>_oracle.txt`; the
   validator never clobbers the native output). Tear the VM down after
   (`podman machine rm -f` + `system connection rm` + the machine cache dir).
6. **Record**: registry entry; per-analysis acc×eff certification (`certify_acceptance.py` vs
   the published maps) + a µ95 anchor where a likelihood exists are the physics-fidelity
   follow-through for any routine that will SERVE results (bit-for-bit alone proves the CODE).
