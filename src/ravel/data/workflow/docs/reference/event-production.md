# Shower and detector production

Science mode `event-production` turns parton-level events from any generator and model into
Delphes ROOT files and a `production-receipt.json`. It runs Pythia 8 and Delphes as supervised
chunks through the execution backends, checks every output against its contract before the next
step reads it, and refuses a detector card that would see an invisible particle. The output feeds
`columnar-analysis` directly.

The production runs only through ordinary `ravel plan`, approval and `ravel run`. The command
`ravel event-production check task.json` checks a task without running anything.

## The task

```json
{
  "events": {"lhe": "unweighted_events.lhe.gz", "generation_receipt": "generation-receipt.json"},
  "process": {"description": "p p > n2 x1+"},
  "model": {"name": "MSSM_SLHA2", "slha": "param_card.dat", "produced": [1000023, 1000024],
            "invisible": [1000022], "visible_stable": []},
  "shower": {"seed": 1234,
             "commands": ["Tune:pp = 14", "SLHA:useDecayTable = on"],
             "census_events": 1000},
  "detector": {"cards": [
    {"name": "cms", "card": "delphes_card_CMS.tcl", "fix_invisibles": true,
     "keep_branches": ["Jet", "Electron", "Muon", "Photon", "MissingET"],
     "required_branches": ["Event.Weight", "Jet.PT"]}]},
  "normalization": {"sigma": "lhe-init"},
  "chunks": 8, "parallel": 1, "merge": "list", "retain_hepmc": false,
  "backend": {"kind": "native"},
  "resources": {"cpus_per_chunk": 1, "memory_mib": 4096, "wall_seconds_per_chunk": 7200}
}
```

- `events.lhe` is the generated sample. The LHE banner supplies the generator version, the process
  lines, the imported model and the run card. A declared `model.name` must match the banner.
- `shower.commands` are Pythia 8 settings, one `Key = value` per line, or a `cmnd` file.
  The stage sets the input file, the event range of each chunk and the seeds; a command that sets
  `Beams:LHEF`, `Beams:nSkipLHEFatInit`, `Main:numberOfEvents` or `Random:seed` is refused.
  A `SLHA:file` setting is pinned as an input. Chunk `i` uses seed `seed + i`.
- `shower.variants` are named alternative settings, for example a matching-scale variation. Each
  variant is showered from the same LHE events and reported as its own sample.
- `detector.cards` lists one or more Delphes cards. All cards run on the same showered events.
  `keep_branches` writes a managed copy whose TreeWriter keeps only those branches.
  `overrides` replaces declared module settings, each with a reason.
- `events.generation_receipt` links the sample to its generation. A RAVEL
  `generation-receipt.json` is validated; the parameter point whose LHE file (or transformed LHE
  file) has the input's sha256 is selected, its cards and LHE file are re-hashed, and the
  production receipt records the point, generator, model, process, beams, PDF and cross section
  under `generation`. `events.lhe_transform` names the receipt of a separate `lhe-transform` study
  (`<output>.transform.json`); its original must be the point's LHE file. The settings a transform
  requires (for example `Check:event = off`) must appear in every shower variant, and its deviations
  are copied into the production receipt.
- `normalization.sigma` is `lhe-init` (the sum of XSECUP in the LHE init block), `ledger` (a
  normalization ledger: sigma, k factor, branching fractions and filter efficiency with their
  sources), `registry` (a cross-section `request` looked up in the pinned registry, with an
  optional `process_basis`) or `generation-receipt`. With no other keys, `generation-receipt`
  takes the selected point's cross section and convention; a JSON `pointer` with a declared
  `source` and `convention` reads any other receipt.
- With a ledger, the receipt's `analysis_normalization` names the receipt without a pointer, so
  the columnar analysis engine takes sigma x k as the cross section and the branching fractions
  and filter efficiency as its factor.
- `merge` is `list` (the chunk files, pinned, are the sample) or `hadd` (one file, with its entry
  count and weight sums checked against the chunks).
- `tools` can name `shower`, `shower_merged`, `delphes` and `hadd` programs. By default the
  installed programs from the native toolchain are used; `ravel doctor` reports a missing one.

## Invisible particles and detector cards

`model.invisible` lists the stable states that leave no signal. RAVEL checks the list against the
model:

- with `model.slha` and `model.produced`, every stable BSM state reached by the decay chains of the
  produced states must be declared invisible or listed in `visible_stable`, and no declared
  invisible state can decay in the card;
- with `model.closure_report` (the decay-closure check of a simplified spectrum), every state in
  its invisible census must be declared.

Every card is then checked. Each calorimeter module must deposit zero energy for each invisible
state, explicitly or through its `{0}` default, and each generator-level jet or missing-momentum
module must remove it through a `PdgCodeFilter`. A card that fails is refused. With
`fix_invisibles`, RAVEL writes a derived card that adds the missing entries, records every change
and its reason, and keeps the diff to those lines. The receipt lists the change as a deviation.

During the run, the stable BSM states in the first `census_events` showered events of each chunk
are compared with the declared list. An undeclared state stops the chunk before Delphes runs.

`ravel detector-card check CARD --invisible 1000039` and
`ravel detector-card derive CARD --invisible 1000039 --output new.tcl --record new.json` run the
same checks by hand.

## MLM-merged samples

A sample generated with `ickkw = 1` needs a matching block, and a matching block needs a sample
that was generated with `ickkw = 1`:

```json
"merging": {"scheme": "MLM", "base_partons": 0, "settings": {
  "JetMatching:merge": "on", "JetMatching:scheme": 1, "JetMatching:setMad": "off",
  "JetMatching:qCut": 30, "JetMatching:nJetMax": 2, "JetMatching:nQmatch": 5}}
```

All six settings are required. `qCut` must be at least the generation `xqcut`, `nJetMax` must equal
the largest number of extra partons in the LHE file (counted above `base_partons`), and the LHE
events must be unweighted. The merged shower program counts attempted, accepted and vetoed events
and writes the differential jet rates of each accepted event. The receipt records the cross section
before matching per parton multiplicity, the veto counts, Pythia's own estimate, the DJR histograms
and the matched cross section

    sigma_matched = sigma_LHE x accepted / attempted

pooled over all chunks, with the binomial uncertainty of the fraction. With `normalization.sigma`
`lhe-init`, the receipt's `sigma.value_pb` is the matched cross section. A ledger or a generation
receipt supplies the cross section as declared, and the matched value is kept for comparison.

## Output contracts and the execution gate

Each chunk is one execution-backend stage under the machine lease. With a local backend the chunks
run one at a time, nested in the calling stage's lease; `parallel` applies to remote slots. Inside it:

1. Pythia showers the chunk. The gate accepts the shower only if the program exited 0, the log
   holds no hard-error marker and the HepMC file is complete with the expected event count.
2. The census of stable BSM states runs on the showered events.
3. Delphes runs every card. The gate accepts each output only if it has the expected number of
   entries, the required branches and weights that are finite and not all zero.

After the job, the fetched files are checked again against the same contracts. A chunk whose gate
refuses any step stops the production, and no receipt is written. Marker lists are data in
`src/ravel/data/output_markers.json`; `ravel output-gate check` evaluates any stage's outputs and log.

## The production receipt

`event-production/production-receipt.json` holds:

- `generator`, `shower` and `detector`: names, versions with their source, programs with sha256;
- `cards`: the LHE file, each Delphes card (source and derived, sha256, invisible-state check) and
  the SLHA card;
- `process`, `model` (name, banner import, UFO tree digest, SLHA pin) and `invisible_census`;
- `events`: LHE events, attempted, accepted, detector entries per card and each chunk with its seed;
- `sigma`: `value_pb`, `source` and `convention` (order, tool, PDF, scales, process basis), plus the
  ledger or generation receipt it came from;
- `weights`: the `Event.Weight` sums and the normalization rule
  `yield = sigma x L x (selected weight sum) / (all-event weight sum)`;
- `merging`: `none` or the MLM accounting;
- `outputs`: the Delphes files per card with entries and weight sums;
- `variants`, `deviations`, `disk_preflight` and `analysis_normalization`.

`analysis_normalization` is the block for `columnar-analysis`: add the luminosity and its source
and pass the Delphes files as inputs. The cross section is read from the receipt by pointer
(`/sigma/value_pb`), with the receipt's sha256 recorded in the analysis result.

With `retain_hepmc`, each chunk keeps its gzip HepMC file and an `event-metadata.json` for Rivet.
