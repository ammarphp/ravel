# Ordinary study blueprints

`ravel.workflow.research_blueprint` turns declared interventions into actual fresh scientific input files and study specifications. It composes the existing AgentGraph, AgentHost, research_cycle, science and role-review APIs. It owns no second journal, scheduler, goal store, acceptance policy or process runner.

A source recipe contains exactly:

```python
{
    "schema_version": 1,
    "context": exact_context_pin,
    "study_template": exact_existing_v2_specification_pin,
    "files": [{"id": "records", "path": "inputs/records.jsonl",
               "format": "jsonl", "source": exact_original_input_pin}],
    "bindings": [{"document": "study", "pointer": "/task/records", "file": "records"}],
    "variables": [{"id": "group", "file": "records", "pointer": "/0/group_id",
                   "schema": {"type": "string", "enum": ["separate", "shared"]},
                   "meaning": "Explicit supplied grouping; native event acquisition is unqualified.",
                   "premise_ids": ["pairing"]}],
    "experiment_template": {
        "question": "Complete prospective question", "premise_ids": ["pairing"],
        "cost": {"calls": 0, "output_tokens": 0, "wall_seconds": 30, "native_attempts": 1},
        "observable": {"pointer": "/quantities/covariance/0/0", "outcomes": {"first": 5, "second": 1}},
        "context_outputs": {"measurement": "outputs/attempt-1/result.json"},
        "acceptance_scope": "the_template_policy_scope", "exploratory": True
    }
}
```

This abbreviated inventory is a shape example: a quantities study also needs its actual contract input and binding. `inputs(request, base_dir=...)` verifies the COMPLETE mutable scientific inventory plus the original immutable `goal_binding` dependency pins returned by existing `task_completion.binding_projection`. Parent dependencies are authenticated and exposed as normal Graph inputs at their original paths; they must not appear in the copied `files` inventory. Omissions and undeclared transitive scientific dependencies refuse. There is no source inference, implicit asset download or heuristic path rewriting.

Content pins are `{path, sha256, size}`. Formats are JSON, JSONL or byte-preserved literal. Every JSON/JSONL slot already exists and must satisfy the original finite scalar schema. No root/structural replacement is allowed. Pointer list indices use ASCII grammar. Literal files cannot be edited by a choice. Reference bindings must match the exact original referenced dependency, and only `/task/...` references may be rebound in the top-level study. Variable and reference paths cannot overlap.

The compiler preserves the specification's original goal_binding, source, policy, attempts, ceiling, output policy and baseline assumptions. It never copies, alters or grants authority for the original parent contract/closure/assignment. The generated dependency closure equals fresh scientific inputs union unchanged original parent dependencies. It appends the literal declared input interventions to assumptions. Structured files receive a fresh deterministic serialization identity; literal files are copied exactly. Domain validation remains the existing adapter's responsibility. A scalar string is not automatically a physically meaningful parameter; the recipe must supply an appropriate domain/schema, and the compiler never imports or executes that string. New Python adapters, arbitrary code execution, numerical truth and native ABI are not qualified here.

## Connected entry paths

For a concrete baseline or screen, prepare a context from already adopted hypotheses:

```python
context_pin = research_blueprint.prepare_context(cycle_root, fresh_context_dir, parent=None)
```

A parent may be supplied for refinement after an actual ordinary review or canonical failed-stage diagnostic. Its original full criticism is presented with historical/fresh provenance intact. All currently applicable rivals remain in the context. No citation-led or speculative generation is required. Existing hypotheses may have been supplied or generated; no hypothesis is invented by this helper. The optional explicitly selected two-stream `research_followup.prepare_design_context` is also accepted, with its stricter complete-origin census unchanged.

An ordinary designer can choose finite values through:

```python
spec = research_blueprint.choice_spec(
    blueprint_pin, base_dir=base, graph_id="choose", model=explicit_model,
    reasoning_effort=explicit_effort, max_output_tokens=declared_cap,
    max_wall_seconds=declared_ceiling, adapter="responses",  # or existing command adapter
)
research_cycle.execute_graph(cycle_root, designer_graph, spec, admitted_host)
choice_binding = research_blueprint.prepare_choice(
    cycle_root, designer_graph, node_id="choose", request_pin=blueprint_pin,
    base_dir=base, output_dir=fresh_choice_directory_inside_cycle,
)
```

`choice_spec` binds complete original input/context content as normal Graph inputs. Its schema covers every declared scalar assignment and every current rival, permitting explicit unknown predictions. `prepare_choice` freshly verifies the original charged model Graph, exact instructions/schema/inputs and complete actual result before writing the choice and its original provenance. It makes no model call. Supplied deterministic choice files are also allowed and must not be described as generated by a model.

The choice has `{kind:'research_blueprint_choice', blueprint_sha256, context_sha256, reason, variants}`; each variant has `{id, change, assignments, predictions}`. Every assignment is required, unlisted fields refuse, and ids must be distinct.

The actual compiler is one designer tool with action `research-blueprint`, max_attempts 1 and parameters `{request_input, choice_input, output_dir}`. Normal inputs include blueprint, choice and every `inputs(...)` pin. The destination must be fresh and inside this cycle. Call through `research_cycle.execute_graph` so tool cost and elapsed coordination are retained. `materialize(...)` is the deterministic API behind that tool and does not plan, approve or run.

Its result names actual output pins and portfolio, and explicitly authorizes none of planning/execution/acceptance. Use:

```python
admission = research_blueprint.admission_spec(
    cycle_root, materialization_graph, node_id="compile",
    graph_id="admit", max_wall_seconds=declared_tool_ceiling,
)
research_cycle.execute_graph(cycle_root, admission_graph, admission, admitted_host)
research_blueprint.adopt_portfolio(cycle_root, admission_graph, node_id="admit", context_pin=result["context"])
selected = research_cycle.select(cycle_root)
research_cycle.prepare_experiment(cycle_root, selected["selected"], fresh_run_directory)
```

The second normal tool receives every NEW specification/input file; it does not pretend their bytes were already presented to the earlier model. Adoption validates the complete portfolio before one existing cycle commit. No old vote carries. Phase reservations and lifecycle prerequisites govern existing selection and dispatch. `science.approve`, `research_cycle.run_experiment/observe/adjudicate`, actual critic/improver/skeptic/decider evidence, scoped knowledge and `synthesize` remain unchanged. An expensive new adapter still needs its actual low-cost lifecycle qualification.

Limits: 32 original inputs, 64 primitive variables, 128 explicit references, 8 competing variants, 2 MiB per consumed document and 16 MiB aggregate source/choice snapshots and aggregate new study/input population. These are content limits, not a measured total-I/O or synchronous cancellation guarantee. No cross-call content cache exists. Current source, feedback, premise, rival and output drift refuses. Failure after writing retains partial files and a failed Graph; no successful materialization or scientific hypothesis result is fabricated.

Before successful return, every originally emitted input/specification/portfolio pin and the initially written materialization commitment is freshly authenticated. Changed bytes refuse with failed partial outputs retained; no changed file is recaptured into the commitment.
