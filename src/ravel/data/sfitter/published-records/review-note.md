# Published SFitter card records: provenance note

Evidence file pinned by every record in this directory.

These records translate the source repairs, defect holds and evaluator conventions
that the 2026-10-10 development line encoded in Python
(`sfitter_card_derivation.py`, `sfitter_higgs_support.py`) into the reviewed-source
record schemas (`repair-manifest`, `defect-registry`). Each record binds the exact
bytes of the SFitterAgents source it relies on (commit
`6072a79e0f132d61a927f11ed482a401b34f6e3f`, MIT licence, see
`../LICENSE.upstream.txt` and `../upstream-source.json`); a different byte stream
is refused, never adapted.

What is mechanical and what is not:

- The transformations (earlier-card measurement restoration for the mispaired
  single-top helicity row, the documented dropped-`D` token, projection of the two
  exact duplicate `D6qt1xD6qt1` terms to the released reader's last value,
  coalescence of the one byte-identical Higgs measurement/prediction pair) reproduce
  the earlier code's output exactly. Each one is an input correction that keeps a
  full lineage, not a physics statement.
- The held Higgs response (original row 197, ID 5019) and the unresolved intents of
  the two Top terms are recorded as unresolved. Nothing here resolves them, and a
  record that clears one needs authenticated external evidence.
- The evaluator conventions (ttH production ratio fixed to one, SM production
  scaling table, unused measurement nuisance retained in the roster) are literal
  readings of the pinned evaluator source with line locators. They are not
  validation of the physics.
- The review is a software translation. A physicist review of each correction is
  still required; the `reviewer` field says so.
