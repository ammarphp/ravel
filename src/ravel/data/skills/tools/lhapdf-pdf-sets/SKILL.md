---
name: lhapdf-pdf-sets
description: Use when choosing or checking an LHAPDF parton-density set for event generation or PDF variations - LHAID, members and error type, which partons a set carries, lepton and photon content of the proton such as LUXlep, and the MadGraph beam settings (lpp, pdlabel, lhaid) that go with it.
license: Apache-2.0
compatibility: LHAPDF 6.5.6 data sets in RAVEL's shared LHAPDF data directory; MadGraph5_aMC@NLO 2.9.27, and 3.7.0 for lepton and photon partons where the toolchain installs it.
allowed-tools: Bash Read
metadata:
  ravel-requires-modes: "model-events pdf-variations"
  upstream-version: "madgraph:madgraph=2.9.27 madgraph:lhapdf=6.5.6 madgraph:mg5amcnlo=3.7.0"
  ravel-version-unpinned: "madgraph:lhapdf=6.5.6 madgraph:mg5amcnlo=3.7.0"
  ravel-parameters: "model-events.generation.beam_type model-events.generation.beam_pdg model-events.runtime.options.lhapdf model-events.generation.scale_pdf"
  last-reviewed: "2026-10-11"
---

# LHAPDF sets

## Read the set before using it

Every LHAPDF set has an `.info` file. Its `SetIndex` is the LHAID of member 0,
`NumMembers` and `ErrorType` (`replicas`, `hessian`, `symmhessian`) define how
an uncertainty is formed, and `Flavors` lists the partons the set provides.
A process can only draw initial-state partons that appear in `Flavors`.

```python ravel-block=pdf-info-flavours
import yaml

LEPTONS_AND_PHOTON = {22, 11, -11, 13, -13, 15, -15}

def pdf_set_summary(info_text):
    """LHAID, members, error type and non-QCD partons from an LHAPDF .info text."""
    info = yaml.safe_load(info_text)
    flavours = [int(f) for f in info["Flavors"]]
    return {"lhaid": int(info["SetIndex"]), "members": int(info["NumMembers"]),
            "error_type": info["ErrorType"], "flavours": flavours,
            "leptons_and_photon": sorted(set(flavours) & LEPTONS_AND_PHOTON)}
```

LUXlep-NNPDF31_nlo_as_0118_luxqed (LHAID 82400, `DataVersion: 2`, 101
replica members) lists the photon (22) and the charged leptons (±11, ±13, ±15)
besides quarks and the gluon. Its `.info` cites arXiv:2005.06477 for the
lepton content.

## Beam settings in MadGraph

- MadGraph 2.9.27 run card: `lpp` 0 = no PDF, 1 = proton, -1 = antiproton,
  2 = photon from proton, 3 = photon from electron, 4 = photon from muon.
- MadGraph 3.7.0 run card: 0 = no PDF, ±1 = proton/antiproton, 2 = elastic
  photon of a proton or ion beam, ±3 = PDF of an electron/positron beam,
  ±4 = PDF of a muon/antimuon beam.
- `pdlabel = lhapdf` with `lhaid = <SetIndex>` selects an LHAPDF set.
- When a process has a lepton and a quark or gluon in the initial state,
  MadGraph 2.9.27 writes a default card with the lepton leg as a beam without
  PDF (`lpp = 0`, `ebeam = 1k`; `RunCardLO.create_default_for_process`). For
  leptons taken from the proton, both beams must be protons: check `lpp1` and
  `lpp2` in the card MadGraph wrote.

```python ravel-block=beam-readback
from ravel.physics import model_events

def beam_mismatch(run_card_text, expected_lpp):
    """[(key, card value, expected)] where the card's beam types differ."""
    rows = model_events.assignments(run_card_text)
    found = []
    for key, value in zip(("lpp1", "lpp2"), expected_lpp):
        actual = model_events.literal(rows.get(key, "missing"))
        if actual != value:
            found.append((key, rows.get(key), value))
    return found
```

## In RAVEL

`model-events` declares `model-events.generation.beam_type`,
`model-events.generation.beam_pdg` and the LHAPDF tool path
(`model-events.runtime.options.lhapdf`), and `check_cards` reads the beam
types back from the run card. In this release model-events admits beam types
-1, 0 and 1 on the pinned MadGraph 2.9.27 tree. `pdf-variations` reweights
supplied parton records with NNPDF30_nlo_as_0118 and admits quark and gluon
partons only; see `docs/workflow/reference/pdf-variations.md`.

## Pitfalls

- A run card whose beam types differ from the plan (for example the default
  `lpp2 = 0` for a lepton-quark process) generates the wrong collision and
  exits 0. Caught by `ravel.physics.model_events.check_cards`.
- A parton record with a flavour the reweighting set does not carry. Caught by
  `ravel.physics.pdf_variations.validate_records`.
- Advisory: lepton and photon partons of the proton need a set that lists them
  in `Flavors` and, in RAVEL's toolchain, MadGraph 3.7.0; model-events on
  MadGraph 2.9.27 does not run them in this release.
- Advisory: MadGraph's built-in `pdlabel` sets (for example `nn23lo1`) are
  read from MadGraph's own tables, not through LHAPDF; record which route ran.
- Advisory: replicas and Hessian sets combine members differently; read
  `ErrorType` before forming an uncertainty (LHAPDF 6 manual,
  https://lhapdf.hepforge.org/).

More: `references/review.md`.
