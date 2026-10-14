# mcfm-amplitudes component

A small overlay for MCFM 10.2.1 that writes the per-point helicity
amplitudes for interfering resonances at every integration point to a text file. RAVEL turns that file into a
compact amplitude store and recombines it for any coupling and propagator choice.

## Contents

| File | Purpose |
|---|---|
| `ravel_bridge.f90` | capture module: per point, the continuum and spin-0 helicity amplitudes for both lepton pairings, momenta and integration weights |
| `ravel_driver.f90` | program `ravel_mcfm_amplitudes`: point evaluation, warm-up and fixed-grid weighted blocks |
| `lowint-capture.patch` | three-line hook in `src/Procdep/lowint.f` |
| `CMakeLists-ravel.cmake` | build target, included at the end of MCFM's root `CMakeLists.txt` |
| `upstream-api.json` | sha256 of every upstream MCFM file the overlay relies on |
| `addon.json` | component manifest read by RAVEL (name, license, file hashes) |

## Build

The RAVEL installer fetches MCFM at the pinned commit, applies the patch, copies these
files to `<mcfm>/ravel/`, appends `include(ravel/CMakeLists-ravel.cmake)` to the root
`CMakeLists.txt` and builds with GNU compilers inside the Linux container recipe of the
execution backend. The program needs one thread and no MPI.

## How RAVEL finds it

RAVEL looks for `mcfm-amplitudes/addon.json` in, in order: the directories listed in
`RAVEL_ADDON_PATH`, `$RAVEL_NATIVE_BUILD/addons`, the shared native build
(`${XDG_DATA_HOME:-~/.local/share}/ravel-native/addons`) and, in a source checkout,
`addons/gpl`. It checks every listed file against its sha256 before use.

## Program protocol

The program runs in a directory holding `input.ini` (an MCFM card for process 131 at
LO), `ravel-control.dat` (`operation draws seed channel`) and, depending on the
operation, `ravel-points.dat` or `proposal-grid.bin`. It writes `amplitudes.dat`.
Operation 0 evaluates supplied points, 1 is the warm-up that writes
`proposal-grid.bin`, and 2 integrates a block on that frozen grid. Channel 1, 2 and 3
select the lepton-flavour configuration declared in the card (different flavours,
identical electrons, identical muons).
