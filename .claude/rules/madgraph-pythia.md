# Rule — MadGraph + Pythia (generation & showering)

Run commands from the repository root in Bash. First run `source native/scripts/paths.sh`;
this selects the native build and binary paths, including an existing local toolchain.

Read when generating events, building cards, or showering. The hard-won idioms; getting these wrong
fails *silently* (exit 0, plausible-but-wrong output).

## Invocation idioms
- `conda run -n <env> … <<heredoc` does **not** pass stdin. Write to `/tmp/x.py`, then
  `<conda> run -n mg5 python /tmp/x.py`. (`<conda>` = `$RAVEL_NATIVE_BUILD/tools/miniforge3/bin/conda`.)
- `timeout` is absent on this host. Long gens/showers/builds → background jobs + poll the log.
- MadGraph `output <dir>` writes the process dir at exactly `<dir>`. After `generate_events`, **confirm
  `<procdir>/Events/<run>/` exists and is non-empty** before trusting a "done".
- **Never consume a mid-write `.lhe.gz`.** A COMPLETE MadGraph product carries a terminal
  `Cross-section :` line in `logs/*.log`, a gzip that decompresses to EOF, and a banner `nevents` equal
  to its counted `<event>` records. If any of those fail (producer still running, truncated gzip, or the
  "grabbed the LHE mid-write, 7031 not 10000" banner/count mismatch), the shower silently loses events.
  `validate_run_state.py`'s `producer-complete` invariant (N4) hard-FAILs on exactly this — let the
  banner σ line appear before any consumer reads the LHE.

## Run-card edits — keyed Python, not greedy sed
A single `sed 's/.*= xqcut/…/'` silently misses (run-card spacing + the `auto_ptj_mjj … if xqcut >0`
comment line). Use:
```python
import re; rc="<procdir>/Cards/run_card.dat"; t=open(rc).read().splitlines()
for i,l in enumerate(t):
    if re.search(r"=\s*xqcut\b", l): t[i]=re.sub(r"^\s*\S+\s*=","  80.0  =",l)
    if re.search(r"=\s*ickkw\b", l): t[i]=re.sub(r"^\s*\S+\s*=","  1  =",l)
open(rc,"w").write("\n".join(t)+"\n")
```
Common keys: `nevents`, `ebeam1/2` (= ½·√s, so 6500 for 13 TeV), `iseed` (MadGraph resets to 0 after
each run — re-set to reproduce), `use_syst=False` (single nominal weight).

## SLHA card invariant — verify masses + decays BEFORE showering (a 🔴 silent trap)
Determine which inputs the actual imported model consumes. A UFO may expose physical masses and
mixing matrices as independent external SLHA parameters; a spectrum calculator may instead derive
them from soft parameters. `MSOFT/HMIX` presence alone does not establish an override. Pin the UFO,
restriction/cache inputs and effective cards; inspect their mass and coupling dependencies before
changing the spectrum. The inspected RRR MSSM_SLHA2 interface reads `Mneu1` from `MASS[1000022]`
and NMIX independently. This supports its supplied simplified-model interface, not a newly
diagonalized MSSM spectrum. Decays (source-verified Session 2 in Pythia's upstream SLHAinterface.cc source,
plus a direct 8.312 shower test):
MadGraph does **NOT** inject `MODSEL` into the LHE banner — the banner carries exactly what the input
card had — and Pythia 8.312 imports SLHA `DECAY` tables **regardless of MODSEL** when
`SLHA:useDecayTable=on`. The real silent killer is a **width-only DECAY table** (total width, no BR
rows — MadGraph's default restrict card): Pythia imports nothing ("ignoring empty DECAY tables"), and
with internal SUSY off (no MODSEL) it can't compute the channels itself → undecayed sparticles →
empty SRs, exit 0. Include `MODSEL` (`1 1`) anyway — it is required the moment any particle relies on
Pythia's internal machinery for its channels. Preserve the declared spectrum/mixing/decay policy,
give every produced unstable sparticle explicit BR rows, then run the automated pre-shower guard
`src/ravel/validation/lhe_check.py <lhe> --expect-mass <PDG>:<mass> …` (first-event + banner
masses, MODSEL, weight structure, merged-vs-unmerged) and **confirm the shower makes the expected
decay products**. The EWKino simplified-model recipe is in `docs/workflow/checklists/model-cards.md`.

## ISR and multi-jet merging
Decide from the published signal simulation and the observables that provide acceptance. A
two-lepton or monojet label does not establish that shower-only ISR is adequate. In compressed
SUSY-2018-16, the recoil jet, missing momentum and RISR are central to selection; the ATLAS
slepton samples include up to two extra partons with CKKW-L and a merging scale of one quarter
of the slepton mass. Keep this distinct from the RRR unmerged one-parton approximation.
The current explicit-cards native adapter intentionally rejects merged samples because their
vetoes and weights require a different normalization contract. Do not bypass that guard.

For a separately supported MLM workflow:
1. Process: `generate p p > <parents>` + `add process … j` + `… j j`.
2. Run card: `ickkw=1`; assess `xqcut` with a **measured scale-variation study** including
   integration and sampling errors, jet rates and analysis-relevant shapes. A small smoke can
   detect gross failures but cannot establish a precision plateau. With
   `auto_ptj_mjj=T` the applied parton cut is `xqcut`, not the literal `ptj` line. Full recipe + the
   worked example: `docs/workflow/checklists/merging.md`.
3. **Matched shower** with `$RAVEL_NATIVE_BIN/pythia_shower_merged` (uses the
   `CombineMatchingInput` MLM hook). The plain `pythia_shower` has **no** matching hook and would
   double-count the ME jets.
4. Pythia cfg (explicit — `setMad=on` often can't parse MG's header and silently defaults `qCut=10`,
   which vetoes **every** event): `JetMatching:merge=on`, `scheme=1`, `setMad=off`, `qCut ≥ xqcut`
   (e.g. 100), `nJetMax=2`, `nQmatch=4`.
5. Validate accepted weights, cross sections, differential jet rates and recoil/selection shapes
   over declared variations. MLM and ordinary CKKW-L do not guarantee exact preservation of the
   lowest-multiplicity LO inclusive cross section. Do not select a scale just to force that
   equality or move a result toward a publication. The old 5% comparison was a scoped diagnostic
   for one retained multijet example, not a universal physical law.

Record the source-backed prescription, approximation and unresolved uncertainty before running.
See `docs/workflow/checklists/merging.md` for primary references and the historical example.
