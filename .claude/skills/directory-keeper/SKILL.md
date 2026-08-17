---
name: directory-keeper
description: >
  Use at the END of any task that created, moved, renamed, or deleted files/folders in the
  hep-agentic-pipeline project (or DSRLab particle-physics workspace). Reconciles and updates
  DIRECTORY.md (the canonical directory map) against the actual tree, confirms new files are
  categorized into the right track, and confirms environment/data changes were logged. Trigger
  whenever wrapping up work that touched the repo layout, before reporting completion.
---

# Directory Keeper

Keep `DIRECTORY.md` (at the repo root) a faithful, authoritative map of the project. Run this at
the end of any task that changed the file layout. It is fast and prevents documentation drift in
a repo meant to be distributed to other researchers.

## Procedure

1. **Locate the map.** Find `DIRECTORY.md` at the project root (e.g.
   `hep-agentic-pipeline/DIRECTORY.md`). If it does not exist, create it from the template below.

2. **List the actual tree** (excluding local-only/gitignored paths):
   ```bash
   cd <repo-root>
   find . -not -path './**/build/*' -not -path './.git/*' -not -name '.DS_Store' | sort
   ```

3. **Reconcile.** For every difference between the tree and `DIRECTORY.md`:
   - **New file/folder not in the map** → add a row. Assign its **track tag**:
     `agent` · `pedagogical` · `data` · `software` · `output` · `local-only` · `meta`.
     If you cannot confidently categorize it, list it under "⚠ Needs categorization" and tell the user.
   - **Entry in the map but missing on disk** → remove the row (or mark it `(planned)` if it is an
     intentional placeholder for future work).
   - **Moved/renamed** → update the path.

4. **Confirm change-logging hygiene** (do not skip):
   - If the environment changed (new tool/version/config), it must be in the stage's
     `changes/ENVIRONMENT-CHANGES.md`.
   - If a card or data file changed, it must be in `changes/DATA-AND-CARD-CHANGES.md` with both a
     workflow-level and a pedagogical-level pointer.
   - If either is missing, add it (or flag it to the user).

5. **Confirm originals are preserved.** Pristine inputs (e.g. provided cards) must still exist
   untouched; edits should live on copies. Flag any in-place mutation of an original.

6. **Report** a one-line summary of what changed in `DIRECTORY.md` and any ⚠ items.

## Template for a missing `DIRECTORY.md`
```markdown
# Directory map

Authoritative layout of this repository. Track tags: agent | pedagogical | data | software |
output | local-only | meta. Kept in sync by the `directory-keeper` skill.

| Path | Track | Purpose |
|------|-------|---------|
| README.md | meta | top-level orientation |
| ... | ... | ... |
```

## Trial runs
- If the task ran the pipeline, confirm a dated run folder exists under `trial-runs/` following the
  layout in `trial-runs/README.md` (RESULT.md + config/ + inputs/ + logs/ + outputs/), and that
  `RESULT.md` is filled in. Flag any incomplete run folder.

## Red flags (you are rationalizing — stop)
| Thought | Reality |
|---|---|
| "Tiny change — the map can't have drifted" | Doc drift compounds silently (catalogue D2: stale doc lines kept re-installing a dead default); the map stays trustworthy only because EVERY layout change reconciles it. |
| "That stray dir outside the run tree can wait" | Catalogue D3's recurrence was exactly that — a stray output dir outside the run tree, caught at cleanup. Flag and place it now. |
| "I'll update the map and skip the change-logs" | Step 4 is half the job: an environment/card change missing from the changes logs is drift with a delay fuse. |

## Stop conditions
- A new path you cannot confidently categorize → list it under "⚠ Needs categorization" and
  tell the user; never guess a track silently.
- A pristine original (the provided cards) mutated in place → stop and flag it immediately;
  do not paper over it in the map (hard rule, CLAUDE.md).

## Notes
- Do **not** enumerate the contents of `build/` or per-run heavy intermediates (local-only/
  gitignored) — list `build/` and `trial-runs/` as single entries.
- This skill is about the *map*, not the files themselves; it does not move or delete anything
  except editing `DIRECTORY.md`.
- Mechanical backstop: `python3 trial-runs/_infrastructure/check_agent_surface.py` asserts the
  map two ways (every row exists on disk; unmapped top-level entries WARN) — run it to confirm
  the reconcile landed clean.
