# Revealed hypothesis board → constructive discussion → ordinary experiment

`ravel.workflow.research_board_discussion` connects the existing hypothesis board,
AgentGraph/Host and research cycle. It introduces no second scheduler, budget,
journal, scientific reviewer or execution approval. It is an implementation of
RES-MEETING; useful scientific reasoning and superiority over isolated revision
remain empirical questions.

The input is an existing research cycle with its original question, requested
quantities, premises and complete experiment/failure history, and a board after
**every** initial commitment and reveal. Import the whole board with the ordinary
`research-cycle import-board` operation. Complete populations up to the existing
64-hypothesis total are validated in 16-row batches before one state publication.
Cycle IDs bind the charter digest, original actor/name and complete hypothesis
source digest; the report retains the inverse map and original categorical
predictions, explicit contradictions, artifact references and unknowns. Reimport,
collisions, an invalid later batch or excess total capacity refuse without partial
state or board-proposal publication. No identity syntax rule is loosened.

## Prepare the two arms

Use `prepare(cycle_root, board_root, fresh_output_dir, **options)` for either
`arm="discussion"` or `arm="isolated"`. The destination must be disjoint from the
original cycle and board. Options are:

- `participant_order`: exactly every charter actor, once, between one and eight.
- `designer`: `{actor_id, session_id, model_id}`.
- `final_reviewers`: two prospective `{actor_id, session_id, model_id}` rows for
  the eventual independent critic and verifier. All participant/designer/final
  actor and session IDs must differ. These are declarations, not proof of fresh
  processes, independent reasoning or authenticated identities.
- `observations`: one `{id, pin, missing_reason}` for **every** charter artifact.
  A present `pin={path,sha256,size}` must authenticate the original full bytes;
  `missing_reason` is null. Only declared-digest artifacts may have `pin=null`
  with an explicit missing reason. Frozen evidence cannot be dropped. Complete
  bytes are presented as base64 alongside the pin; no semantic summary replaces
  them.
- `candidates`: zero to eight complete existing research-cycle experiment
  declarations (within the remaining cycle capacity). Every current hypothesis
  has a declared prediction or JSON null. Ordinary specification, input closure,
  original goal binding, review policy and acceptance scope remain unchanged.
  An existing `input_exposure` classification preserves every execution pin but
  presents only the source inputs marked `model_context`, plus the full exposure
  inventory. A withheld input exposed by another candidate or common observation
  refuses before dispatch. These are byte/pin presentation checks, not proof that
  a shared context contains no semantic hint. With no supplied executable study, the designer can propose a located
  acquisition or a prospective experiment; the API does not invent its inputs.
- `max_output_tokens` (16–32000), `max_wall_seconds` (1–3600),
  `reasoning_effort`, and `adapter="responses"|"command"`: explicit common
  per-turn ceilings and the existing Host transport.

Prepare both arms from the same declared board/scientific context, order, model
population, per-turn ceilings and prospective study inputs, using independently
created ordinary cycles/roots when needed. The matched declared reservation is
`N+1` calls, `(N+1)*tokens`, `(N+1)*wall_seconds`, and zero native attempts.
Preparation dispatches nothing. The API labels this comparison as **matched
ceilings**, not measured equal cost, a randomized trial, experimental blinding
or evidence of efficacy. Actual per-turn usage, failures and unused reservations
are retained for later comparison. Conducting such a study requires separate
admission and genuine independent evaluation.

## Execute one bounded sequence

`run(cycle_root, preparation_pin, host=host)` is an actual model-call entry. It
reserves the **complete participant plus designer sequence** in the original
cycle ledger before the first call. It then uses unchanged
`cycle.execute_graph(..., prepared=True)` with one ordinary model node per turn,
one worker, one attempt and no reworks. No automatic retry, extra round or new
allowance follows a failure.

In the discussion arm each participant sees every original/current hypothesis
and each preceding checked turn. In the isolated arm each participant sees only
its own initial hypotheses and no other participant's revisions. Both arms see
the same original question, premises, common source observations and retained
prior experiment observations. The final designer sees all initial hypotheses
and all completed revisions in both arms. This is an API disclosure boundary;
source artifacts, common context and access outside this API can disclose ideas.
It provides no OS isolation or proof of experimental blinding. This operation
never creates final critic/verifier contexts or submits their votes.

Each returned turn must retain its entire visible hypothesis census. Edges are
`{kind, hypothesis_ids, statement, source_basis}` with kind `contradiction` or
`missing_premise`. Proposals are
`{kind, question, hypothesis_ids, missing_inputs, expected_outcomes, source_basis}`
with kind `acquisition` or `experiment`; each expected outcome is
`{label,prediction:string|null}`. Source basis pins must name the full observations
actually presented. An edge is an attributed review judgment, not an automated
proof that either hypothesis is false. Unknown predictions and missing premises
remain explicit. Only the designer may select an exact supplied candidate ID.

The report retains the original board and every minority explanation, inverse
mapping, whole task, full prior experiment history, original observations,
contexts, raw response/Host receipts, checked judgments, actual Graph usage and
all reservations, including turns never started. A malformed response, failed
transport or freshness refusal stops the sequence and produces an incomplete
report; Graph/Host call history and completed raw responses remain on disk.
If a damaged original cycle cannot itself be read or a process terminates before
report delivery, those original receipts remain the recovery evidence; the API
cannot guarantee a final report across arbitrary storage/process failure.
Artifacts are complete, immutable, at most 2 MiB each; an oversized context/report
refuses without truncating the population. Existing Host input limits also apply.

## Adopt a proposal and continue the original task

`adopt(cycle_root, report_pin)` replays the actual charged Graph origins, exact
contexts and full report, checks ending source/preparation/report commitments,
and refuses incomplete reports or changed evidence. If the designer selects a
supplied candidate, its complete inputs must have been ordinary designer Host
inputs. Adoption adds that prospective design through the existing cycle commit;
it carries no old votes and clears no scientific review. Distinct declared
prediction labels are prospective contrast metadata, not measured resolving
power. Selection and the ordinary science plan, CHECK-IN 1, execution, critique,
verification and final decision still follow the existing workflow. The original
parent obligations and acceptance domains remain open.

If no candidate is selected, `adopt` returns the complete acquisition/experiment
proposal and leaves the scientific experiment population unchanged. Use the
existing source/premise revision and design/blueprint operations after obtaining
the specified evidence. Missing inputs do not become refuted hypotheses or a
narrowed parent question.

## Ordinary CLI

Each command accepts strict JSON through `--request`, using the existing bounded
research request parser:

```text
ravel research-cycle import-board --cycle CYCLE --request IMPORT.json
ravel research-cycle discussion-prepare --cycle CYCLE --request PREPARE.json
ravel research-cycle discussion-run --cycle CYCLE --request RUN.json
ravel research-cycle discussion-adopt --cycle CYCLE --request ADOPT.json
ravel research-cycle select --cycle CYCLE
ravel research-cycle prepare --cycle CYCLE --experiment ID --rundir FRESH_RUN
```

`IMPORT.json` has `board_root` and complete `streams` (actor → citation_led or
speculative). `PREPARE.json` has `board_root`, `output_dir` and all options listed
above; paths resolve relative to the request file. `RUN.json` is
`{"preparation_pin": {"path": "...", "sha256": "...", "size": 123}}`;
`ADOPT.json` is `{"report_pin": {"path": "...", "sha256": "...", "size": 123}}`.
Pin paths resolve from the original cycle's declared base. `discussion-run` invokes
ordinary Host model transport; the other discussion commands perform metadata
preparation or prospective adoption. No command approves or runs a scientific
study, and no designer consensus becomes an ordinary review decision.

See [connected research cycle](connected-research-cycle.md) and the
[hypothesis board source](../../src/ravel/workflow/hypothesis_board.py).
