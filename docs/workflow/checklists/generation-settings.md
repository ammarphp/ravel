# Checklist — generation settings

Edit the MadGraph run card (`<procdir>/Cards/run_card.dat`) with a **keyed Python replace — never
`sed`**: a greedy `sed 's/.*= key/…/'` silently misses on the run card's spacing and nearby comment
lines (an `iseed` sed miss was observed in the field — the intended seed was never applied, exit 0).
Pattern (same idiom as `docs/workflow/checklists/merging.md`):

```python
import re; rc="<procdir>/Cards/run_card.dat"; t=open(rc).read().splitlines()
edits={"nevents":"10000","ebeam1":"6500.0","ebeam2":"6500.0","iseed":"42","use_syst":"False"}
for i,l in enumerate(t):
    for k,v in edits.items():
        if re.search(r"=\s*"+k+r"\b", l): t[i]=re.sub(r"^\s*\S+\s*=","  "+v+"  =",l)
open(rc,"w").write("\n".join(t)+"\n")
```

| Field | Set to |
|---|---|
| `ebeam1`, `ebeam2` | √s / 2 in GeV — **must match the routine's beam energy** (e.g. 6500 for 13 TeV) |
| `nevents` | ~10k for a shape/plot demo; **scale it so the weakest SR you intend to certify holds ≥25 raw events** (the tail-SR statistics advisory in `docs/workflow/steps/03-generate.md`) |
| `iseed` | **an explicit integer** (reproducibility). With `0` MadGraph auto-assigns a seed; either way the seed actually *used* is recorded only in the run banner (`Events/<run>/*_banner.txt`) — and MadGraph resets the card's `iseed` to 0 after every run, so **the banner, not the post-run card, is the seed record** |
| `use_syst` | **`False` — the pipeline norm** (single nominal weight). `True` bloats the LHE with variation weights and risks a multiweight LHE silently entering the single-weight analysis path; `src/ravel/validation/lhe_check.py` detects the leak. Set `True` only when a PDF/scale-band study is the explicit goal (and then the whole downstream path must be multiweight-aware) |

**Decoupled masses**: use **4.5e9 GeV** for every decoupled sparticle, consistently. Values ≳1e10
risk numeric trouble in the matrix-element/width machinery, and mixed decoupling conventions across
cards get flagged at audit. (Card recipe: `docs/workflow/checklists/model-cards.md`.)

**Proc-card portability**: the steering script's `output <dir>` path is either **relative to the
repo root** (state the required cwd in a comment) or clearly machine-local (absolute) — pick one and
record which; the script reproduces elsewhere only if the path convention is explicit. Pin the MG5
version in provenance.

**Provenance — record at generation time, for every new run** (in the run's `provenance.json`):
- `pdlabel` + `lhaid` (the PDF set) and `dynamical_scale_choice`;
- σ **± the MadGraph integration error** from the run banner — per-subprocess lines too when the
  sample is merged (plus pre-veto vs matched σ after the shower);
- the MG5 version, `nevents`, and the **banner** `iseed`;
- if merged: `ickkw`, `xqcut`, and the shower-side `qCut` / `nJetMax` / `nQmatch`. Note: with
  `auto_ptj_mjj = T` (the default) the *effective* `ptj`/`mmjj` follow `xqcut` — the card's literal
  `ptj` line is stale; record `xqcut`.

If the process has extra-jet multiplicities and the merging is done in the shower (CKKW-L), set
`ickkw = 0`, `xqcut = 0`, and regulate jets with `ptj`. MLM merging: `docs/workflow/checklists/merging.md`.

Pythia shower cfg: read the LHE (`Beams:frameType=4`, `Beams:LHEF=…`), `SLHA:useDecayTable = on`,
and set any stable BSM particle (the LSP) `:mayDecay = off`.

Always do a small run (≤1k events) first to confirm the chain, then scale up — and run the
mandatory pre-shower gate `src/ravel/validation/lhe_check.py` on every LHE before any shower
time (`docs/workflow/steps/03-generate.md`).
