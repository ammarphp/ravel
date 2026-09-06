# Checklist — defining the model cards  ·  [judgment]

Two cards drive MadGraph: the **process card** (what to produce) and the **parameter card** (the
physics point). Either accept them from the requester or write them.

## Process card
```
import model <MODEL>          # e.g. sm, MSSM_SLHA2, a UFO model
generate p p > <final state>  # the hard process; add jets / vetoes as needed
output <dir> -f -nojpeg
```
- Choose the final state so the chosen routine selects on it (jets+MET search → coloured production;
  dilepton search → dilepton final state; etc.).
- For a non-bundled model, fetch its UFO and place it in MadGraph's `models/`.

## Parameter card (the point under test)
- Set the masses in the `MASS` block for the relevant PDG codes; decouple irrelevant states (large mass).
- Set the decays so the produced particles give the intended final state — either declare them in
  `DECAY` blocks (Pythia applies them via the SLHA), or use MadGraph decay-chain syntax
  `generate p p > X X, (X > a b)`.
- If MadGraph rejects a supplied SLHA card with `InvalidParam`, normalize its DECAY lines:
  `environment/scripts/normalize_param_card.py`.

Keep any supplied original card unmodified; edit a copy.

## Electroweakino simplified models (the mixing is real judgement, not a default)
For a chargino/neutralino simplified model, masses, mixing and decay assumptions must describe
the declared model. Inspect the actual imported UFO and restriction/cache inputs before editing
the card. Physical MASS entries and mixing matrices can be independent external parameters;
`MSOFT/HMIX` presence does not prove that MadGraph recomputes or overrides them.

- **Choose and record the model interface.** A supplied simplified-model spectrum uses explicit
  physical masses, mixing and decays. A self-consistent MSSM spectrum instead needs a declared
  spectrum calculation with its inputs, output masses/mixing and validity checks. Do not infer
  the latter from setting M1/M2/μ alone, or replace supplied mixing with guessed pure-state values.
  Pin the imported model, effective restriction, cards and any spectrum-calculator output.
- **Give every produced unstable sparticle explicit BR rows; include `MODSEL` (`1 1`).** Corrected
  (source-verified): Pythia 8.312 imports SLHA `DECAY` tables **regardless of MODSEL** when
  `SLHA:useDecayTable=on`. The real silent killer is a **width-only DECAY table** (no BR rows —
  MadGraph's default restrict card): Pythia imports nothing ("ignoring empty DECAY tables"), and with
  internal SUSY off ("No MODSEL found…") it cannot compute the channels itself → undecayed sparticles
  → empty SRs, exit 0. `MODSEL` is still required the moment any particle relies on Pythia's internal
  machinery for its decays — include it always; never rely on it alone.
- **Mixing:** the N/U/V matrices affect couplings and decay predictions. Pure bino/wino entries
  are simplified-model assumptions when supplied independently; changing a soft parameter does
  not automatically update an external mixing matrix. Check the model's dependencies explicitly.
- **Forced decays:** one `DECAY 1000024` block `→ 1000022 24` (C1→N1 W) at BR 1.0 and one
  `DECAY 1000023` block `→ 1000022 23` (N2→N1 Z) at BR 1.0; Pythia decays the W/Z.
- **Production:** `generate p p > x1+ n2` / `add process p p > x1- n2` (wino associated production). EWK
  final states can still depend on recoil radiation; assess multiplicities and matching against
  the publication and selection (`docs/workflow/checklists/merging.md`). The LO σ is
  corrected to NLO+NLL via `nlo_xsec.py --process wino-c1n2` — **note that file is a single charge
  state** (`1000023 -1000024`); compare it to a *single-charge* LO, or sum both charges (see
  `docs/workflow/steps/07-exclude.md`).
- **VERIFY BEFORE SHOWERING (catches S1 in seconds):** read the first LHE event and confirm the
  generated particle masses equal the intended point (`m(C1)=m(N2)=m_wino`, `m(N1)=m_LSP`), and confirm
  the shower actually produces leptons (C1/N2 decayed). A `pyslha.readSLHAFile` check (one DECAY channel
  each, model interface recorded) is the pre-flight. Generated masses check the executed point;
  they do not by themselves validate mixing, widths, branching ratios or all events.

## Slepton-bino simplified model (the EwkCompressed2018 / RRR Fig-3 case)
The inspected MSSM_SLHA2 interface exposes the produced slepton masses and bino mass as direct
MASS entries, with mixing supplied separately. Preserve that declared interface and inspect it
again when changing the model or restriction. A mass-only scan is not a newly diagonalized MSSM
spectrum, and inherited widths/decays need a separate check at small splittings. A parameterized
base is bundled:
- **Param card:** `…/envs/pipeline/share/mapyde/cards/param/SleptonBino.slha` has `{{MSLEP}}` (all six
  charged sleptons 1000011/13/15 + 2000011/13/15) and `{{MN1}}` (the bino LSP, 1000022) as jinja
  placeholders, with explicit **BR=1 decay rows** (ℓ̃→χ̃₁⁰ + ℓ) — so no width-only decay trap, leptons
  are produced. Render the two masses in: either `mapyde config generate-mg5 <toml>`, or (native path)
  `prepare_native_slepton.py --m-parent <MSLEP> --m-lsp <MN1>` (which renders this card + `run.mg5` +
  `shower.cfg`; see `docs/workflow/reference/native-pipeline.md`).
- **Process:** slepton pair + 1 ISR jet, `p p > chsleptons chsleptons j / susystrong @1` (the mapyde
  `isrslep` proc card; the mass-independent block is `src/ravel/data/templates/slepton_isrslep_generate.mg5`).
  This alias includes staus; it is not the four selectron/smuon diagonal channels. Record the
  actual channel list. The unmerged one-parton recipe is an approximation to be tested for
  generation-cut and recoil dependence, not an exemption from the merging review. See
  [the merging checklist](merging.md) for the distinct ATLAS prescription.
- **σ:** LO MadGraph × a flat k≈1.18 (mapyde's slepton default); NLO+NLL via `nlo_xsec.py --process slepton`.
- **The grid is the point:** a single (MSLEP, MN1) is ONE scan point — define the full `grid:` in the
  step-8 spec (`benchmarks/specs/slepton-bino-figure-3-coarse.json`), not a single card. On-grid range Δm ≈ 5–40 GeV.
- **The `run.mg5` card-provisioning idiom** (how `prepare_native_slepton.py::write_run_mg5` hands
  MadGraph the cards, and the pattern to reuse when generalizing `prepare_native_*` to a new model):
  after `launch <procdir>` and the `madspin/shower/reweight=OFF` block, the param-card and run-card
  **absolute paths are given on their own bare lines** (MadGraph's interactive prompt consumes them
  in order — param card first, then run card), followed by `set iseed <N>` then `done`. This is the
  scriptable equivalent of the interactive card selection; the bare-path lines are positional, so
  keep the order (param, run) and always use absolute paths (a relative path resolves against the
  procdir, not the run dir, and silently loads the wrong card).
- **VERIFY:** `lhe_check.py` (masses, single-weight, MODSEL warning is OK here — the BR rows apply) +
  confirm the shower produces soft e/µ.
