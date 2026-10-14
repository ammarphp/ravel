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
  corrected using `ravel xsec lookup --request request.json` with explicit order, PDF and scale,
  on the same production basis as the LO denominator (see `docs/workflow/steps/07-exclude.md`).
- **VERIFY BEFORE SHOWERING (catches S1 in seconds):** read the first LHE event and confirm the
  generated particle masses equal the intended point (`m(C1)=m(N2)=m_wino`, `m(N1)=m_LSP`), and confirm
  the shower actually produces leptons (C1/N2 decayed). A `pyslha.readSLHAFile` check (one DECAY channel
  each, model interface recorded) is the pre-flight. Generated masses check the executed point;
  they do not by themselves validate mixing, widths, branching ratios or all events.

## Selected model and process recipes

Use the [general card renderer contract](../reference/named-scans.md#card-recipe).
Supply parameter and run templates, a model/process source, a launch template, explicit
parameter addresses and generation controls. No model population or mass point is bundled.
Preserve source decay rows, production-state content, matching settings and normalization
conventions in the selected input. Review widths, branching ratios and event-level readback
when changing parameters. Resolve and qualify the selected model interface rather than
assuming a mass-only edit creates a newly diagonalized spectrum.

- **Interface:** inspect the imported model again for the scanned entries. A mass-only scan of a
  model with independent mixing inputs is not a newly diagonalized spectrum, and inherited widths
  and decays need a separate check where splittings become small.
- **Process:** record the actual channel list a multi-particle alias expands to; an alias can
  include states the request did not ask for. Decide recoil radiation and merging from the
  publication and selection ([the merging checklist](merging.md)).
- **σ:** use `ravel xsec lookup --request request.json` with explicit order, PDF, scale and
  flavour/chirality count; derive any correction from a matched generator denominator.
- **The `run.mg5` card-provisioning idiom:** after `launch <procdir>` and the
  `madspin/shower/reweight=OFF` block, the param-card and run-card **absolute paths are given on
  their own bare lines** (MadGraph's interactive prompt consumes them in order — param card first,
  then run card), followed by `set iseed <N>` then `done`. The bare-path lines are positional, so
  keep the order (param, run) and always use absolute paths (a relative path resolves against the
  procdir, not the run dir, and silently loads the wrong card).
- **VERIFY:** `lhe_check.py` (masses for each point, weight structure) and confirm the shower
  produces the intended final-state objects.

The requested order must match what the analysis states.
A charge-summed basis must be requested explicitly with `charge: "sum"`.
