"""Inert operator notifier for the canaries: appends one line per call to the file in argv[1].

It records only the arguments it was given (run name and state code), as a real notifier would
send them; it never reads the run or the network.
"""
import json
import sys
import time

with open(sys.argv[1], 'a') as stream:
    stream.write(json.dumps({'argv': sys.argv[2:], 'monotonic_ns': time.monotonic_ns()}) + '\n')
