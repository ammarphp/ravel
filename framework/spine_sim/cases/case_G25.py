#!/usr/bin/env python3
"""G25 PRODUCER BARRIER (N4): a .lhe.gz whose banner nevents != the counted <event> records (grabbed
mid-write) must FAIL the producer barrier (inv producer-complete or the generation stage). The Cross-
section completion line is present so the FAIL isolates to the event-count mismatch. inv
producer-complete's locate_lhe_gz only matches *.lhe.gz and its banner regex only matches 'N = nevents'
-- mirror p4a _fixture_lhe_mid_write (a REAL gzip via gzip.open)."""
import gzip, os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import _case_lib as L

@L.case_main
def run():
    with L.tempdir() as td:
        rd = os.path.join(td, "2026-07-09_producer")
        L.write_contract(rd, task_mode="reproduce", stat_mode="best-sr-counting",
                         compute_plan="smoke", detector_mode="simpleanalysis-delphes-native")
        L.write_json(rd, "outputs/sr_yields.json",
                     [{"name": "SR1", "n": 5, "b": 4.0, "db": 1.0, "s": 3.0}])
        # a COMPLETE 'Cross-section :' line so the barrier FAILs on the event-count mismatch, not the log
        L.write_text(rd, "logs/madgraph.log", "Cross-section :   1.234e+00 pb  +- 1.2e-02 pb\n")
        lhe_dir = os.path.join(rd, "Events", "run_01")
        os.makedirs(lhe_dir, exist_ok=True)
        # banner promises 3 events but only 2 <event> records were written -> grabbed mid-write
        body = ("<LesHouchesEvents version=\"3.0\">\n<header>\n<MGGenerationInfo>\n"
                "  3 = nevents\n</MGGenerationInfo>\n</header>\n<init>\n</init>\n"
                "<event>\n1 1\n</event>\n<event>\n1 1\n</event>\n</LesHouchesEvents>\n")
        with gzip.open(os.path.join(lhe_dir, "unweighted_events.lhe.gz"), "wt", encoding="utf-8") as fh:
            fh.write(body)
        res, _ = L.run_validate(rd)
        fired = (L.invariant_status(res, "producer-complete") == "FAIL"
                 or L.stage_status(res, "generation") == "FAIL")
        L.gate_fired(fired, "neither inv producer-complete nor the generation stage FAILed")

if __name__ == "__main__":
    sys.exit(run())
