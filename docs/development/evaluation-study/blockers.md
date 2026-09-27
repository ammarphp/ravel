# Evaluation study: blockers

A blocker stops a specific package or action, not the whole program. Local deterministic work
continues around each one.

Since 2026-09-26 the human reviews are deferred to one consolidated review after further
development and no longer block development ([decisions.md](decisions.md) E-34). Their rows stay
here, marked "deferred review (E-34)": their questions are still open, and nothing produced under
their provisional defaults is reported as a scored or empirical finding before that review. The
same direction authorized the 8-assignment engineering smoke, so B-03 now holds only the
engineering and setup it still needs.

| ID | Status | Blocks | Blocker | Unblocking action | Owner |
|---|---|---|---|---|---|
| B-01 | deferred review (E-34) | Reporting any scored or empirical result; WP02 exit (G0) | No approved study charter or oracle definitions (PKT-D01, PKT-D02, PKT-D04, PKT-D05) | The consolidated review of the Phase 0 audit, slice design §5 and the oracle review packet | Ammar, the lab |
| B-02 | deferred review (E-34) | WP05 exit; using the oracle to score any non-synthetic run | The pyhf-free oracle has no human statistics review | In the consolidated review, a statistics reviewer checks model, estimand, roots, tolerance and the cross-check evidence | Statistics reviewer |
| B-03 | open: engineering (smoke authorized, E-34) | Launching WP15, the authorized 8-assignment smoke; WP16 (pilot) | The harness cannot yet run a real host: no real-host campaign builder, `claude_cli` adapter factory and launcher, real-host launch policy, proxy start, credential path or arm-free path names ([smoke-request.md](smoke-request.md), "Not implemented" 1–6). No provider credential is provisioned for an isolated config, and headless `claude -p` authentication on this host is unverified. The smoke's approval record (per-run cap, model, the Claude choices of H-04) is not written. The pilot has no authorization | Build and test the missing real-host pieces (local engineering); provision a credential for the isolated config; write the approval record and freeze the smoke campaign with it; authorize the pilot separately | Integration lead (engineering); Ammar (credential, pilot) |
| B-04 | open | WP08 live validation | No pinned standalone Codex CLI (only an auto-updating alpha inside the ChatGPT app) | Decide H-04; pin by path and SHA-256 or authorize an install | Ammar |
| B-05 | open: waits on B-03 | Real-host isolation proof | A live model session inside the deny-default profile (with the allowlist proxy) has not been verified; server-side tools (web search) are outside any local boundary; the profile gives subjects no pty and no named semaphores, which a host's shell tool may need | The authorized smoke (E-34) inspects the init tool list and denial logs and exercises the host's shell tool and a multiprocessing script under the production profile | Integration lead |
| B-06 | open | WP18, WP21 (protected final cases) | No holdout custodian; this repository shares `.git` with the historical checkout and is published (E-35), so evaluator or holdout material for protected cases must never be committed here | Name a custodian and an external store (PKT-D08) | Lab |
| B-07 | open for the pilot and later campaigns | Scripted assent for a real subject outside synthetic engineering campaigns | Scripted-YES authorization for evaluation assignments not granted (PKT-D06). The E-34 smoke is a `synthetic_engineering` campaign, where broker operations are pre-authorized by the provisional default | Ammar authorizes scope and escalation rules | Ammar |
| B-08 | open | WP20 external baselines | Licences and resources: JFC and the Collider-Bench GitHub repo have no licence; HEPTAPOD is GPL-3.0; ColliderAgent needs a remote platform account; SFitterAgents needs SLURM | PKT-D11 | Ammar |
| B-09 | open | WP24–WP27 (a separate method-development track, outside this study) | Its dataset and method choices are undecided | PKT-D09, PKT-D10 | The lab |
