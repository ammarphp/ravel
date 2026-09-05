# Checklist — mapyde TOML config

Start from a bundled template (`sleptons.toml` for slepton production, `ewkinos.toml` for
electroweakinos) and change only what the request requires.

## Required (container backend only)
_These apply to the **legacy container backend** (`--backend container`). The native VM-free default
for EwkCompressed2018 uses no mapyde/podman at all (`docs/workflow/reference/native-pipeline.md`)._
| Field | Value |
|---|---|
| `[base] engine` | `"podman"` (container backend only) |

## Physics point & statistics
| Field | Meaning / how to set |
|---|---|
| `[madgraph] params` | name of the SLHA param template (e.g. `"SleptonBino"`) → `<params>.slha` |
| `[madgraph.masses]` | substitutions into the SLHA template, e.g. `MSLEP = 200`, `MN1 = 150` |
| `[madgraph.proc] name` | process card name (e.g. `"isrslep"` = slepton pair + 1 ISR jet) |
| `[madgraph.run] nevents` | event count (start ≤1000 to validate, then scale up) |
| `[madgraph.run] ecms` | √s in GeV (e.g. 13000) |
| `[madgraph.run] seed` | 0 = auto each run; fixed int = reproducible |
| `[madgraph.run.options]` | generation cuts (`ptj`, `ptj1min`, `mmjj`, `xqcut`, `ktdurham`) — keep template values unless the request justifies changes |

## Target analysis (selection + statistical model — keep these consistent!)
| Field | Meaning |
|---|---|
| `[simpleanalysis] name` | the ATLAS SimpleAnalysis selection (e.g. `"EwkCompressed2018"`) |
| `[pyhf] likelihood` | the matching pyhf workspace (e.g. `"Slepton_bkgonly.json"`) |
| `[analysis] kfactor` | NLO/LO k-factor applied to the signal (e.g. 1.18) |
| `[analysis] lumi` | integrated luminosity in pb⁻¹ (e.g. 139000) |

The `name` and `likelihood` MUST belong to the same published analysis. Available bundled
likelihoods: `mapyde --prefix likelihoods` (e.g. Slepton, Higgsino, WinoBino). For an analysis not
bundled, point `[base] likelihoods_path` at a directory containing its HEPData pyhf workspace.

## Switching the whole model/process
- Different SUSY production → choose a different template (`ewkinos.toml`) or set
  `[madgraph.proc] name` to another bundled process card (`mapyde --prefix cards` → `process/`).
- Custom process → add your own process card to a `process_path` directory and reference it.

## Skips (re-using earlier stages)
Each stage block has `skip = true/false`; set `skip = true` to reuse a previous stage's output.
