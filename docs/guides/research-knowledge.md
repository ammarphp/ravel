# Knowledge-directed research in the ordinary cycle

This extends `ravel.workflow.research_cycle` using its existing executor and knowledge storage. The shared `physics_knowledge` kernel assembles located source assertions, dependencies, conflicting assertions, domain/convention metadata and proposed test obligations. Its named pure checks establish supplied algebra only.

Use the existing deterministic `physics-knowledge` Host action for graph retrieval. Bind its complete request/source input inventory, retain the actual graph result and cumulative call debit, and keep any model inputs or protected assessment inputs explicitly classified. The consumer can call the same kernel API directly, without a provider call.

For an already-created ordinary research cycle:

```python
from ravel.workflow import research_cycle

# request_pin is an exact ordinary {path, sha256, size} JSON pin.
# premise_map represents every selected kernel premise; IDs do not collapse.
research_cycle.bind_knowledge(
    cycle_dir, request_pin,
    premise_map={"ordered-beam-flux": "beam-convention"},
    reason="Bind the located source and its explicit applicability domain.",
)

# First propose hypotheses and complete prospective designs through the existing
# propose/design or constructive revision APIs. A mapped design explicitly binds
# every imported premise context. Empty lists expose obligations without a test.
selection = research_cycle.knowledge_next(
    cycle_dir, obligation_designs={"compare-ordered-flux": ["beam-contrast"]}
)
```

The literal mapping above is illustrative, not a supplied physics study or a promise that those IDs occur in a catalogue. Both APIs use the exact IDs of the selected packet and current cycle. The complete packet and dependency pins stay in immutable research history. The source assertion's literal text remains unchanged; request/packet context hashes participate in premise freshness. Conflicts are retained as source assertions, not assumed simultaneously true.

An immutable source/request successor conservatively reopens affected experiments and their descendants. Old measurements and decisions remain in old history. Editing an old pinned source refuses admission. Manually revising an imported premise makes knowledge-directed selection require explicit rebinding; it must not silently restore an earlier assertion. Old studies still need the ordinary current accepted-evidence/reuse guards.

`knowledge_next` retains the ordinary selection's source, premise, parent-review, resource, checking-reservation and lifecycle filters. Periodic exploration remains reserved. Among eligible designs it prioritizes declared coverage of unresolved source conflicts, then proposed obligation coverage, prediction separation and smaller declared cost. This transparent heuristic ranks declared designs. Posterior probabilities, calibrated information gain and improvement claims require their own measured scientific evidence. A proposed study-to-obligation mapping requires scientific assessment before it earns resolution credit.

Actual current observations retain matching, differing and unknown predictions separately, with their original scope. A differing scoped prediction does not delete or globally refute a hypothesis; unknowns and adapter failures do not count as support or contradiction. Reopened results are separated from current evidence. The returned constructive follow-up can guide the existing `feedback_packet` and improver→verifier route to a new competing hypothesis or discriminating design. Launch, retry, review votes, physical input changes and scientific acceptance retain their ordinary admission requirements.

The supplied portable controls establish composition and adverse source/resource behavior. They use synthetic documents/designs and explicitly mocked observation/review state where indicated. Native physics, independent agent judgment, scientific utility and comparative advantage require separately executed, matched scientific evaluations.
