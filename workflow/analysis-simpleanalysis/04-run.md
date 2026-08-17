# Step 4 — Run the pipeline

Run the six stages in order: `madgraph → delphes → analysis → simpleanalysis → sa2json → pyhf`.
(`mapyde run all` omits simpleanalysis/sa2json, so run stage-by-stage.) Use the provided driver,
which auto-cleans stale containers and logs each stage.

**Do (one command; wrap in `caffeinate` so the VM can't idle-sleep):**
```bash
RUN="$PWD/trial-runs/<your-run-folder>"
caffeinate -i -s bash trial-runs/_infrastructure/run-pipeline.sh "$RUN" "config/run.toml" &
```
Run it in the background for long jobs. The driver writes `logs/STATUS.txt` (PASS/FAIL + timing
per stage) and `logs/<stage>.log`.

**What each stage produces (under `<RUN>/output/`):**
- madgraph → `madgraph/.../unweighted_events.lhe.gz` + `*pythia8_events.hepmc.gz`; prints `Cross-section`.
- delphes → `delphes/delphes.root`.
- analysis (Delphes2SA) → `analysis/Delphes2SA.root`.
- simpleanalysis → `<selection>.txt/.root/.json` (per-signal-region yields + acceptance).
- sa2json → `<selection>_patch.json` (signal patch for the likelihood).
- pyhf → `muscan_results.json` (the µ limit) + `EwkCompressed2018_patch.json`.

**Monitor:**
```bash
tail -f trial-runs/<your-run-folder>/logs/STATUS.txt
```

**If a stage FAILs:** the driver stops there; open that stage's log and
`workflow/checklists/troubleshooting.md`.

**Next:** `05-read-results.md` (in this directory)
