.PHONY: green green-self-drive spine-sim replay claims

# REPLAY MODE (the README quickstart): re-validate the cached benchmark artifacts through the
# real pyhf statistics + provenance layers. Needs only `pip install -r requirements-replay.txt`.
replay:
	python3 scripts/run.py ravel.validation.benchmark --fast

# The claims gate: each registered claim in the validation documentation must match evidence/claims.json (+ artifact pins).
claims:
	python3 scripts/check_publication.py
	python3 scripts/check_evidence.py --check
# The aggregate workflow-adherence green bar (L6): every gate G0-G27 fires + the CR board + agent
# surface coherence. Run before merging the spine worktree back.
green:
	python3 scripts/green_board.py

# ALSO run the live clean-room self-drive (needs `claude` on PATH + the conda symlink in the worktree).
green-self-drive:
	python3 scripts/green_board.py --with-self-drive

# Just the per-gate simulation harness.
spine-sim:
	python3 tests/adversarial/run_suite.py --require-all
