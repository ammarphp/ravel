"""Finite, literal MA5 Initialize booking compiler; never interpret C++.

Supported source syntax is deliberately finite. A dynamic booking, conditional
booking population, non-linear/frequency plot or unresolved region expression
is an explicit missing implementation, not a smaller output denominator.
"""
import json
import math
import re


def _mask_strings(text):
    return re.sub(r'"(?:\\.|[^"\\])*"|\'(?:\\.|[^\'\\])*\'',
                  lambda m: ' ' * len(m[0]), text)


def _configuration(text, start, end):
    """Admit literal calls, preserving order and unknown inherited state.

    This is source interpretation only. The caller must separately bind the
    supported MC/REC/service definitions with configuration_sources().
    """
    code = _mask_strings(text)
    pattern = (r'\bPHYSICS\s*->\s*(mcConfig|recConfig)\s*\(\s*\)\s*\.\s*'
               r'(Reset|AddHadronicId|RemoveHadronicId|AddInvisibleId|RemoveInvisibleId)'
               r'\s*\(([^();{}]*)\)\s*;')
    matches = list(re.finditer(pattern, code))
    stripped = list(text)
    operations, mc, rec = [], None, None
    for m in matches:
        if not start <= m.start() < m.end() <= end:
            raise ValueError('physics configuration outside Initialize unsupported')
        prefix = code[start:m.start()]
        if prefix.count('{') != prefix.count('}'):
            raise ValueError('nested or deferred physics configuration unsupported')
        if prefix.rstrip() and prefix.rstrip()[-1] not in ';}':
            raise ValueError('standalone physics configuration statement required')
        target = 'mc' if m[1] == 'mcConfig' else 'rec'
        method, argument = m[2], text[m.start(3):m.end(3)].strip()
        if method == 'Reset':
            if argument: raise ValueError('argument-free configuration Reset required')
            arguments = []
            if target == 'mc': mc = {'hadronic_ids': set(), 'invisible_ids': set()}
            else: rec = {'delta_r_algorithm': True, 'delta_r': 0.5, 'sum_pt': 1.0, 'et_pt': 1.0}
        else:
            if target != 'mc' or not re.fullmatch(r'[+-]?(?:0|[1-9][0-9]*)', argument):
                raise ValueError('literal signed decimal MC configuration ID required')
            value = int(argument)
            if not -(2**31) <= value < 2**31:
                raise ValueError('configuration ID exceeds signed 32-bit source domain')
            arguments = [value]
            if mc is not None:
                key = 'hadronic_ids' if 'Hadronic' in method else 'invisible_ids'
                if method.startswith('Add'): mc[key].add(value)
                else: mc[key].discard(value)
        operations.append({'target': target, 'method': method, 'arguments': arguments})
        stripped[m.start():m.end()] = ' ' * (m.end() - m.start())
    remaining = _mask_strings(''.join(stripped))
    if re.search(r'\b(?:mcConfig|recConfig|RemoveHadronicId|RemoveInvisibleId)\b', remaining):
        raise ValueError('unknown or indirect physics configuration unsupported')
    if not operations: return ''.join(stripped), None
    if len(operations) > 16384: raise ValueError('finite configuration population required')
    if mc is not None: mc = {k: sorted(v) for k, v in mc.items()}
    return ''.join(stripped), {'operations': operations, 'mc_state_after_explicit_reset': mc,
                              'rec_state_after_explicit_reset': rec,
                              'native_effective_configuration_observed': False}


def configuration_sources(expected, declared, capture, base):
    """Bind the finite source semantics; no ABI or runtime authority is implied."""
    if 'physics_configuration' not in expected:
        if 'configuration_sources' in declared:
            raise ValueError('configuration sources without admitted operations')
        return
    if json.dumps(declared.get('physics_configuration'), sort_keys=True, allow_nan=False) != json.dumps(expected['physics_configuration'], sort_keys=True):
        raise ValueError('literal typed physics configuration declaration differs')
    keys = ('mc', 'rec', 'physics', 'identification')
    pins = declared.get('configuration_sources')
    if type(pins) is not dict or set(pins) != set(keys):
        raise ValueError('complete physics configuration source pins required')
    sources = {}
    for key in keys:
        _, raw = capture.pin(pins[key], base)
        sources[key] = re.sub(r'\s+', '', _mask_strings(clean(raw.decode())))
    required = {
        'mc': ('std::set<MAint32>invisible_ids_;', 'std::set<MAint32>hadronic_ids_;',
               'voidReset(){invisible_ids_.clear();hadronic_ids_.clear();}',
               'voidAddHadronicId(MAint32id){hadronic_ids_.insert(id);}',
               'voidRemoveHadronicId(MAint32id){hadronic_ids_.erase(id);}',
               'voidAddInvisibleId(MAint32id){invisible_ids_.insert(id);}',
               'voidRemoveInvisibleId(MAint32id){invisible_ids_.erase(id);}'),
        'rec': ('voidReset(){deltaRalgo_=true;deltaR_=0.5;sumPT_=1.;ET_PT_=1.;}',),
        'physics': ('MCconfig&mcConfig(){returnId->mcConfig();}',
                    'RECconfig&recConfig(){returnId->recConfig();}'),
        'identification': ('mcConfig_.hadronic_ids_.find(part.pdgid())',
                           'mcConfig_.invisible_ids_.find(part.pdgid())'),
    }
    if any(sources[key].count(fragment) != 1 for key in keys for fragment in required[key]):
        raise ValueError('unsupported pinned physics configuration API semantics')


def clean(text):
    # Preserve strings and remove both comment forms before matching calls.
    pattern = r'"(?:\\.|[^"\\])*"|\'(?:\\.|[^\'\\])*\'|//[^\n]*|/\*[\s\S]*?\*/'
    return re.sub(pattern, lambda m: ' ' * len(m[0]) if m[0].startswith(('//', '/*')) else m[0], text)


def split(text):
    parts, start, depth, quoted, escape = [], 0, 0, False, False
    for i, c in enumerate(text):
        if quoted:
            if escape: escape = False
            elif c == '\\': escape = True
            elif c == '"': quoted = False
        elif c == '"': quoted = True
        elif c in '({[': depth += 1
        elif c in ')}]': depth -= 1
        elif c == ',' and depth == 0: parts.append(text[start:i].strip()); start = i + 1
        if depth < 0: raise ValueError('unbalanced booking expression')
    if quoted or depth: raise ValueError('incomplete booking expression')
    return parts + [text[start:].strip()] if text.strip() else []


def string(text):
    if not re.fullmatch(r'"(?:\\.|[^"\\])*"', text):
        raise ValueError('literal booking title required')
    value = json.loads(text)
    if not value or value.strip() != value or len(value) > 256 or any(c in value for c in '/\\\n\r\x00"'):
        raise ValueError('nonempty safe native booking title required')
    return value


def compile_source(text):
    text = clean(text)
    starts = list(re.finditer(r'\bInitialize\s*\([^;{}]*\)\s*\{', text))
    if len(starts) != 1: raise ValueError('exactly one source Initialize body required')
    start = starts[0].end(); depth = 1; quoted = False; escape = False; end = None
    for i in range(start, len(text)):
        c = text[i]
        if quoted:
            if escape: escape = False
            elif c == '\\': escape = True
            elif c == '"': quoted = False
        elif c == '"': quoted = True
        elif c == '{': depth += 1
        elif c == '}':
            depth -= 1
            if depth == 0: end = i; break
    if end is None: raise ValueError('incomplete source Initialize body')
    text, configuration = _configuration(text, start, end)
    body = text[start:end]
    tokens = re.sub(r'"(?:\\.|[^"\\])*"', '""', body)
    if re.search(r'\b(if|for|while|switch|goto|do)\b|[?#]', tokens):
        raise ValueError('conditional, loop or preprocessed booking body unsupported')
    arrays = {}
    for m in re.finditer(r'(?:const\s+)?(?:std::)?string\s+(\w+)\s*\[\s*(\d*)\s*\]\s*=\s*\{([^{}]*)\}\s*;', body):
        if m[1] in arrays: raise ValueError('ambiguous region array')
        values = [string(x) for x in split(m[3])]
        if m[2] and int(m[2]) != len(values): raise ValueError('partial region array unsupported')
        # Reject later mutation: static local initializer must supply the full scope.
        if re.search(r'\b' + re.escape(m[1]) + r'\s*\[[^]]*\]\s*=', body[m.end():]):
            raise ValueError('mutated region scope unsupported')
        arrays[m[1]] = values
    calls = []
    pattern = r'\b(Add\w+)\s*\('
    for m in re.finditer(pattern, _mask_strings(body)):
        prefix = _mask_strings(body[:m.start()])
        if prefix.count('{') != prefix.count('}'):
            raise ValueError('nested or deferred source booking unsupported')
        if m[1] not in ('AddRegionSelection', 'AddCut', 'AddHisto'):
            raise ValueError('unsupported source booking method: ' + m[1])
        level = 1; quote = False; esc = False; stop = None
        for i in range(m.end(), len(body)):
            c = body[i]
            if quote:
                if esc: esc = False
                elif c == '\\': esc = True
                elif c == '"': quote = False
            elif c == '"': quote = True
            elif c == '(': level += 1
            elif c == ')':
                level -= 1
                if not level: stop = i; break
        if stop is None: raise ValueError('incomplete booking call')
        calls.append((m[1], split(body[m.end():stop])))
    # A registration in another function cannot be silently left out.
    if len(re.findall(pattern, _mask_strings(text))) != len(calls):
        raise ValueError('bookings outside Initialize unsupported')
    for name in arrays:
        references = len(re.findall(r'\b'+re.escape(name)+r'\b', re.sub(r'"(?:\\.|[^"\\])*"', '""', body)))
        if references != 1 + sum(args.count(name) for _, args in calls):
            raise ValueError('region scope used outside literal bookings')
    regions, cuts, histograms = [], {}, []
    names = set()
    def scope(args, index):
        if len(args) == index: result = list(regions)
        elif len(args) != index + 1: raise ValueError('unknown booking overload')
        elif args[index] in arrays: result = list(arrays[args[index]])
        else: result = [string(args[index])]
        if not result or len(set(result)) != len(result) or set(result) - set(regions):
            raise ValueError('complete known unique region scope required')
        return result
    for method, args in calls:
        if method == 'AddRegionSelection':
            if len(args) != 1: raise ValueError('literal region overload required')
            name = string(args[0])
            if name in cuts or any(cuts.values()) or histograms:
                raise ValueError('unique regions must precede cuts and plots')
            regions.append(name); cuts[name] = []
        elif method == 'AddCut':
            if not args: raise ValueError('named literal cut required')
            name = string(args[0]); selected = scope(args, 1)
            if ('cut', name) in names: raise ValueError('duplicate native cut booking')
            names.add(('cut', name))
            for region in selected: cuts[region].append(name)
        else:
            if len(args) not in (4, 5): raise ValueError('unknown histogram overload')
            name = string(args[0]); selected = scope(args, 4)
            if ('histo', name) in names: raise ValueError('duplicate native histogram booking')
            names.add(('histo', name))
            if not re.fullmatch(r'[1-9]\d*', args[1]): raise ValueError('literal bin count required')
            values = []
            for x in args[2:4]:
                if not re.fullmatch(r'[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?', x):
                    raise ValueError('literal finite axis bound required')
                values.append(float(x))
            if not all(map(math.isfinite, values)) or not values[1] > values[0] or int(args[1]) > 100000:
                raise ValueError('valid finite linear histogram axis required')
            histograms.append(dict(name=name, nbins=int(args[1]), xmin=values[0], xmax=values[1], regions=selected))
    if not 1 <= len(regions) <= 1024 or len(histograms) > 4096 or sum(map(len, cuts.values())) > 16384:
        raise ValueError('finite complete booking population required')
    result = {'regions': regions, 'cuts': cuts, 'histograms': histograms}
    if configuration is not None: result['physics_configuration'] = configuration
    return result
