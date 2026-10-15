"""One explicit adapter identity per engine; source contracts supply native syntax."""
from dataclasses import dataclass

from . import formats


@dataclass(frozen=True)
class DecayProgram:
    program: str
    model_families: tuple

    def _point(self, point):
        from ravel.physics.higgs_decays import validate_point
        point = validate_point(point)
        if point['program'] != self.program:
            raise ValueError('selected adapter program differs from model point')
        return point

    def render_card(self, point, contract):
        return formats.render(self._point(point), contract)

    def parse_outputs(self, point, contract, outputs):
        return formats.parse(self._point(point), contract, outputs)

    def output_names(self, contract):
        formats.validate_format(contract, self.program, contract['version'], contract['order'])
        return formats.output_names(contract)


class HDecay(DecayProgram):
    def __init__(self):
        super().__init__('HDECAY', ('SM',))


class EHDecay(DecayProgram):
    def __init__(self):
        super().__init__('eHDECAY', ('EFT',))


class TwoHDecay(DecayProgram):
    def __init__(self):
        super().__init__('2HDECAY', ('2HDM',))


class SingletHDecay(DecayProgram):
    def __init__(self):
        super().__init__('sHDECAY', ('singlet',))


class NTwoHDecay(DecayProgram):
    def __init__(self):
        super().__init__('N2HDECAY', ('N2HDM',))


class ProphecyFourF(DecayProgram):
    def __init__(self):
        super().__init__('Prophecy4f', ('four_fermion',))

    def _point(self, point):
        point = super()._point(point)
        if any(s['coverage'] != 'four_fermion' for s in point['scalars']):
            raise ValueError('Prophecy4f supplies a four_fermion sector, not a complete scalar width')
        return point


class TwoHDMC(DecayProgram):
    def __init__(self):
        super().__init__('2HDMC', ('2HDM',))


class FeynHiggs(DecayProgram):
    def __init__(self):
        super().__init__('FeynHiggs', ('MSSM',))

    def scope_tools_job(self, *args, **kwargs):
        raise ValueError('awaits scope-tools FeynHiggs')
