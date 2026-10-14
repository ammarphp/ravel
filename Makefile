.PHONY: green gate-sim

# The aggregate workflow-adherence green bar: every gate G0-G27 fires + the CR board + agent
# surface coherence.
green:
	python3 scripts/green_board.py

# Just the per-gate simulation harness.
gate-sim:
	python3 tests/adversarial/run_suite.py --require-all
