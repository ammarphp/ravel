# Checklist — troubleshooting

Symptom → fix. These are the failures seen building and running this pipeline.

| Symptom | Fix |
|---|---|
| `rivet`/`yoda` "Python module could not be loaded" | don't wrap in a login shell (`bash -lc`) — it clobbers the conda env; use `conda run -n rivet <cmd>` directly |
| Pythia8 Python module has no HepMC writer | use the compiled C++ bridge `pythia_shower` (built in step 1) — the official `Pythia8Plugins/HepMC3.h` writer |
| `rivet-mkhtml: unrecognized arguments: --no-weights` | drop the flag; just `rivet-mkhtml <yoda> -o <dir>` |
| Rivet lists analyses instead of running | the `-a <ID>` name is wrong; copy an exact ID from `rivet --list-analyses` |
| Contur `No 'signal'/'uncertainties' block found` | supply a `config.dat` (configobj format) with all required blocks — adapt `…/share/contur/tests/sources/custom_config.dat` |
| Contur runs but "Not adding likelihood … list is empty" | the analysis isn't in Contur's likelihood database (it targets measurements); take the exclusion from pyhf instead — `docs/workflow/steps/07-exclude.md` (counting model from the bundled REF, or a published likelihood) |
| `python: command not found` running a helper | there is no bare `python` on PATH — from the repository root, run `$CONDA run -n rivet python scripts/run.py ravel.<group>.<module>` (the `rivet` env has the deps) |
| `rivet-mkhtml -o` wrote plots in the wrong place | `-o` is relative to the current dir; pass full paths and do not `cd` first (`rivet-mkhtml <rundir>/build/x.yoda -o <rundir>/plots`) |
| `from pyhf.infer.intervals import upper_limit` fails | in pyhf 0.7.x it is `pyhf.infer.intervals.upper_limits.upper_limit`; `pyhf_exclude.py` uses a grid-bracket+interpolate instead |
| HEPData JSON fetch: `SSLCertVerificationError` | the local CA bundle is missing; `hepdata_fetch.py` retries with the `certifi` bundle — verification is never bypassed (CR-021); run under a conda env that has certifi |
| HEPData looks "down/blocked" for a record | READ the census R1 status: `ABSENT` (open-API 404, INSPIRE-corroborated) = **no record exists** — plan around absence; `ERROR outage-or-block` (403/5xx/network) = retry later / browser — never conclude absence from an outage (the two were once conflated: a real "Cloudflare-blocked/503" diagnosis masked a genuine no-record) |
| `--tables` fails (no hepdata-cli, or the cli route 403s) | `hepdata_fetch.py` auto-falls back to the open `/record/data/<recid>/<table_id>/<version>` endpoint (ids from the record JSON) with the same verify-after-download contract; only BOTH routes failing exits nonzero |
| pyhf limit looks like ">2" / stuck at the scan ceiling | it was a fixed µ grid (e.g. mapyde muscan 0.1–2.0); use `pyhf_exclude.py` — it has no ceiling (see `docs/workflow/checklists/exclusion-model.md`) |
| pyhf Mode-A limit with obs==exp, or a non-monotonic/cliffy CLs curve, or µ_hat==1.0 exactly | the CR-005 silent-SLSQP failure class (NaN pockets in −2lnL): current `pyhf_exclude.py` auto-escalates to guarded MIGRAD (check `exclusion.json` `"optimizer"`); a result from an OLDER copy of the tool with these signatures is untrustworthy — re-run. A guard `RuntimeError` = sick surface, never bypass it with the stock backend |
| MadGraph `madgraph requires the six module` | `conda install -n mg5 -c conda-forge six numpy` |
| MadGraph `InvalidParam … int('decay')` | run `environment/scripts/normalize_param_card.py` on the SLHA card |
| `width of particle 13 too small …` | benign — that particle is not an s-channel propagator |
| Fortran/HepMC link errors on macOS | ensure Apple Command Line Tools (the SDK) are present; conda sets `SDKROOT` |
| **(container special case only)** podman VM won't boot (`VZErrorDomain Code=1`) | conda's podman is x86 → it pulls an unbootable amd64 image; use the native arm64 podman client + arm64 `vfkit`/`gvproxy` |
| **(container special case only)** stale container name collision after an interrupted run | `podman rm -f $(podman ps -aq)` before re-running |
| a long run dies overnight | wrap it in `caffeinate -i -s` so macOS does not idle-sleep |

If unresolved, read the stage's own log/debug output and CHECK IN.
