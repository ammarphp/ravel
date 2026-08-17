# Checklist — multi-jet merging  ·  [judgment] decide · [agent] run

Why this matters: a search's high-jet-multiplicity signal regions are only populated correctly if the
extra hard jets come from the **matrix element**, not the parton shower alone. Plain LO single-process
generation lacks the hard ME jets, so the high-multiplicity yield is mismodelled — and the size, even
the sign, of the residual is analysis- and tune-specific (a missing-jet deficit can be offset or
reversed once the shower tune is accounted for), so it is **measured per run, not assumed**.
Merging extra ME multiplicities into the shower addresses the ME side of it.

## When to merge
- Any colored production where the analysis has SRs requiring **≥4 jets** (gluino/squark with long
  decay chains, multijet+MET searches). **Always** for `4j`–`8j`-type SRs.
- Skip for genuinely 2-body, low-multiplicity final states (e.g. slepton→ℓχ̃, 2-lepton SRs) — there the
  ISR jets are soft and the shower suffices.
- The cutflow certification (`validate_cutflow.py`) flags the need: if a high-multiplicity SR is low
  and attributed `cause_class: merging`, re-generate merged.

## CKKW-L / MLM recipe (MadGraph + Pythia8)
1. **Process** — add the extra-jet multiplicities, e.g.
   ```
   generate    p p > go go
   add process p p > go go j
   add process p p > go go j j
   ```
2. **MadGraph run card** — MLM: `ickkw = 1`, plus `xqcut` (the ME/PS matching scale). **The scale is
   measured, not assumed**: run a **matched-σ stability scan** — ~1k events/point across a ~2.5×
   span of `xqcut` (bracket from ~m/10 up to the ¼·m(parent) headline guess for the lightest
   produced sparticle), shower each point with the matched bridge, and accept an `xqcut` on the
   σ-plateau satisfying **|matched σ / LO σ − 1| ≤ 5%** (the MLM veto must preserve the inclusive
   lowest-multiplicity rate). Worked example (gluino pair, m = 1000 GeV, `p p > go go` + j + jj,
   MLM `ickkw=1`, `qCut = 1.25×xqcut`, `nJetMax=2`, `nQmatch=4`, 1k events/point; LO reference
   σ = 0.201 pb):

   | xqcut [GeV] | pre-veto σ [pb] | matched σ [pb] | matched/LO |
   |---|---|---|---|
   | 100 | 0.3972 | 0.1887 | 0.939 |
   | 150 | 0.3110 | 0.1926 | 0.958 |
   | 250 | 0.2484 | 0.1972 | 0.981 |

   Total matched-σ variation 4.4% over the 2.5× span — a genuine plateau; the m/4 point (250 GeV)
   preserved the inclusive rate best (−1.9%) and was the production choice. A lower plateau point
   can also pass (an 80 GeV `xqcut` on an 800 GeV squark sample matched to 0.9%) — **the scan, not
   the m/4 rule of thumb, decides**. `ptj`/`mmjj` follow `xqcut` automatically under
   `auto_ptj_mjj = T` (the default; verified at LHE level — the minimum light-parton pT tracks
   `xqcut` even when the card's literal `ptj` line still reads its old value), so record `xqcut`,
   not the stale `ptj` line. (CKKW-L instead: `ickkw = 0` in MadGraph and do the merging in Pythia.)
   **Edit these with a keyed Python replace, not a single greedy `sed`** — the run-card line spacing
   plus the nearby `auto_ptj_mjj … if xqcut >0` comment make `s/.*= xqcut/…/` fragile (it silently
   leaves the default; observed this run):
   ```python
   import re; rc="<procdir>/Cards/run_card.dat"; t=open(rc).read().splitlines()
   for i,l in enumerate(t):
       if re.search(r"=\s*xqcut\b", l): t[i]=re.sub(r"^\s*\S+\s*=","  80.0  =",l)
       if re.search(r"=\s*ickkw\b", l): t[i]=re.sub(r"^\s*\S+\s*=","  1  =",l)
   open(rc,"w").write("\n".join(t)+"\n")
   ```
   The procdir is exactly the `output <dir>` path (e.g. `build_madgraph/`); **after `generate_events`,
   confirm `<procdir>/Events/<run>/` exists and is non-empty before trusting it** — a procdir/path
   mismatch produces no events *with exit 0* (the most dangerous silent failure; observed this run).
3. **Pythia8 cfg** — turn on matching: `JetMatching:merge = on`, `JetMatching:scheme = 1` (MLM),
   `JetMatching:qCut = 1.25×xqcut`, `JetMatching:nJetMax = 2`, `JetMatching:setMad = off` (set qCut
   explicitly — `setMad=on` often can't parse MG's header and silently defaults qCut). `qCut` must
   sit **above** `xqcut`; the pipeline factor is **1.25×** (MadGraph's own pythia8 interface defaults
   to ~1.5×xqcut — the 1.25-vs-1.5 sensitivity is spot-checked with one qCut variant whenever a
   merged sample is scored against a published grid). For CKKW-L: `Merging:doKTMerging = on`,
   `Merging:TMS = <qCut>`, `Merging:Process`, `Merging:nJetMax`.
4. **Validate the merging scale** — the normative gate is the matched-σ stability scan of step 2
   (plateau in `xqcut`, |matched/LO − 1| ≤ 5%). Deeper diagnostic when in doubt: the **differential
   jet rates** must be smooth across the matching scale (no kink at qCut). Also re-check σ under the
   one qCut variant (e.g. 1.5×xqcut) when the sample is scored. An unstable σ means the scale is
   wrong.

## Expected effect
Merging changes the high-jet-multiplicity SR acceptance — usually lifting it toward the published
value, though the net size depends on the shower tune — while the low-multiplicity SRs are largely
unchanged. Re-run `validate_cutflow.py` after merging — the
high-multiplicity residuals should drop into their tier tolerance or shrink with the attribution.
Record in `provenance.json`: per-subprocess pre-veto σ ± integration error (from the banner), the
matched σ, `xqcut`, `qCut`/`nJetMax`/`nQmatch`, and the scan table that justified the scale
(`checklists/generation-settings.md` lists the full provenance fields).
