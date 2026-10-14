"""Full linear MA5 SAF output reader, preserving both raw sign channels.

Scoped to Histo/Counter/RegionSelection in the pinned OSU outputs. Does not
execute analyses, normalize distributions, clip negative bins or invent bin
second moments/cross covariance absent from the supplied native format.
"""
import math
import re

STATS = ('nevents', 'sumwentries', 'nentries', 'sumw', 'sumw2', 'sumwx', 'sumwx2')


def tree(text):
    roots = []
    stack = []
    for line in text.splitlines():
        # SAF writers quote literal titles; a # inside those quotes is data.
        # Comments begin only outside a title. Escaped quotes are not part of
        # this finite SAF title grammar and are refused by title().
        quoted = False
        for i, char in enumerate(line):
            if char == '"': quoted = not quoted
            elif char == '#' and not quoted:
                line = line[:i]; break
        if quoted: raise ValueError('Unterminated quoted native SAF title')
        line = line.strip()
        if not line:
            continue
        tag = re.fullmatch(r'<(/?)([A-Za-z]+)>', line)
        if tag:
            closing, name = tag.groups()
            if closing:
                if not stack or stack[-1]['tag'] != name:
                    raise ValueError('Malformed or crossed native SAF tags')
                node = stack.pop()
                (stack[-1]['children'] if stack else roots).append(node)
            else:
                stack.append({'tag': name, 'lines': [], 'children': []})
        else:
            if not stack:
                raise ValueError('Native SAF text outside a block')
            stack[-1]['lines'].append(line)
    if stack:
        raise ValueError('Incomplete native SAF block')
    if (len(roots) < 2 or roots[0]['tag'] != 'SAFheader' or roots[-1]['tag'] != 'SAFfooter'
            or roots[0]['lines'] or roots[-1]['lines'] or roots[0]['children'] or roots[-1]['children']):
        raise ValueError('Exact complete SAF header/footer required')
    if any(n['tag'] in ('SAFheader', 'SAFfooter') for n in roots[1:-1]):
        raise ValueError('Duplicate native SAF framing')
    return roots[1:-1]


def title(line):
    if not line.startswith('"') or not line.endswith('"') or line.count('"') != 2:
        raise ValueError('Exact quoted source output title required')
    return line[1:-1]


def pair(line, *, counts=False, signed_moment=False):
    tokens = line.split()
    if len(tokens) != 2:
        raise ValueError('Complete two-channel native row required')
    if counts:
        if any(not re.fullmatch(r'\+?\d+', v) for v in tokens):
            raise ValueError('Exact integer native entry counters required')
        return [int(v) for v in tokens]
    values = [float(v) for v in tokens]
    if any(not math.isfinite(v) or (v < 0 and not signed_moment) for v in values):
        raise ValueError('Finite nonnegative raw sign-channel magnitude required')
    return values


def histograms(text):
    nodes = tree(text)
    result = []
    seen = set()
    for node in nodes:
        if node['tag'] != 'Histo' or node['lines']:
            raise ValueError('Only complete source-defined linear histograms admitted')
        children = node['children']
        if [c['tag'] for c in children] != ['Description', 'Statistics', 'Data']:
            raise ValueError('Complete ordered histogram sections required')
        desc, stats, data = children
        if any(c['children'] for c in children) or len(desc['lines']) < 3:
            raise ValueError('Complete native histogram description and regions required')
        name = title(desc['lines'][0])
        if name in seen:
            raise ValueError('Duplicate histogram hides the requested output denominator')
        seen.add(name)
        axis = desc['lines'][1].split()
        if len(axis) != 3:
            raise ValueError('Complete native linear axis required')
        n = float(axis[0]); lo, hi = map(float, axis[1:])
        if not math.isfinite(n) or not n.is_integer() or not 1 <= n <= 100000 or not all(map(math.isfinite, [lo, hi])) or not hi > lo:
            raise ValueError('Invalid native histogram binning')
        n = int(n)
        regions = desc['lines'][2:]
        if any(not r or '"' in r for r in regions) or len(set(regions)) != len(regions):
            raise ValueError('Unique explicit native histogram regions required')
        if len(stats['lines']) != 7 or len(data['lines']) != n+2:
            raise ValueError('Complete native moments, bins and both flows required')
        moments = [pair(v, counts=i in (0, 2), signed_moment=i == 5)
                   for i, v in enumerate(stats['lines'])]
        # sumwx may be signed when x is negative. Neither value moment is a
        # substitute for unavailable per-bin second moments.
        values = [pair(v) for v in data['lines']]
        channels = {}
        for i, sign in enumerate(('positive', 'negative')):
            channels[sign] = {**{k: moments[j][i] for j, k in enumerate(STATS)},
                              'underflow': values[0][i], 'overflow': values[-1][i],
                              'array': [v[i] for v in values[1:-1]]}
        result.append({'name': name, 'nbins': n, 'xmin': lo, 'xmax': hi,
                       'regions': regions, **channels,
                       'native_numeric_tokens': {'statistics': [x.split() for x in stats['lines']],
                                                 'data': [x.split() for x in data['lines']]},
                       'native_moment_definitions': {'sumwx': 'sum(value*weight)',
                                                     'sumwx2': 'sum(value^2*weight)',
                                                     'sumw2': 'sum(weight^2)'},
                       'per_bin_sumw2': None, 'cross_bin_covariance': None,
                       'raw_channel_semantics': 'Two native sign channels retained separately; no summary clipping or second-moment subtraction'})
    return result


def counters(text):
    nodes = tree(text)
    if not nodes or nodes[0]['tag'] != 'InitialCounter' or any(n['tag'] != 'Counter' for n in nodes[1:]):
        raise ValueError('Complete native initial counter and ordered cuts required')
    results = []
    for node in nodes:
        if node['children'] or len(node['lines']) != 4:
            raise ValueError('Complete named counter with three sign-channel rows required')
        name = title(node['lines'][0])
        values = [pair(v, counts=i == 0) for i, v in enumerate(node['lines'][1:])]
        results.append({'name': name, 'positive': dict(zip(('nentries', 'sumw', 'sumw2'), [v[0] for v in values])),
                        'negative': dict(zip(('nentries', 'sumw', 'sumw2'), [v[1] for v in values])),
                        'native_numeric_tokens': [v.split() for v in node['lines'][1:]]})
    if len({r['name'] for r in results}) != len(results):
        raise ValueError('Duplicated native cut counter')
    return {'initial': results[0], 'cuts': results[1:]}


def regions(text):
    nodes = tree(text)
    if len(nodes) != 1 or nodes[0]['tag'] != 'RegionSelection' or nodes[0]['children']:
        raise ValueError('Exactly one explicit region selection required')
    names = [title(v) for v in nodes[0]['lines']]
    if not names or len(set(names)) != len(names):
        raise ValueError('Complete unique region denominator required')
    return names
