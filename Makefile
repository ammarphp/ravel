.PHONY: green green-self-drive spine-sim replay claims

# REPLAY MODE (the README quickstart): re-validate the cached benchmark artifacts through the
# real pyhf statistics + provenance layers. Needs only `pip install -r requirements-replay.txt`.
replay:
	python3 framework/benchmark/run_benchmark.py --fast

# The claims gate: every number in README.md must match results/manifest.json (+ artifact pins).
claims:
	python3 scripts/claims_check.py
	python3 framework/check_evidence.py --check
# The aggregate workflow-adherence green bar (L6): every gate G0-G27 fires + the CR board + agent
# surface coherence. Run before merging the spine worktree back.
green:
	python3 framework/green_board.py

# ALSO run the live clean-room self-drive (needs `claude` on PATH + the conda symlink in the worktree).
green-self-drive:
	python3 framework/green_board.py --with-self-drive

# Just the per-gate simulation harness.
spine-sim:
	python3 framework/spine_sim/run_spine_sim.py --require-all
