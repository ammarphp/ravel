# Reusable interfaces

## Constructive continuation

```python
from ravel.workflow import research_cycle, research_followup

turn = research_followup.run_ideation(
    cycle_root, parent_experiment_id, fresh_turn_directory,
    host=explicit_existing_agent_host,
    model=declared_model, reasoning_effort=declared_effort,
    max_output_tokens=per_turn_cap, max_wall_seconds=per_turn_wall,
    citation_sources=exact_content_pins, speculative_sources=[],
)
if turn["complete"]:
    context_pin = research_followup.prepare_design_context(
        cycle_root, parent_experiment_id, turn["bindings"], fresh_designer_directory,
    )
```

This function really dispatches if called with a live Host. It is not a source-only checker. A fresh root execution admission, compatible provider/runtime and exact cumulative budget are prerequisites. Each stream is one normal model node. `prepare_ideation` and `ideation_spec` are separately usable preparation APIs and make no model calls. `adopt_ideas` verifies the actual charged Graph, exact presented context/instructions/schema, source-scoped attributions and hypothesis stream before using the original `research_cycle.propose` journal operation.

The returned `bindings` are a dictionary keyed by `citation_led` and `speculative`, each with `{graph_root,node_id,context_pin}`. Content pins have exactly `{path,sha256,size}`. They bind the actual consumed bytes, not a later path hash.

An explicit designer model or deterministic source producer supplies:

```json
{
  "kind": "research_portfolio",
  "parent_experiment": "original-parent-id",
  "context_sha256": "exact-design-context-file-hash",
  "reason": "Why these competing interventions discriminate the retained rivals",
  "experiments": ["ordinary research_cycle experiment objects; not strings"]
}
```

Before either Host delivery or final adoption, the context must contain exactly one citation-led stream and one speculative stream. Each literal hypothesis row is checked against its genuine original model result and the currently adopted cycle content. Deleting, duplicating or rewriting rows cannot narrow the rival denominator, even with a truthful new context file hash.

The designer result must be a completed charged Graph node with role `designer`. A normal AgentHost tool node may use action `research-portfolio` and parameters `{proposal_input,context_input}`, naming explicitly bound normal input IDs. Its complete inputs include the context, canonical feedback, proposed study specifications and every consumed study input. The model route uses the same `bound_portfolio` admission; `adopt_portfolio(cycle_root, graph_root, node_id=..., context_pin=...)` then performs one atomic existing cycle commit.

`research_cycle.select`, phase allocation/check reservation, `prepare_experiment`, ordinary CI1 approval, `run_experiment`, `observe`, actual role decisions, `adjudicate`, knowledge export/retrieval and `synthesize` remain the execution and delivery path. Parent task completion is not inferred from admitting or selecting one rival.

## Original AgentRivet module binding

```python
from ravel.workflow import agentrivet_runtime
from ravel.workflow.agentrivet_provider import GraphLLM

llm = GraphLLM(
    fresh_graph_root, model=declared_model, reasoning_effort=declared_effort,
    max_calls=10, max_output_tokens=4096, max_wall_seconds=1800,
    dispatcher=explicit_admitted_dispatcher,
    dispatcher_pin=exact_dispatcher_source_pin,
    source_inputs=[*core_and_four_role_pins, original_memory_source_pin, *other_admitted_inputs],
)
loop, binding = agentrivet_runtime.instantiate(
    explicitly_loaded_original_core, all_four_loaded_role_modules, llm,
    source_pins={"core": core_pin, **four_role_pin_map},
    provider=declared_provider, model=declared_model, max_iterations=3,
)
# Under a separate exact root model-call admission, invoke the ORIGINAL loop:
# loop.run(explicit_original_memory_with_complete_paper_and_HEPData_inputs)
# Then verify and prepare the ordinary source input:
# prepared = agentrivet_runtime.prepare_source_study(...)
```

The role keys are `analyst`, `coder`, `code_reviewer`, `physics_reviewer`. Source pins use `{path,sha256}` and must identify the exact external `.py` files already bound as normal Graph provider inputs. `inspect_binding` and `instantiate` do not call a provider. `instantiate` supports one to three original revision rounds and requires the full worst-case ceiling `1 + 3 * max_iterations`, not a forecast assuming early approval. The provider object must be the concrete GraphLLM, not an overriding subclass.

`generation_outputs(llm)` verifies complete fresh Analyst/coder/reviewer triplets and returns the actual reserved-call/request/message/result/transport census. It is read-only. Unknown external inference usage remains unknown; reservations are not observed provider token usage.

`prepare_source_study(core,roles,llm,memory_module,memory,source_pins=...,memory_pin=...,routine=...,assets=...,output_dir=...,review_policy=...,approval_mode=...)` reads and checks that history against original Memory, preserves raw outputs, and calls the existing source-study preparer. Assets have the existing agentrivet_candidate asset shape; no synthetic default asset is added. `memory_pin` must have been a normal Graph input before generation. Source output paths must be fresh. Original upstream accepted markers are preserved as producer metadata and carry no ordinary acceptance.

Actual loading/imports, Pydantic, SDKs, provider availability, context capacity, credential selection, process containment, native compilation and supplied-event execution are caller/root qualification obligations. No implicit installation, credential discovery, provider call, loop execution, arbitrary code runner, approval or retry is implemented by this module.
