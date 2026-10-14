# Review record: pythia-shower-cards

Machine review during RAVEL development. It is not a physicist review.

```json
{
  "skill": "pythia-shower-cards",
  "reviewed": "2026-10-11",
  "reviewer": "RAVEL development stream (machine review)",
  "sources": [
    "Pythia 8.3 online manual, https://pythia.org/latest-manual/ (Jet Matching, CKKW-L Merging, SUSY Les Houches Accord, Main-Program Settings)",
    "Bierlich et al., A comprehensive guide to the physics and usage of PYTHIA 8.3, SciPost Phys. Codebases 8 (2022), arXiv:2203.11601",
    "RAVEL src/ravel/physics/pythia_cards.py and model_events.py (check_cards)",
    "RAVEL .claude/rules/madgraph-pythia.md and docs/reference/failure-modes.md C1"
  ],
  "tested_versions": {"pythia8": "8.312 (card syntax; no shower run)", "ravel": "0.4.0"},
  "executable_blocks": ["pythia-card-compare"],
  "illustrative_blocks": [],
  "limits": ["The block compares card text; it does not run Pythia or qualify a shower."]
}
```
