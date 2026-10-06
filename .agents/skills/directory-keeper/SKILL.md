---
name: directory-keeper
description: >
  Use at the END of any task that created, moved, renamed, or deleted files/folders in the
  Ravel repository. Reconciles and updates
  DIRECTORY.md (the canonical directory map) against the actual tree, confirms new files are
  placed in the right table, and confirms environment/data changes were logged. Trigger
  whenever wrapping up work that touched the repo layout, before reporting completion.
---

# Directory Keeper

Keep `DIRECTORY.md` (at the repo root) a faithful, authoritative map of the project. Run this at
the end of any task that changed the file layout. It is fast and prevents documentation drift in
a repo meant to be distributed to other researchers.

## Procedure

1. **Locate the map.** Find `DIRECTORY.md` at the root of the current checkout.
   If it does not exist, create it from the template below.

2. **List the actual tree** (excluding local-only/gitignored paths):
   ```bash
   cd <repo-root>
   find . -not -path './**/build/*' -not -path './.git/*' -not -name '.DS_Store' | sort
   ```

3. **Reconcile.** For every difference between the tree and `DIRECTORY.md`:
   - **New file/folder not in the map** → add a row to the matching table: `| File | Purpose |`
     for root files and key files, `| Directory | Contents |` for directories, `| Collection |
     Contents |` for curated evidence. If you cannot confidently place it, list it under
     "⚠ Needs categorization" and tell the user.
   - **Entry in the map but missing on disk** → remove the row.
   - **Moved/renamed** → update the path.

4. **Confirm change-logging hygiene** (do not skip):
   - If the environment changed (new tool/version/config), it must be in
     `environment/changes/environment-changes.md`.
   - If a card or data file changed, it must be in a change record beside the changed material (as in
     `benchmarks/scoped/changes/data-and-card-changes.md`) with a workflow pointer.
   - If either is missing, add it (or flag it to the user).

5. **Confirm originals are preserved.** Pristine inputs (e.g. provided cards) must still exist
   untouched; edits should live on copies. Flag any in-place mutation of an original.

6. **Report** a one-line summary of what changed in `DIRECTORY.md` and any ⚠ items.

## Template for a missing `DIRECTORY.md`
```markdown
# Repository directory

Maintained by hand with the `directory-keeper` skill when files are added, moved or removed.

## Root files

| File | Purpose |
|---|---|
| `README.md` | Project overview and entry points |

## Main directories

| Directory | Contents |
|---|---|
| `src/ravel/physics/` | Event processing and statistical engines |
```

## Trial runs
- If the task ran the pipeline, confirm a dated run folder exists under `trial-runs/` following the
  layout in `docs/workflow/run-directory.md` (RESULT.md + config/ + inputs/ + logs/ + outputs/), and that
  `RESULT.md` is filled in. Flag any incomplete run folder.

## Red flags (you are rationalizing — stop)
| Thought | Reality |
|---|---|
| "Tiny change — the map can't have drifted" | Doc drift compounds silently (catalogue D2: stale doc lines kept re-installing a dead default); the map stays trustworthy only because EVERY layout change reconciles it. |
| "That stray dir outside the run tree can wait" | Catalogue D3's recurrence was exactly that — a stray output dir outside the run tree, caught at cleanup. Flag and place it now. |
| "I'll update the map and skip the change-logs" | Step 4 is half the job: an environment/card change missing from the changes logs is drift with a delay fuse. |

## Stop conditions
- A new path you cannot confidently categorize → list it under "⚠ Needs categorization" and
  tell the user; never guess a placement silently.
- A pristine original (the provided cards) mutated in place → stop and flag it immediately;
  do not paper over it in the map (hard rule, CLAUDE.md).

## Notes
- Do **not** enumerate the contents of `build/` or per-run heavy intermediates (local-only/
  gitignored) — list `build/` and `trial-runs/` as single entries.
- This skill is about the *map*, not the files themselves; it does not move or delete anything
  except editing `DIRECTORY.md`.
- Mechanical backstop: `python3 scripts/run.py ravel.validation.check_agent_surface` asserts the
  map two ways (every row exists on disk; unmapped top-level entries WARN) — run it to confirm
  the reconcile landed clean.
