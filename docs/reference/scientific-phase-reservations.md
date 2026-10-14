# Scientific phase reservations

`ravel.workflow.scientific_phase_allocation.allocate(request)` reserves declared
check costs before construction or polishing. The ordinary AgentHost action
`scientific-phase` takes an explicitly pinned `request_input`; blinded review
roles cannot receive this planning action.

The closed schema-1 request contains `budget`, `usage`, `checks`, `designs`,
`completed_check_ids`, `retained_design_ids` and `mandatory_check_ids`. Resource
vectors have exactly `calls`, `output_tokens`, `wall_seconds` and
`native_attempts`. A design declares construction cost, check IDs and polishing
cost. Shared pending checks reserve once across mandatory and retained designs.

The result identifies overruns, reservation deficits and individually affordable
designs. Affordable rows do not form a jointly feasible batch. Polishing requires
a retained design and all its declared checks completed. Unknown or failed checks
must remain pending; the caller supplies completed IDs and debits actual receipts
before reallocating.

This pure policy executes no work, grants no approval and observes no native
internal call counts. Declared ceilings are not measured costs or cancellation
guarantees. Graph calls and revisions still consume the graph's own budget;
scientific acceptance remains with the ordinary result/review lifecycle.
