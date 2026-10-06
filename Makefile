.PHONY: green adversarial replay claims

# REPLAY MODE (the README quickstart): re-validate the cached benchmark artifacts through the
# real pyhf statistics + provenance layers. Needs only `pip install -r requirements-replay.txt`.
replay:
	python3 scripts/run.py ravel.validation.benchmark --fast

# The claims gate: each registered claim in the validation documentation must match evidence/claims.json (+ artifact pins).
claims:
	python3 scripts/check_publication.py
	python3 scripts/check_evidence.py --check
# The aggregate workflow-adherence green bar: the adversarial gate board (every gate G0-G27 fires),
# agent-surface coherence and the run-state selftest. Run before committing workflow changes.
green:
	python3 scripts/green_board.py

# Just the adversarial gate board (the per-gate simulation harness).
adversarial:
	python3 tests/adversarial/run_suite.py --require-all
