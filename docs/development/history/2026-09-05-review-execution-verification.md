# Independent post-repair execution/native verification

Verified working tree descending from `8d8b4b53b358c9798ae9b0d6345919c907b8639e`. Exact source hashes below identify the tested implementation, including uncommitted changes. No source edits or HEP generation were performed during this verification.

Completed 2026-09-05T18:36:33.026907+00:00. Eight independently executed probe groups cover the six original findings. Every group passed its adversarial and positive assertions.

## Dispositions

| Original finding | Disposition | Independent observed result |
|---|---|---|
| F1: success with live descendants | Resolved in tested process-group scope | Normal process exits zero. Escaping child in the owned group instead gives rc=3 and a failed receipt; no late write occurs. A retry succeeds and retains prior output. Separate dead-leader recovery preserves interrupted/succeeded records and kills the remaining writer. |
| F2: log ownership bypass | Resolved | Scientific output, workflow/approval/control paths, another stage's log, and a declared input cannot become the new log. Original output/log/input bytes remain unchanged and the original receipt remains valid. |
| F3: canonical-command approval bypass | Resolved at executor boundary | Both actual `python -m ... native_pipeline run` and `python scripts/run.py ... native_pipeline run` exit 2 without approval; library execution and internal generation also reject before work. A valid exact-plan synthetic approval reaches the controlled first stage. Changing CHECK-IN bytes inside that stage prevents the second stage. The remaining container live route is now explicitly rejected at both entry functions; its dry diagnostic still succeeds. |
| F4: contradictory WZ decay | Resolved for tested topology substitutions | Valid W/Z card plans before and after the negative controls. Both photon substitution and wrong W charge reject before preparation. |
| F5: contradictory normalization | Resolved for tested evidence/operand contradictions | A valid three-source record with weights 2,-1,3 gives sumw=4, sumw2=14 and sigma=2 pb times k=.8 =>1.6 pb. Coherent headline inflation, missing source roles, and an edited generated sum all reject against recomputed evidence. Restoring the record succeeds. |
| F6: recent-log phantom liveness | Resolved | A recent log alone now blocks the running claim; a real live process with its actual start identity is accepted; the same PID with a false identity is blocked. |

No original finding remains open within these tested boundaries. The complete script assertions and machine-readable observations accompany this report.

## Evidence and reproducibility

- Script: `<review-workdir>/ravel-execution-independent-verification.py`.
- Output: `<review-workdir>/ravel-adversarial-execution-verification.json`.
- Command from DSRLab: `PYTHONPATH=hep-agentic-pipeline/src <review-workdir>/ravel-cli-clean-env/bin/python <review-workdir>/ravel-execution-independent-verification.py`.
- All eight probe groups passed; reviewed source hashes were identical before and after the run.
- Every original observation script/report/JSON was hash-checked and remained byte-for-byte unchanged.
- Native valid-approval controls use explicitly labeled synthetic fixture approvals and an inert supervisor callback, which stops after preparation dispatch. CLI rejection controls start no physics engine. Descendant/recovery/liveness cases use real short Python processes.

## Remaining limitations, separate from resolved findings

- Process cleanup is verified for the owned POSIX process group, including a dead leader with live members. This is not an OS sandbox or proof against a deliberately daemonized process that escapes that group.
- Canonical native commands are protected in the executor independently of shell-hook recognition. The legacy hook is not a complete shell parser. Live container dispatch is deliberately unavailable until an equivalent bound adapter exists.
- Approval verifies recorded instruction integrity, exact plan bytes, declared scope and budget. It is not independent human authentication.
- PID/start identity establishes observed process liveness at the time checked, not scientific progress or future completion.
- Normalization recomputation checks declared bookkeeping. These tests establish neither detector fidelity, generator-model adequacy nor statistical coverage. WZ daughter checks are bounded topology checks, not a complete SLHA physics validator.
- The broader source/public/package regression runs are owned by root. This report does not claim their completion, and it does not independently review my typed-result repairs.

## Exact tested source SHA-256

| Source | SHA-256 |
|---|---|
| `src/ravel/workflow/execution.py` | `a6526f0513e5140125c2e780eb74bc7a863153c37755d9a245e94a466785fba7` |
| `src/ravel/workflow/stage_supervisor.py` | `3e4ad72b8b78a1ac4c673671c7af7756828238e9fae7af7ff9c9b0efee84bcb0` |
| `src/ravel/workflow/state_io.py` | `29b8166c6d113f242684578594b5f6032e5c4e01d506fec9e7504b63c70e2297` |
| `src/ravel/workflow/workflow_state.py` | `d5b467e25d77f31f00dd735766b41f77a0a0fd39130e072378fb5a36213d3198` |
| `src/ravel/workflow/current_state.py` | `7f9c7274383465f788d1c47eb6481d6dcb50a533d89c18466bfff9aecc0bdcb1` |
| `src/ravel/workflow/stop_dispatch.py` | `45b9b59ddf888421db234ac3d2652234835c977617d5703ea5a60af223ad2c74` |
| `src/ravel/physics/native_pipeline.py` | `eb52dd1755bbfe78c7a2b547c0e45cc4ea037603cbda0f1f90eeee3b26853c9b` |
| `src/ravel/physics/native_capabilities.py` | `d5923a7d78d14eefc556d9e3797e0fc2336e80082eafad33ba60a704a4521112` |
| `src/ravel/physics/native_normalization.py` | `eedb8562078d97695880f44a27fc2e5a2c222197f552e7739640cb5f1528954f` |
| `src/ravel/workflow/scan_orchestrator.py` | `16ea96140671cee96a70bd80a53ff614f79a3eb27483a34174fc13620f0740e8` |
| `src/ravel/workflow/scan_babysitter.py` | `9babb5ba716e5e58eef585b4daa0764c44b4a20cbe2a9031f0d0400baddd7d85` |
| `.claude/hooks/pretooluse-bash.sh` | `72fd0352252c1533e75b745e527e10f434d036567e085b25839aca0b5d0e45a3` |

## Original observations preserved

| File | SHA-256 |
|---|---|
| `<review-workdir>/ravel-execution-review-probes.py` | `3d2d8ed66d7d1d87eb529e78ea653d0dfdf3ef6a912a7d2fcbd1aa544c8e8f20` |
| `<review-workdir>/ravel-execution-review-probes.json` | `29922efef9b2958153cc4b33a26368be17b4dd048315a188e364feb837bc7a82` |
| `<review-workdir>/ravel-native-review-probes.py` | `28a92d75009365c395fccfd0bb1851eecc799d626db0b7a05491a64bfc3fbd02` |
| `<review-workdir>/ravel-native-review-probes.json` | `28fc00e50e86541dc7975da2d4efe3c8010e06b9c4b92703dbc642c369f98a07` |
| `<review-workdir>/ravel-adversarial-execution-review.md` | `bc87fdb6799361b3d8352849e60b675a894ac22a433cd299eabf7720d4ff476b` |
