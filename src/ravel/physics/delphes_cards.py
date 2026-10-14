"""Read a Delphes TCL card: which particles the detector sees and what MET uses.

Delphes calorimeter modules deposit a fraction of each stable particle's
energy, chosen by ``add EnergyFraction {abs(PDG)} {fractions}``. A particle
without its own row takes the ``{0}`` default row. A new stable particle that
should escape (a gravitino, a sneutrino, a dark-sector state) is therefore
visible unless every calorimeter lists it with zero fractions. Reconstructed
missing momentum is built from whatever the card merges into it, so such a
particle also changes MET. ``invisible_census`` reports this per PDG code from
the card text alone; it runs nothing and reads no events.
"""
from __future__ import annotations

import re

_MODULE = re.compile(r"^module\s+(\S+)\s+(\S+)\s*\{(.*?)^\}", re.M | re.S)
_FRACTION = re.compile(r"^\s*add\s+EnergyFraction\s+\{\s*(-?\d+)\s*\}\s+\{([^}]*)\}", re.M)
_PDG = re.compile(r"^\s*add\s+PdgCode\s+\{\s*(-?\d+)\s*\}", re.M)
_INPUT = re.compile(r"^\s*(?:add|set)\s+InputArray\s+(\S+)", re.M)
CALORIMETERS = ("SimpleCalorimeter", "Calorimeter", "DualReadoutCalorimeter")


def modules(text):
    """[(type, name, body)] in card order; comments are dropped first."""
    clean = "\n".join(line.split("#", 1)[0] for line in text.splitlines())
    return [(m.group(1), m.group(2), m.group(3)) for m in _MODULE.finditer(clean + "\n")]


def energy_fractions(body):
    rows = {}
    for code, values in _FRACTION.findall(body):
        numbers = [float(x) for x in values.split()]
        if not numbers:
            raise ValueError(f"EnergyFraction row for {code} has no fraction")
        rows[abs(int(code))] = numbers
    return rows


def invisible_census(text, pdg_codes, *, met_module="MissingET", generator_met_module="GenMissingET"):
    """Per PDG code: calorimeter deposits, and whether MET treats it as invisible.

    Returns ``{pdg: {'calorimeters': {module: fractions}, 'invisible_to_calorimeters':
    bool, 'in_generator_met_filter': bool}}``. ``invisible_to_calorimeters`` is
    True only when every calorimeter module gives the code all-zero fractions,
    either by its own row or by the default row. ``in_generator_met_filter`` is
    True when a ``PdgCodeFilter`` feeding the generator-level MET module lists
    the code (signed or not). Charged particles also leave tracks; this census
    covers neutral stable states.
    """
    found = modules(text)
    if not found:
        raise ValueError("no Delphes modules found in the card")
    calorimeters = [(name, energy_fractions(body)) for kind, name, body in found if kind in CALORIMETERS]
    if not calorimeters:
        raise ValueError("the card defines no calorimeter module")
    filters = {name: {int(c) for c in _PDG.findall(body)} for kind, name, body in found if kind == "PdgCodeFilter"}
    bodies = {name: body for _, name, body in found}
    generator_inputs = {array.split("/", 1)[0] for array in _INPUT.findall(bodies.get(generator_met_module, ""))}
    census = {}
    for code in pdg_codes:
        deposits = {}
        for name, rows in calorimeters:
            if abs(code) in rows:
                deposits[name] = rows[abs(code)]
            elif 0 in rows:
                deposits[name] = rows[0]
            else:
                raise ValueError(f"calorimeter {name} has no row for {code} and no default row")
        census[code] = {
            "calorimeters": deposits,
            "invisible_to_calorimeters": all(not any(f) for f in deposits.values()),
            "in_generator_met_filter": any(code in filters[f] or -code in filters[f]
                                           for f in generator_inputs if f in filters),
            "reconstructed_met_module_present": met_module in bodies,
        }
    return census


def visible_invisibles(text, pdg_codes):
    """The codes the analysis expects to escape but the card makes visible."""
    census = invisible_census(text, pdg_codes)
    return sorted(code for code, row in census.items() if not row["invisible_to_calorimeters"])
