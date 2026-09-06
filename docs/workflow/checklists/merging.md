# Checklist — multi-jet merging  ·  [judgment] decide · [agent] run

Hard radiation can determine acceptance even when the sought particles decay only to leptons.
Matrix-element multiplicities, shower recoil and their overlap must therefore be assessed against
the actual observables. The size and sign of an approximation's effect are measured per process
and selection. Agreement with a final contour does not by itself validate the radiation model.

## When to merge
- Read the publication's generator, multiplicities, shower, tune, PDF and matching prescription.
  Distinguish decay jets from radiation jets and identify observables sensitive to the latter.
- For compressed sleptons, a hard recoil can be essential for the missing-momentum trigger and
  RISR selection. ATLAS SUSY-2018-16 uses up to two extra partons and CKKW-L at one quarter of the
  slepton mass. Its electroweakino merging scale is different. A two-lepton label is no exemption.
- Treat an unmerged fixed-multiplicity RRR recipe as a declared approximation. Check generation-cut
  dependence, recoil spectra and selection efficiencies before interpreting it as experiment-level
  fidelity. A `cause_class` label from a cutflow report is a hypothesis until controlled variation
  supports it.
- The current explicit-cards native execution adapter supports unmerged LO only. Its rejection of
  mixed multiplicities and matching settings protects normalization. A merged adapter needs an
  audited accounting of attempted, vetoed and accepted weights before it can serve these samples.

## MLM setup and separate CKKW-L requirements (MadGraph + Pythia8)
1. **Process** — add the extra-jet multiplicities, e.g.
   ```
   generate    p p > go go
   add process p p > go go j
   add process p p > go go j j
   ```
2. **MadGraph run card** — MLM: `ickkw = 1`, plus `xqcut` (the ME/PS matching scale).
   Start from a justified process-specific prescription and declare variations before inspecting
   agreement. Evaluate rates and differential distributions with integration and sampling errors.
   Ordinary MLM and CKKW-L do not impose exact inclusive unitarity; agreement with the zero-parton
   LO rate is a diagnostic, not a universal 5% acceptance gate. Historical worked example
   (gluino pair, m = 1000 GeV, `p p > go go` + j + jj,
   MLM `ickkw=1`, `qCut = 1.25×xqcut`, `nJetMax=2`, `nQmatch=4`, 1k events/point; LO reference
   σ = 0.201 pb):

   | xqcut [GeV] | pre-veto σ [pb] | matched σ [pb] | matched/LO |
   |---|---|---|---|
   | 100 | 0.3972 | 0.1887 | 0.939 |
   | 150 | 0.3110 | 0.1926 | 0.958 |
   | 250 | 0.2484 | 0.1972 | 0.981 |

   These central values vary by 4.4%; the historical production choice was 250 GeV. This retained
   table lacks uncertainties and differential jet-rate evidence and therefore does not establish
   a precision plateau by itself. Do not reuse its mass fraction or 5% heuristic as a general
   certificate. `ptj`/`mmjj` follow `xqcut` automatically under
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
   sit above the generation resolution scale. The example's factor 1.25 is a historical choice;
   its sensitivity must be studied with enough events to distinguish variation from noise.
   CKKW-L is a different prescription: use its documented `Merging:*` configuration, process and
   multiplicity handling, and merging-weight normalization. Switching names in an MLM card does
   not implement or validate CKKW-L.
4. **Validate the merging prescription** — inspect differential jet rates across the scale,
   leading-jet and recoil spectra, missing momentum, and the selections that determine acceptance.
   Report rate/shape variation and its uncertainty. Preserve all attempted/accepted counts,
   vetoes, nominal and merging weights, integration errors and normalization factors. An unstable
   result can indicate insufficient precision, incorrect setup or a poor scale choice; diagnose
   which before changing it.

## Expected effect
Merging may change low- as well as high-multiplicity acceptance when recoil enters selection.
The direction is not prescribed. Re-run cutflows and shape comparisons with the same detector,
PDF, normalization and statistical model so the intended change can be isolated.
Record in `provenance.json`: per-subprocess pre-veto σ ± integration error (from the banner), the
matched σ, `xqcut`, `qCut`/`nJetMax`/`nQmatch`, and the scan table that justified the scale
(`docs/workflow/checklists/generation-settings.md` lists the full provenance fields).

## Primary references

- [ATLAS compressed search, arXiv:1911.12606](https://arxiv.org/abs/1911.12606), signal simulation
  and the distinct slepton/electroweakino prescriptions.
- [PYTHIA 8.3, section 5](https://pythia.org/pdfdoc/pythia8300.pdf), accuracy by multiplicity and
  the difference between ordinary and unitarized merging.
- [PYTHIA MLM interface](https://pythia.org/latest-manual/JetMatching.html) and
  [matching/merging frontend](https://pythia.org/latest-manual/MatchingAndMerging.html), hooks,
  vetoes and process-dependent weight accounting. Pin the installed-version documentation when
  executing; the latest manual is an explanatory reference, not a frozen runtime specification.
