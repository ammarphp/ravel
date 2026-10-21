# Reviewed SFitter phase continuation

This private operation connects the source conductor to the existing domain review and ordinary review journal. It prepares the next lead context after the exact current phase passes review; it never starts a model, production job or fit. The original manual-card intake remains a separate route.

```sh
python -m ravel.workflow.sfitter_phase_continuation \
  --adoption /absolute/phase/adoption-receipt.json \
  --domain-request /absolute/review/request.json \
  --rundir /absolute/original-reviewed-run \
  --output /absolute/fresh-next-phase
```

The request must consume the exact adopted workflow and handoff. All three originally registered roles must have accepted the exact domain request and complete current domain report, in its registered claim scope. Every concern owned by the current or an earlier phase must be explicitly material and passing. A narrow traceability acceptance can still be useful evidence, but it must not advance a whole extraction phase. Unresolved future-phase warnings remain in the output receipt.

The implementation invokes the ordinary live reuse gate, preserves its cycle and role event identities, and rechecks it at the end. The next workflow's sources retain the prior request, adoption and original journal/snapshot pins. A later hold or journal change invalidates these old commitments at the next fresh source boundary. It neither copies old votes into a new review nor changes correction resources. The current caller must satisfy the original run's ordinary source/runtime guards; no old package is dynamically imported or exempted.

The output is exactly `workflow.json`, `<output>/next-phase-context/context.json` and `continuation-receipt.json`. Exact bounded input bytes are retained, written bytes are checked against known serialized values, every lexical ancestor and output member is rechecked, and late input/receipt/context/member changes refuse. These are finite filesystem observations, not an OS sandbox or an atomic guarantee against arbitrary concurrent mutation.
