"""Top-level alias for the custody response recorder."""
def main(argv=None):
    import sys
    from . import gate_wiring
    return gate_wiring.main(['respond', *(sys.argv[1:] if argv is None else argv)])
