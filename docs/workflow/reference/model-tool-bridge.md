# Dynamic model tool checks

`model-tool-bridge` prepares a source-bound study of a supplied full UFO model,
an explicit parameter card, and a small collection of tree two-to-two processes.
It uses the qualified MG5 2.9.27 Python API and the scientific-study approval,
supervision, and independent-review workflow. No events are generated.

The typed process document declares PDG numbers, coupling orders, forbidden
intermediate particles, deterministic seeds, and the centre-of-mass energy:

```json
{
  "processes": [
    {"id": "ee_to_top_pair", "initial_pdgs": [-11, 11],
     "final_pdgs": [6, -6], "orders": {"QED": 2, "QCD": 0},
     "forbidden_pdgs": []},
    {"id": "gg_to_top_pair", "initial_pdgs": [21, 21],
     "final_pdgs": [6, -6], "orders": {"QCD": 2, "QED": 0},
     "forbidden_pdgs": []}
  ],
  "seeds": [19, 101],
  "energy_gev": 1000.0
}
```

Prepare a fresh study through the public route:

```bash
ravel model-tool-bridge plan \
  --madgraph /absolute/path/to/mg5amcnlo \
  --python /absolute/path/to/qualified/python \
  --ufo /absolute/path/to/full/ufo \
  --parameter-card /absolute/path/to/param_card.dat \
  --processes /absolute/path/to/processes.json \
  --source 'Attribution and requested point for this supplied model' \
  --trust-ufo-python \
  --rundir /absolute/path/to/fresh-study \
  --review-policy /absolute/path/to/prospective-review-policy.json
```

UFO Python is executable source. Intake records the complete model and MG5 source
censuses, the selected Python executable and its finite installed source and
dependency census, and the exact supplied card.
After actual CHECK-IN 1 approval, execution copies model and tool sources to a
fresh workspace of its own. It disables implicit UFO restrictions and rejects card
addresses missing from, or ignored by, the full native model. A card named
`restrict_default.dat` can serve as explicit parameter values, but its filename
does not authorize restriction of the supplied UFO.

Native checks rebuild each declared process under particle permutations and
Lorentz transformations. Every evaluator records its effective parameters and
couplings and its actual momenta and external-particle masses. The separate
witness checks the consumed card, a common model point across every process and
seed, finite nonzero matrix elements, recomputed numerical agreement, on-shell
conditions, momentum conservation, and the requested invariant energy. It also
checks the actual imported-source census against approved bytes. Resource
receipts record the owned native process, elapsed time, sampled process-group
memory, thread limits and cleanup.

This operation distinguishes three questions. Card parsing and observed
kinematics check syntax and a sampled phase-space point. Native permutation and
Lorentz checks test numerical consistency of the supplied UFO in the sampled
tree processes. Derivation of the UFO from a Lagrangian, independent amplitudes,
widths, ultraviolet consistency, generator integration, showering and detector
response require their own evidence. A passed bridge witness does not establish
those broader claims. Host operating-system libraries also remain outside the
finite Python source capsule.

The current API accepts one to four explicit two-to-two tree processes and two
to eight unique seeds. It refuses free-form generation commands, multiparticle
aliases, implicit or `Auto` widths, duplicate card addresses, scale-dependent
blocks, decay tables, and vacuous zero-amplitude checks. Unverified or failed
native attempts retain their outputs for review. Implementation and synthetic
guard tests are distinct from an executed native acceptance study.

Native API probes retain `native-case-observations.json` before the first case and after each returned permutation and Lorentz phase. An unresolved or failed numerical guard retains the exact return types, tagged nonfinite values, evaluator traces and completed case phases. The `completed` field means all requested native-worker cases returned and the payload was written; it grants no numerical or model validity. Existing nonvacuity and numerical gates remain unchanged.
