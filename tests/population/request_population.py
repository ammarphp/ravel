"""A fixed-seed population of physics requests drawn from orthogonal axes.

Axes: deliverable (with its claim kind) x inputs x field x beams x level x constraint x phrasing.
Each request records the axes it was drawn from and the constraint type its wording should yield,
so extractor recall can be reported per constraint type without gating on it.

    python tests/population/request_population.py --size 20 --seed 2026
"""
from __future__ import annotations

import argparse
import hashlib
import json
import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import synthetic_identifiers as syn  # noqa: E402

SEED = 20261011
CI_SIZE = 2000

FIELDS = {
    "collider": ["a 1.5 TeV Z' boson decaying to dileptons", "stop pair production with a 300 GeV neutralino",
                 "a heavy neutral lepton mixing with muons", "vector-like top partners decaying to bW"],
    "flavour": ["the B_s to mu mu branching ratio with a scalar leptoquark", "lepton-flavour universality ratios R(K)",
                "the C9 Wilson coefficient in b to s transitions", "tau to mu gamma from a flavour-violating Z'"],
    "electroweak": ["the W boson mass with a scalar triplet", "anomalous triple gauge couplings in WW production",
                    "the oblique parameters S and T for a heavy doublet", "the effective weak mixing angle"],
    "higgs": ["the Higgs self-coupling", "Higgs decays to invisible particles",
              "the Higgs coupling to charm quarks", "a 650 GeV heavy scalar decaying to hh"],
    "cosmology": ["the relic density of a 200 GeV singlet scalar", "the sum of neutrino masses from CMB lensing",
                  "warm dark matter from Lyman-alpha data", "the Hubble constant with early dark energy"],
    "astro-particle": ["neutrino flux from a blazar", "gamma-ray lines from dark-matter annihilation in the Galactic centre",
                       "axion-photon conversion in galaxy clusters", "cosmic-ray antiprotons from dark matter"],
    "machine learning": ["a graph-network jet tagger", "a normalising-flow background model",
                         "a weakly supervised anomaly detector", "a transformer for event classification"],
    "theory": ["the one-loop effective potential of a real singlet extension", "two-loop corrections to the rho parameter",
               "unitarity bounds in a two-Higgs-doublet model", "the beta function of a gauge-Yukawa theory"],
    "writing": ["the results of my completed scan run", "the limits from the two finished recast runs",
                "the calibration study in my run directory", "the method comparison I finished last week"],
}
DELIVERABLES = {
    "exclusion": "derive the exclusion limits on {subject}",
    "estimate": "fit and report the allowed range for {subject}",
    "significance": "compute the significance for {subject}",
    "prediction": "predict the distributions for {subject}",
    "agreement": "test whether the prediction for {subject} agrees with the published measurement",
    "calculation": "calculate the leading-order expression for {subject}",
    "finding": "summarise what the literature says about {subject}",
    "method_performance": "evaluate how well {subject} performs against a baseline",
    "document": "write a short note on {subject}",
}
INPUTS = {
    "none": "",
    "files": " using the attached file inputs.root",
    "identifiers": " using HEPData record ins1559 and arXiv:" + syn.arxiv(587),
    "template": " and fill the attached results template without changing its bins",
    "stated counts": " given 9 observed events on an expected background of 4.2 ± 0.8",
}
BEAMS = {
    "pp": " at a 13 TeV proton-proton collider",
    "e+e-": " at a 240 GeV electron-positron collider",
    "mu+mu-": " at a 10 TeV muon collider",
    "ep": " at a 1.3 TeV electron-proton collider",
    "none": "",
}
LEVELS = {"observed": " with the observed data", "expected": " as an expected sensitivity", "not_applicable": ""}
CONSTRAINTS = {
    "none": ("", None),
    "blinding": (" Keep the signal regions blinded.", "blinding"),
    "forbidden sources": (" Do not use HEPData or the paper's figures.", "source_restriction"),
    "prescription formula": (" Use the significance S/sqrt(B + 0.1 B^2).", "prescribed_statistic"),
    "n-sigma": (" Give the 2-sigma region.", "prescribed_statistic"),
    "confidence level": (" Quote it at 90% CL.", "prescribed_statistic"),
    "delegation": ("", "delegation"),
    "negated stage": (" Do not run a detector simulation.", "negated_stage"),
    "requested tool": (" Use MadGraph for any event generation.", "requested_tool"),
}
PHRASINGS = {
    "imperative": "{core}.",
    "question": "Can you {core}?",
    "polite": "Please {core}, thank you.",
    "terse": "{core}",
    "first person": "I need you to {core}.",
}


def _core(rng, axes):
    subject = rng.choice(FIELDS[axes["field"]])
    text = DELIVERABLES[axes["deliverable"]].format(subject=subject)
    return text + BEAMS[axes["beams"]] + LEVELS[axes["level"]] + INPUTS[axes["inputs"]]


def generate(size=CI_SIZE, seed=SEED):
    """[{id, prompt, axes, expected_constraint}], identical for the same size and seed."""
    rng = random.Random(seed)
    population = []
    for index in range(size):
        axes = {"field": rng.choice(sorted(FIELDS)), "deliverable": rng.choice(sorted(DELIVERABLES)),
                "inputs": rng.choice(sorted(INPUTS)), "beams": rng.choice(sorted(BEAMS)),
                "level": rng.choice(sorted(LEVELS)), "constraint": rng.choice(sorted(CONSTRAINTS)),
                "phrasing": rng.choice(sorted(PHRASINGS))}
        core = _core(rng, axes)
        prompt = PHRASINGS[axes["phrasing"]].format(core=core[0].upper() + core[1:] if axes["phrasing"] in
                                                   ("imperative", "terse") else core)
        suffix, expected = CONSTRAINTS[axes["constraint"]]
        prompt = prompt + suffix
        if axes["constraint"] == "delegation":
            prompt = "Run autonomously: " + prompt
        population.append({"id": f"POP-{index + 1:05d}", "prompt": prompt, "axes": axes,
                           "expected_constraint": expected})
    return population


def digest(population):
    return hashlib.sha256(json.dumps([p["prompt"] for p in population]).encode()).hexdigest()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--size", type=int, default=20)
    parser.add_argument("--seed", type=int, default=SEED)
    args = parser.parse_args()
    for request in generate(args.size, args.seed):
        print(request["id"], json.dumps(request["axes"]), request["prompt"], sep="\t")
