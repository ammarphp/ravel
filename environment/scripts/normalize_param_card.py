#!/usr/bin/env python3
"""Normalize non-standard SLHA DECAY header lines for MadGraph's strict parser.

WHY THIS EXISTS
---------------
The ATLAS HEPData SLHA card (`param_card_200_150.dat`) writes some Standard-Model
particle decay widths in a NON-STANDARD form, e.g.:

    DECAY   6    decay 6 1.42E+00  # WT     <-- spurious "decay 6" before the width

The SLHA standard (and MadGraph's `check_param_card.py`) expect:

    DECAY 6 1.42E+00  # WT

so MadGraph raises `InvalidParam` on the non-standard lines. The affected lines are
all SM particles (t, Z, W, h, light quarks/leptons). Their widths do not change the
LO slepton-pair matrix element, but the file must parse for MadGraph to run at all.

WHAT THIS DOES
--------------
Rewrites ONLY the malformed `DECAY <pdg> decay <pdg> <width> ...` header lines into
`DECAY <pdg> <width> ...`, preserving the PDG code, the numeric width, and the
trailing comment EXACTLY. Every mass, mixing-matrix entry, and the slepton ->
lepton + neutralino branching tables are left untouched. No physics is altered.

USAGE
-----
    python normalize_param_card.py <input.dat> <output.dat>
"""
import re
import sys

if len(sys.argv) != 3:
    sys.exit("usage: normalize_param_card.py <input.dat> <output.dat>")

src, dst = sys.argv[1], sys.argv[2]

# Match:  DECAY <pdg> decay <pdg> <rest...>   (the non-standard form)
# Capture: (1) "DECAY " + ws, (2) pdg, (3) ws, then DROP "decay <pdg> ", keep (4) rest.
pat = re.compile(r'^(DECAY\s+)(-?\d+)(\s+)decay\s+-?\d+\s+(.*)$')

changed = []
out_lines = []
with open(src) as fh:
    for lineno, line in enumerate(fh, 1):
        body = line.rstrip('\n')
        m = pat.match(body)
        if m:
            new = f"{m.group(1)}{m.group(2)}{m.group(3)}{m.group(4)}"
            out_lines.append(new + '\n')
            changed.append((lineno, body, new))
        else:
            out_lines.append(line)

with open(dst, 'w') as fh:
    fh.writelines(out_lines)

print(f"Normalized {len(changed)} non-standard DECAY line(s): {src} -> {dst}")
for lineno, old, new in changed:
    print(f"  L{lineno}:")
    print(f"      OLD: {old}")
    print(f"      NEW: {new}")
