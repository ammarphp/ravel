# Review record: madgraph-launch

Machine review during RAVEL development. It is not a physicist review.

```json
{
  "skill": "madgraph-launch",
  "reviewed": "2026-10-11",
  "reviewer": "RAVEL development stream (machine review)",
  "sources": [
    "MadGraph5_aMC@NLO 2.9.27 source: Template/LO/Cards/run_card.dat and madgraph/various/banner.py (RunCardLO defaults, nevents 10000)",
    "MadGraph5_aMC@NLO 2.9.27 source: madgraph/interface/madevent_interface.py and common_run_interface.py (launch questions)",
    "https://launchpad.net/mg5amcnlo",
    "RAVEL src/ravel/physics/model_events.py (check_cards, render_scripts)",
    "RAVEL docs/reference/failure-modes.md section C"
  ],
  "tested_versions": {"madgraph": "2.9.27 (card syntax only; no generation run)", "ravel": "0.4.0"},
  "executable_blocks": ["run-card-keyed-edit", "launch-edit-window"],
  "illustrative_blocks": ["typed-launch-shape"],
  "limits": [
    "The blocks are checked against RAVEL's card checker and rendered scripts, not against a MadGraph run.",
    "MadGraph 3.x launch prompts are not reviewed here."
  ]
}
```
