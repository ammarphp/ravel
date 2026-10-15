# SPDX-License-Identifier: Apache-2.0
"""Separate-process density protocol; run only in the selected generator environment.

This entry point does not import RAVEL. The GPL density binding stays entirely
in this external process. Only JSON density values and metadata cross the boundary.
"""
import json
import math
import sys


def main():
    request = json.load(sys.stdin)
    if not isinstance(request,dict) or set(request) != {'set','member','x','q_gev'}:
        raise ValueError('set, member, x and q_gev fields required')
    if not isinstance(request['set'],str) or not request['set'].strip() or type(request['member']) is not int or request['member']<0:
        raise ValueError('PDF set and nonnegative integer member required')
    for key in ('x','q_gev'):
        values = request[key]
        if not isinstance(values,list) or len(values)<2 or any(type(v) not in (float,int) or not math.isfinite(v) or v<=0 for v in values):
            raise ValueError('finite positive grid nodes required')
        if any(a>=b for a,b in zip(values,values[1:])) or (key=='x' and values[-1]>1):
            raise ValueError('strictly increasing grid required, x <= 1')
    if len(request['x'])*len(request['q_gev'])>100000:
        raise ValueError('grid exceeds 100000 points')
    import lhapdf
    lhapdf.setVerbosity(0)
    pdf = lhapdf.mkPDF(request['set'],request['member'])
    if 22 not in pdf.flavors(): raise ValueError('PDF set has no photon density')
    if any(not pdf.inRangeXQ(x,q) for x in request['x'] for q in request['q_gev']):
        raise ValueError('grid outside PDF validity domain; extrapolation refused')
    values = [[pdf.xfxQ(22,x,q) for q in request['q_gev']] for x in request['x']]
    if any(not math.isfinite(v) or v<0 for row in values for v in row):
        raise ValueError('nonfinite or negative photon density')
    result = dict(request,schema_version=1,set=lhapdf.getPDFSet(request['set']).name,
                  member=pdf.memberID,flavours=list(pdf.flavors()),
                  lhapdf_version=lhapdf.version(),values=values)
    print(json.dumps(result,allow_nan=False))


if __name__ == '__main__':
    try: main()
    except Exception as exc:
        print(str(exc),file=sys.stderr)
        raise SystemExit(1)
