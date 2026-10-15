#!/usr/bin/env python
"""Compatibility entry point for the general, offline cross-section convention service.

Use ``ravel xsec supplied --request`` for selected calculation tables and
``ravel xsec correct --request`` for like-for-like correction contracts.
Process names never select denominators, perturbative orders or approximations.
"""
if not __package__:
    import sys
    from pathlib import Path
    sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
    __package__ = 'ravel.physics'

from ravel.physics.xsec_conventions import MissingInput, correction


def load_lo_ref(process=None, *, request=None, base='.'):
    if request is None:
        raise MissingInput('a supplied LO convention request is required; use ravel xsec supplied --request')
    from ravel.physics.cross_sections import lookup
    if request.get('convention',{}).get('order') != 'LO':
        raise ValueError('the selected denominator must declare LO')
    return lookup(request,base=base)


def hepi_grid(process=None, *, request=None, base='.', allow_network=False):
    if request is None:
        raise MissingInput('a supplied convention request is required; use ravel xsec lookup --request')
    from ravel.physics.cross_sections import lookup
    return lookup(request,base=base)


def slepton_k(mass=None, grid=None, lo_ref=None, *, contract=None, base='.', allow_network=False):
    """Retained import name; bare grids lack the conventions needed to define a ratio."""
    if contract is None:
        raise MissingInput('a supplied correction contract is required; use ravel xsec correct --request')
    return correction(contract,base)


def main_args(argv=None):
    import sys
    arguments = list(sys.argv[1:] if argv is None else argv)
    if any(flag in arguments for flag in ('--process','--mass','--sigma-lo-pb','--m-lsp','--allow-network')):
        error = SystemExit('missing_cross_section_input: use ravel xsec supplied or correct --request')
        error.reason_code = 'missing_cross_section_input'
        raise error
    from ravel.physics.cross_sections import main
    return main(arguments)


def main(argv=None):
    """Command-line entry point; the same refusal and delegation as ``main_args``."""
    return main_args(argv)

if __name__ == '__main__':
    raise SystemExit(main())
