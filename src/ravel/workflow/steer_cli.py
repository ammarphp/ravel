"""Top-level alias for the custody steering recorder."""
def main(argv=None):
    import sys
    from . import gate_wiring
    return gate_wiring.main(['steer', *(sys.argv[1:] if argv is None else argv)])
