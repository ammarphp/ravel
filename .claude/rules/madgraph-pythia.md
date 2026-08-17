# Rule — MadGraph + Pythia (generation & showering)

Read when generating events, building cards, or showering. The hard-won idioms; getting these wrong
fails *silently* (exit 0, plausible-but-wrong output).

## Invocation idioms
- `conda run -n <env> … <<heredoc` does **not** pass stdin. Write to `/tmp/x.py`, then
  `<conda> run -n mg5 python /tmp/x.py`. (`<conda>` = `stages/01-event-generation/build/tools/miniforge3/bin/conda`.)
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
For `MSSM_SLHA2`, gaugino masses are derived from `MSOFT` (M1/M2/M3) + `HMIX` (μ) and **override** the
`MASS` block; a card whose `MASS` says 300 but whose `MSOFT` says otherwise silently generates the
wrong spectrum. Decays (source-verified Session 2, `SLHAinterface.cc` + a direct 8.312 shower test):
MadGraph does **NOT** inject `MODSEL` into the LHE banner — the banner carries exactly what the input
card had — and Pythia 8.312 imports SLHA `DECAY` tables **regardless of MODSEL** when
`SLHA:useDecayTable=on`. The real silent killer is a **width-only DECAY table** (total width, no BR
rows — MadGraph's default restrict card): Pythia imports nothing ("ignoring empty DECAY tables"), and
with internal SUSY off (no MODSEL) it can't compute the channels itself → undecayed sparticles →
empty SRs, exit 0. Include `MODSEL` (`1 1`) anyway — it is required the moment any particle relies on
Pythia's internal machinery for its channels. So: set the soft params consistent with the target,
give every produced sparticle explicit BR rows, then run the automated pre-shower guard
`trial-runs/_infrastructure/lhe_check.py <lhe> --expect-mass <PDG>:<mass> …` (first-event + banner
masses, MODSEL, weight structure, merged-vs-unmerged) and **confirm the shower makes the expected
decay products**. The EWKino simplified-model recipe is in `workflow/checklists/model-cards.md`.

## Multi-jet merging (≥4-jet SRs need it, or they come out ~30–40% low)
1. Process: `generate p p > <parents>` + `add process … j` + `… j j`.
2. Run card: `ickkw=1`; pick `xqcut` from a **measured matched-σ stability scan** (cheap: ~1k events
   at 2–3 scales post-compile; accept |matched/LO−1| ≤ 5%; ¼·m(parent) is the usual winner). With
   `auto_ptj_mjj=T` the applied parton cut is `xqcut`, not the literal `ptj` line. Full recipe + the
   worked example: `workflow/checklists/merging.md`.
3. **Matched shower** with `trial-runs/_infrastructure/pythia_shower_merged` (uses the
   `CombineMatchingInput` MLM hook). The plain `pythia_shower` has **no** matching hook and would
   double-count the ME jets.
4. Pythia cfg (explicit — `setMad=on` often can't parse MG's header and silently defaults `qCut=10`,
   which vetoes **every** event): `JetMatching:merge=on`, `scheme=1`, `setMad=off`, `qCut ≥ xqcut`
   (e.g. 100), `nJetMax=2`, `nQmatch=4`.
5. Validate: matched σ should ≈ the lowest-multiplicity LO σ (the veto preserves the inclusive rate);
   high-mult SR yields rise toward published. Scan `xqcut` for σ-stability.

EWK / lepton-only / monojet searches do **not** need merging — record that deliberate choice.
