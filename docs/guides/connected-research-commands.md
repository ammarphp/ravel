# Ordinary connected research commands

`ravel research-cycle` is a fixed command surface over `ravel.workflow.research_cycle`. Input documents use strict JSON, at most 2 MiB. The command takes one bounded descriptor-backed snapshot and parses exactly those consumed bytes. File identity, size and timestamps are checked before and after consumption, including ending leaf and ancestor identity census (device/inode/type/change time). Nested artifact/spec/config pins additionally retain their explicit expected digest through the existing authenticated next-turn reader. Duplicate keys/nonfinite numbers refuse. File pins retain `{path,sha256,size}`. Unknown command wrapper fields refuse. Relative pins inside research records retain the campaign’s original `base_dir`. `create`, `graph`, `import-board`, `continue` and `synthesize` accept an explicit `--base-dir`, defaulting to their request file’s directory. Other command-line path arguments use the ordinary current working directory.

An ordinary concrete route is:

```sh
ravel research-cycle create --cycle campaign --request question.json
ravel research-cycle propose --cycle campaign --request hypotheses.json
ravel research-cycle graph --cycle campaign --request context-graph-request.json
ravel research-cycle design --cycle campaign --request baseline-design.json
ravel research-cycle select --cycle campaign
ravel research-cycle prepare --cycle campaign --experiment baseline --rundir baseline-run
ravel approve --rundir baseline-run --quote '<actual authorized assent>'
ravel research-cycle run --cycle campaign --experiment baseline
ravel research-cycle observe --cycle campaign --experiment baseline
```

`graph` and `run` perform actual dispatch. Their scientific/provider runtime qualification and resource authority must already exist. Supply authenticated assent, launch leases and credentials through their ordinary owners. The numerical runtime, working directory and environment must match the ordinary plan. Run returns the ordinary scientific exit code and never turns an exit into scientific acceptance. An incomplete Graph returns status 1 with its original incomplete result and retained reservations. Request/parsing/admission failures return status 2.

For bounded input refinement use `blueprint-context --out FRESH_DIRECTORY [--parent REVIEWED_EXPERIMENT]`; then the existing blueprint API prepares a complete source recipe and optional finite designer choice. The materializer is an ordinary Host `research-blueprint` tool in a Graph request. `blueprint-admission --graph MATERIALIZER_GRAPH --node compile --request admission-parameters.json` emits the second ordinary Graph specification. Charge/execute that Graph with `graph`, then call `adopt-portfolio --graph ADMISSION_GRAPH --node admit --request portfolio-binding.json`. This reaches the original cycle `select/prepare`; it copies only declared mutable scientific files and exposes unchanged original parent dependencies at both stages. A baseline can use explicitly supplied finite choices without a provider call; attribution stays source-supplied.

Actual scientific role orchestration belongs to the separately reviewed `ravel judgment` connector, existing review contexts and `physics_review`. An attached campaign must use its prepared-Graph ledger join; `graph --prepared` forwards `prepared=True` to that reviewed existing API. All roles remain separately bound to actual current inputs and registered actor identities. `adjudicate --experiment ID` then consumes the genuine scoped decisions. `feedback --experiment ID` emits the actual feedback pin; `adopt-revision --graph GRAPH --node NODE` admits an existing charged improver Graph result, while `source-revision` retains a separately supplied reviewed source proposal without fabricating a model call. Repair acceptance and a newly requested study still use their original ordinary gates.

After a premise changes, `revise-premise` reopens only dependent interpretations/designs and retains all prior outcomes/decisions. `bind-knowledge` freshly verifies scoped citations, contradictions and kernel facts; `knowledge-next` consumes a complete obligation→existing-design mapping including empty lists. Unknown/native-unserved data remain unknown. `continue` delegates to the existing explicit expired-campaign continuation, preserving original cumulative non-wall ceilings/debits and original deadline. The original deadline remains bound. `synthesize` requires current complete requested quantities and real scoped role decisions, and delegates to the current report renderer with all negatives/reopened history.

Every command has `--cycle ROOT`. Commands with `--request JSON` use these exact wrapper fields:

| Command | Request document |
|---|---|
| `create` | Existing research-cycle contract; no extra wrapper |
| `propose` | `{hypotheses, origin}` |
| `design` | Existing complete experiment record; no extra wrapper |
| `graph` | `{graph_root, spec: pin, host_config: pin}`; explicit Host config selects only its named key environment value |
| `import-board` | `{board_root, streams}` |
| `source-revision` | `{proposal_pin, description}` |
| `revise-premise` | `{id, statement, basis, reason}` |
| `configure-phases` | `{request_pin, check_contracts, preconstruction_checks}` |
| `failed-import` | `{id, document_pin, premise_ids, predictions, historical_cost}` |
| `failed-attach --experiment ID` | `{document_pin}`; same observed attempt and prior result pin, no new debit |
| `diagnostic-feedback --experiment ID` | `{feedback_pin}`; control-only reviews must not be enabled by this command |
| `bind-knowledge` | `{request_pin, premise_map, reason}` |
| `knowledge-next` | `{obligation_designs}` |
| `reuse-adaptation` | `{request_pin, entry_id, bindings}` |
| `continue` | `{new_root, contract, reason}` |
| `synthesize` | Existing complete report request; no extra wrapper |
| `blueprint-admission --graph GRAPH --node NODE` | `{graph_id, max_wall_seconds}` |
| `adopt-portfolio --graph GRAPH --node NODE` | `{context_pin}` |

Other commands: `status`, `select`; `prepare --experiment ID --rundir PATH`; `run --experiment ID [--resume]`; `observe/adjudicate/feedback --experiment ID`; `adopt-revision --graph GRAPH --node NODE`; `record-check --check CHECK_ID`; `blueprint-context --out PATH [--parent ID]`.

Explicit vector ceilings, the original campaign clock, authenticated actors and ordinary workflow gates govern each delegated operation. New experiments and scientific acceptance require their applicable admitted actions.

## Literature query expansion and evidence scoring

The literature tools expose query expansion, evidence records and bounded discovery.
Each runs through `python -m ravel.workflow.research_tools <command> --request <file>`, and each is a
host operation of the coordinator.

| Operation | Command | Request fields |
|---|---|---|
| `literature-query-expansion` | `literature-expand` | `{root, query, output_dir, preferences, max_wall_seconds?, limits?, known_tokens?}` |
| `literature-evidence-scoring` | `literature-score` | `{root, rundir, serving_id, question, output_dir, node_id, attempt, preferences, limits?, max_wall_seconds?}` |
| `literature-discovery-crawl` | `literature-crawl` | `{root, scope_pin, output_dir, preferences?, max_advances?, max_wall_seconds?, max_output_tokens?}` |

Expansion returns the deterministic expansion of the curated vocabulary. Evidence records retain the search envelope delivered to the named worker attempt and its serving custody. Each record preserves the original passage, explicit scoring status and any missing-reply reason. Expansion terms, scores and summaries serve as reading aids; scientific claims require their source evidence and review.

The discovery crawl is the bounded selector loop over the charged discovery client. A fresh output
starts its hash-chained ledger and an existing one resumes it after recomputing the ledger, so a
tampered or stale crawl is refused and no charged page is repeated. Each selector call dispatches the
registered selector card; a refused call is declined and stops selection, and an exhausted campaign
halts with a dated lower-bound report. `research_tools.admit_crawl` accepts only an ended crawl whose
report recomputes; a single discovery query is not a crawl.
