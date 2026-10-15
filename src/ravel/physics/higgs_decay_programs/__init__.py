"""Decay-program identities without importing or launching upstream native tools."""
from .adapters import (EHDecay, FeynHiggs, HDecay, NTwoHDecay, ProphecyFourF,
                       SingletHDecay, TwoHDecay, TwoHDMC)

ADAPTERS = {engine.program: engine for engine in (
    HDecay(), EHDecay(), TwoHDecay(), SingletHDecay(), NTwoHDecay(),
    ProphecyFourF(), TwoHDMC(), FeynHiggs(),
)}
