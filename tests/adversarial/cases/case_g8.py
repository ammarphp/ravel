#!/usr/bin/env python3
"""G8 RESOLVE (D8/D-4): an OPEN tool_generator_model failure cannot be closed without a
recipe_search.json. Per RECONCILE D-4 this is a NON-invariant Stop branch: drive
stop_dispatch.py --branch recipe-search (which shells resource_census.py --assert-recipe-search) and
assert exit 2 + the G8-RECIPE-SEARCH token, not the bare predicate CLI."""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import _case_lib as L

@L.case_main
def run():
    with L.tempdir() as td:
        rd = os.path.join(td, "2026-07-09_svj")
        # a generator-model failure the run_state still lists as open (assert_recipe_search keys on
        # failure_class=="tool_generator_model"); NO inputs/recipe_search.json -> the close-block fires
        L.write_json(rd, "logs/madgraph.failure.json",
                     {"stage": "madgraph", "failure_class": "tool_generator_model"})
        L.write_run_state(rd, session_id="T", open_failure_records=["logs/madgraph.failure.json"])
        cp = L.drive_stop(rd, "recipe-search", last_message="Here is the results deck.")
        L.assert_block(cp, L.STOP_TOKENS["recipe-search"])

if __name__ == "__main__":
    sys.exit(run())
