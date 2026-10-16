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
`CMakeLists.txt` and builds with GNU compilers: inside the Linux container recipe on
macOS, on the host with the compiler-bootstrap toolchain on Linux x86_64. The program
needs one thread and no MPI. MCFM's fixed-form include files `zcouple_cms.f` and
`cpscheme.f` cannot be included in free-form source; the bridge and driver declare
their common blocks, and `upstream-api.json` pins both files.

## How RAVEL finds it

RAVEL looks for `mcfm-amplitudes/addon.json` in, in order: the directories listed in
`RAVEL_ADDON_PATH`, `$RAVEL_NATIVE_BUILD/addons`, the shared native build
(`${XDG_DATA_HOME:-~/.local/share}/ravel-native/addons`) and, in a source checkout,
`addons/gpl`. It checks every listed file against its sha256 before use.

## Program protocol

The program is given the path of `input.ini` (an MCFM card for process 131 at LO) and
works in that card's directory, which also holds `ravel-control.dat` (`operation draws
seed channel`), MCFM's runtime files `process.DAT`, `br.sm1` and `br.sm2` and, depending
on the operation, `ravel-points.dat` or `proposal-grid.bin`. A card path with a directory
must be absolute. It writes `amplitudes.dat` (and the warm-up's `proposal-grid.bin`) to
`RAVEL_OUTPUT_DIR` when that is set, otherwise to the card's directory.
Operation 0 evaluates supplied points, 1 is the warm-up that writes
`proposal-grid.bin`, and 2 integrates a block on that frozen grid. Channel 1, 2 and 3
select the lepton-flavour configuration declared in the card (different flavours,
identical electrons, identical muons).

The output (record format `RAVEL_MCFM_3`) opens with the control line, the
initialized `DOMAIN` and a `SAFETY` header naming the cuts the program applies.
Both are MCFM's own and are declared in `addon.json` under `protocol.safety_cuts`:
MCFM omits its continuum quark loops below a Z transverse momentum of 0.1 GeV
(`src/ZZ/getggZZamps.f`), applied here to both lepton pairings, and `lowint`
discards a draw whose lepton energies or normalized invariants fall below 1e-9
(`passed_smallnew`, `src/Need/smallnew.f`), applied here to supplied points too. A
draw below either is written as an `EXCLUDE` record with its momenta (and, for the
Z cut, its weight fields and MCFM's own squared amplitude), counts in the
`COMPLETE` census and is never stored, so integrals cover exactly the restricted
phase space and the excluded share is measured.
