"""Bound trusted FeynRules model source to evaluated checks and fresh UFO output.

The resulting literal external card is an explicit source point for a separately
approved model-tool-bridge study. Native derivation, tree numerical consistency,
widths and physical model validity remain distinct claims.
"""
import argparse
import ast
import json
import math
import os
from pathlib import Path
import re
from tokenize import TokenError

from ravel.physics import model_tool_bridge as custody
from ravel.physics import model_provider_bridge as provider

SCOPE = 'Trusted source/model restrictions, evaluated kinetic and returned mass checks, and native UFO export custody'
REQUIRED_UFO = ('__init__.py', 'object_library.py', 'parameters.py', 'particles.py',
                'couplings.py', 'vertices.py', 'lorentz.py')


def validate(task):
    custody._keys(task, ('config',), 'model-derivation-bridge task')
    if not isinstance(task['config'], str) or not task['config'].strip():
        raise ValueError('source-bound derivation config required')
    return dict(task)


def _relative_files(values, suffix, minimum, maximum):
    if (not isinstance(values, list) or not minimum <= len(values) <= maximum
            or any(not isinstance(name, str) for name in values) or len(set(values)) != len(values)):
        raise ValueError('bounded unique source-file list required')
    for name in values:
        if not isinstance(name, str):
            raise ValueError('relative source-file names required')
        path = Path(name)
        if path.is_absolute() or path.as_posix() != name or '..' in path.parts or path.suffix != suffix:
            raise ValueError('source file must remain inside its declared tree')


def validate_config(c):
    if isinstance(c,dict) and c.get("operation") == "sarah-source-ufo":
        from ravel.physics import model_sarah
        return model_sarah.validate_derivation(c)
    compatibility=c.get('ufo_python_compatibility','none')
    from ravel.physics import ufo_interop
    if compatibility not in ('none',ufo_interop.POLICY):
        raise ValueError('explicit supported UFO Python compatibility policy required')
    if 'expected_provider_digest' in c and (not isinstance(c['expected_provider_digest'], str)
                                             or not re.fullmatch('[0-9a-f]{64}', c['expected_provider_digest'])):
        raise ValueError('expected provider digest must be a sha256 hex digest')
    custody._keys({k:v for k,v in c.items() if k not in ('ufo_python_compatibility','physical_checks','two_gauge_checks',
                                                         'expected_provider_digest')}, ('schema_version', 'operation', 'source', 'kernel', 'application_metadata',
        'provider_tree', 'model_tree', 'model_files', 'restrictions', 'lagrangian_symbol',
        'trusted_provider_source', 'trusted_model_source', 'provider_readiness_receipt', 'provider_readiness_run',
        'expected_kernel_version', 'expected_provider_version', 'max_seconds', 'max_ram_mib'), 'derivation config')
    if type(c['schema_version']) is not int or c['schema_version'] != 1 or c['operation'] != 'feynrules-source-ufo':
        raise ValueError('qualified operation is feynrules-source-ufo schema1')
    if c['trusted_provider_source'] is not True or c['trusted_model_source'] is not True:
        raise ValueError('explicitly trusted executable provider/model source required')
    if not isinstance(c['source'], str) or not c['source'].strip():
        raise ValueError('source attribution required')
    if (type(c['expected_kernel_version']) not in (int, float)
            or c['expected_kernel_version'] not in provider.READINESS_KERNEL_VERSIONS
            or c['expected_provider_version'] != '2.3.49'):
        raise ValueError('derivation requires an explicitly qualified Wolfram14.3 or15.0/FeynRules2.3.49 binding')
    custody._keys(c['provider_readiness_run'], ('path', 'attempt_id', 'attempt_record'), 'qualified provider run')
    if not isinstance(c['provider_readiness_run']['path'], str) or not c['provider_readiness_run']['path']:
        raise ValueError('original actually executed provider run required')
    if not isinstance(c['provider_readiness_run']['attempt_id'], str) or not c['provider_readiness_run']['attempt_id']:
        raise ValueError('original provider attempt identity required')
    _relative_files(c['model_files'], '.fr', 1, 4)
    _relative_files(c['restrictions'], '.rst', 0, 8)
    if not isinstance(c['lagrangian_symbol'], str) or not re.fullmatch('[A-Za-z][A-Za-z0-9$]{0,63}', c['lagrangian_symbol']):
        raise ValueError('one named Global Lagrangian symbol required; expressions are forbidden')
    if type(c['max_seconds']) is not int or not 1 <= c['max_seconds'] <= 900:
        raise ValueError('derivation native time ceiling must be1..900seconds')
    if type(c['max_ram_mib']) is not int or not 512 <= c['max_ram_mib'] <= 8192:
        raise ValueError('derivation sampled RAM ceiling must be512..8192MiB')
    if 'physical_checks' in c:
        from ravel.physics import model_physical_checks
        model_physical_checks.validate(c['physical_checks'])
    if 'two_gauge_checks' in c:
        custody._keys(c['two_gauge_checks'], ('new_terms_symbol',), 'two-gauge checks')
        symbol = c['two_gauge_checks']['new_terms_symbol']
        if not isinstance(symbol, str) or not re.fullmatch('[A-Za-z][A-Za-z0-9$]{0,63}', symbol):
            raise ValueError('two-gauge checks need the named Global symbol holding the new terms')
    return c


def _load(task, base):
    validate(task)
    path = custody._regular(task['config'], base)
    return path, validate_config(custody._read(path))


def qualified_receipt(receipt, expected_kernel_version=None):
    """Check the pinned prior native readiness result, without claiming authentication."""
    if receipt.get("native_provider",{}).get("provider_kind")=="sarah":
        from ravel.physics import model_sarah
        return model_sarah.qualified_receipt(receipt,expected_kernel_version)
    native = receipt.get('native_provider', {})
    version = native.get('kernel_version')
    if (type(version) not in (int, float) or version not in provider.READINESS_KERNEL_VERSIONS
            or (expected_kernel_version is not None and version != expected_kernel_version)):
        raise ValueError('prior qualified provider/runtime differs')
    if (receipt.get('status') != 'passed' or receipt.get('physics_validated') is not False
            or receipt.get('model_calculation_performed') is not False
            or type(receipt.get('generated_events')) is not int or receipt['generated_events'] != 0
            or receipt.get('checks', {}).get('passed') is not True
            or set(receipt.get('checks', {}).get('checks', {})) != set(provider.adjudicate({},
                {'expected_kernel_version':version,'expected_provider_version':'2.3.49'}, Path('/unused'),0)['checks'])
            or not all(value is True for value in receipt['checks']['checks'].values())):
        raise ValueError('actual passing source-bound provider readiness receipt required')
    if (native.get('provider_version') != '2.3.49'
            or not isinstance(native.get('provider_root'), str) or not native['provider_root']):
        raise ValueError('prior qualified provider/runtime differs')
    execution = receipt.get('native_execution', {})
    if (type(execution.get('returncode')) is not int or execution['returncode'] != 0
            or execution.get('resource_violation') is not None
            or not isinstance(execution.get('command'), list) or not execution['command']):
        raise ValueError('prior actual successful bounded kernel execution required')
    return receipt


def _qualification(c, base):
    """Read actual closed-stage commitments, never mutable-copy/path identity alone."""
    from ravel.workflow import accepted_prior_science
    binding = c['provider_readiness_run']; root = custody._regular(binding['path'], base, directory=True)
    prior = accepted_prior_science.accepted(root, claim_scope='provider_readiness',
        mode='model-provider-bridge', attempt_id=binding['attempt_id'])
    # The ordinary study binds these journal, head and retained evidence bytes.
    # Re-running inputs at dispatch replays the original source-bound reuse gate,
    # including any later hold, while this study retains its fresh launch guards.
    review_proof = [custody._regular(p, root) for p in prior['paths']]
    stage = prior['receipt']
    if stage.get('status') != 'succeeded' or stage.get('attempt_id') != binding['attempt_id']:
        raise ValueError('original provider successful execution commitment changed')
    record = custody._pin(binding['attempt_record'], base)
    if record != custody._regular(stage['attempt_record'], root):
        raise ValueError('qualified provider attempt record differs')
    spec = custody._read(root/'inputs/science.json'); plan = custody._read(root/'inputs/science-plan.json')
    approval = custody._read(root/'inputs/science-approval.json')
    if (spec.get('schema_version') != 2 or spec.get('mode') != 'model-provider-bridge'
            or approval.get('schema_version') != 2 or approval.get('expert_review') is not False
            or approval.get('plan_sha256') != custody._hash(root/'inputs/science-plan.json')
            or approval.get('checkin_sha256') != custody._hash(root/'inputs/checkin1.json')):
        raise ValueError('qualified provider actual approval differs')
    config_path = custody._regular(spec['task']['config'], Path(plan['base_dir']))
    pin = stage['input_snapshot'].get(str(config_path), {})
    if (pin.get('kind') != 'file' or len(pin.get('files', [])) != 1
            or pin['files'][0].get('sha256') != custody._hash(config_path)):
        raise ValueError('original qualified config is absent from closed-stage bytes')
    original = provider.validate_config(custody._read(config_path))
    expected_readiness='wolfram-sarah-readiness' if c['operation']=='sarah-source-ufo' else 'wolfram-feynrules-readiness'
    if original['operation']!=expected_readiness:
        raise ValueError('provider readiness operation differs from model derivation')
    if (original['expected_kernel_version'] != c['expected_kernel_version']
            or original['expected_provider_version'] != c['expected_provider_version']):
        raise ValueError('derivation runtime version differs from original qualified readiness')
    fr, manifest, files = custody._tree(original['provider_tree'], config_path.parent)
    if (original['kernel'] != c['kernel'] or original['application_metadata'] != c['application_metadata']):
        raise ValueError('current kernel/application pins differ from originally qualified bytes')
    result = custody._pin(c['provider_readiness_receipt'], base)
    if len(stage['outputs']) != 1 or result != custody._regular(Path(stage['outputs'][0])/'model-provider-bridge.json', root):
        raise ValueError('qualified output is not the actual closed-stage provider result')
    previous = qualified_receipt(custody._read(result), c['expected_kernel_version'])
    process = custody._read(result.parent/'native-process.json')
    if not provider.adjudicate(previous['native_provider'],original,
            Path(previous['native_provider']['provider_root']),process['pid'])['passed']:
        raise ValueError('actual qualified native readiness checks no longer pass')
    if previous['native_execution']['command'][0] != str(custody._pin(original['kernel'], config_path.parent)):
        raise ValueError('original qualified kernel command differs')
    proof = [*review_proof, record, config_path, manifest, root/'execution_state.json', root/'inputs/science.json',
             root/'inputs/science-plan.json', root/'inputs/science-approval.json', root/'inputs/checkin1.json',
             root/'inputs/physics_review_policy.json', result.parent/'native-process.json', *files]
    for name, snapshot in stage['input_snapshot'].items():
        dependency = custody._regular(name,root,directory=snapshot['kind']=='directory')
        if dependency.is_dir():
            proof.extend(p for p in dependency.rglob('*') if p.is_file())
        else:
            proof.append(dependency)
    proof.extend(p for p in result.parent.rglob('*') if p.is_file())
    return custody.source_tree(fr), proof


def inputs(task, base):
    path, c = _load(task, base)
    if c["operation"]=="sarah-source-ufo":
        from ravel.physics import model_sarah
        return model_sarah.derivation_inputs(task,base)
    kernel = custody._pin(c['kernel'], path.parent)
    if not os.access(kernel, os.X_OK):
        raise ValueError('native kernel is not executable')
    metadata = custody._pin(c['application_metadata'], path.parent)
    fr, fr_manifest, fr_files = custody._tree(c['provider_tree'], path.parent)
    model, model_manifest, model_files = custody._tree(c['model_tree'], path.parent)
    for name in ('FeynRules.m', 'FeynRulesPackage.m', 'ToolBox.m'):
        if not (fr/name).is_file():
            raise ValueError('missing qualified provider source ' + name)
    version = re.search(r'FR\$VersionNumber\s*=\s*"([^"]+)"', (fr/'FeynRulesPackage.m').read_text())
    if not version or version.group(1) != c['expected_provider_version']:
        raise ValueError('provider source version differs')
    for name in c['model_files'] + c['restrictions']:
        custody._regular(name, model)
    readiness = custody._pin(c['provider_readiness_receipt'], path.parent)
    qualified_source, proof = _qualification(c, path.parent)
    if qualified_source != custody.source_tree(fr):
        raise ValueError('qualified source bytes differ from the current derivation pins')
    physical_inputs=[]
    if 'physical_checks' in c:
        from ravel.physics import model_physical_checks
        physical_inputs=model_physical_checks.inputs(c['physical_checks'],path.parent)
    sources = list(Path(__file__).resolve().parents[1].rglob('*.py'))
    return sorted(set([path, kernel, metadata, fr_manifest, model_manifest, readiness,
                       *fr_files, *model_files, *proof, *physical_inputs, *sources]))


# Independent witnesses for the two FeynRules quadratic-term diagnostics that the
# Standard Model itself triggers. CheckKineticTermNormalisation compares a Dirac
# kinetic coefficient with I after replacing a chiral projector by 1/2, so a
# left-handed field written in Dirac notation (the SM neutrinos) is reported as
# non-canonical. GetMassSpectrum reports a scalar or vector mass term with a
# positive numerical coefficient as having the wrong sign, which includes a
# coefficient that vanishes up to rounding (the Goldstone terms of the Higgs
# potential at its minimum). The witnesses recompute both numbers per field pair.
DIAGNOSTIC_WITNESS_SCRIPT = (
    'ravelTermList[x_] := With[{e = Expand[x]}, If[e === 0, {}, If[Head[e] === Plus, List @@ e, {e}]]];\n'
    'kinList = ravelTermList[kinTerms]; kinContent = Sort /@ (FeynRules`GetFieldContent /@ kinList);\n'
    'massList = ravelTermList[FeynRules`GetMassTerms[lag, FeynRules`FlavorExpand -> True]];\n'
    'massContent = Sort /@ (FeynRules`GetFieldContent /@ massList);\n'
    'ravelConjugatePair[p_] := Length[p] === 2 && p[[1]] === FeynRules`anti[p[[2]]];\n'
    'ravelProjectors = FeynRules`ProjP | FeynRules`ProjM;\n'
    'ravelUnprojected[t_] := FeynRules`NumericalValue[t /. Dot[FeynRules`del[a_, mu_], b_] :> -Dot[a, FeynRules`del[b, mu]]\n'
    ' /. FeynRules`del[__] -> 1 /. _?FeynRules`FieldQ -> 1 /. Dot[1, 1] -> 1 //. FeynRules`TensDot[__][__] -> 1\n'
    ' //. FeynRules`Ga[__] -> 1 //. (FeynRules`ProjP | FeynRules`ProjM)[__] -> 1];\n'
    'fermionKinetic = Map[Function[p, Module[{sel = Pick[kinList, kinContent, p]},\n'
    ' <|"fields" -> Map[ToString[#, InputForm]&, p], "monomials" -> Length[sel],\n'
    '  "projector_counts" -> Map[Count[#, ravelProjectors, {0, Infinity}, Heads -> True]&, sel],\n'
    '  "projectors" -> Union[Map[ToString, Cases[sel, ravelProjectors, {0, Infinity}, Heads -> True]]],\n'
    '  "unprojected_coefficient" -> num[ravelUnprojected[Total[sel]]],\n'
    '  "in_mass_terms" -> MemberQ[massContent, p]|>]],\n'
    ' Select[DeleteDuplicates[kinContent], ravelConjugatePair[#] && TrueQ[FeynRules`DiracFieldQ[#[[1]]]]&]];\n'
    'massCoefficients = Map[Function[p, <|"fields" -> Map[ToString[#, InputForm]&, p],\n'
    ' "coefficient" -> num[FeynRules`NumericalValue[Total[Pick[massList, massContent, p]] /. _?FeynRules`FieldQ -> 1]]|>],\n'
    ' Select[DeleteDuplicates[massContent], ravelConjugatePair[#] && (TrueQ[FeynRules`ScalarFieldQ[#[[1]]]]\n'
    '  || TrueQ[FeynRules`VectorFieldQ[#[[1]]]])&]];\n')
KINETIC_WARNING = re.compile(r'Kinetic term for \{([^{},]+), ([^{},]+)\} seems not to be correctly normalized')
MASS_WARNING = re.compile(r'mass term for \{([^{},]+), ([^{},]+)\}\s*seems not to have the correct sign')
VANISHING = 1e-9
PROVIDER_PINS = 'feynrules-provider-pins.json'


def _complex(value):
    if (not isinstance(value, dict) or set(value) != {'real', 'imag'}
            or any(type(value[k]) not in (int, float) or not math.isfinite(value[k]) for k in value)):
        return None
    return complex(value['real'], value['imag'])


def _warnings(printed, pattern):
    lines = [line for line in printed.splitlines() if 'Warning' in line or 'non numerical' in line]
    flagged = [m.groups() for m in map(pattern.search, lines) if m]
    other = [line for line in lines if not pattern.search(line)]
    return flagged, other


def kinetic_diagnostics(native):
    """Adjudicate CheckKineticTermNormalisation: True, or every warning is a chiral field at canonical norm."""
    printed, rows = native.get('kinetic_printed'), native.get('fermion_kinetic_witness')
    if not isinstance(printed, str) or not isinstance(rows, list):
        return {'passed': False, 'failures': ['printed kinetic diagnostics or the chiral witness were not captured']}
    flagged, other = _warnings(printed, KINETIC_WARNING)
    expression = native.get('kinetic_result_expression')
    failures = [f'unadjudicated kinetic diagnostic: {line}' for line in other]
    if expression == 'True' and native.get('kinetic_result') is True and not flagged:
        return {'passed': not failures, 'failures': failures, 'waived': []}
    if expression != 'Null' or not flagged:
        failures.append(f'CheckKineticTermNormalisation returned {expression} without per-field warnings')
    witness = {}
    for row in rows:
        if isinstance(row, dict) and isinstance(row.get('fields'), list):
            witness[frozenset(row['fields'])] = row
    waived = []
    for pair in flagged:
        row = witness.get(frozenset(pair))
        value = _complex((row or {}).get('unprojected_coefficient'))
        counts = (row or {}).get('projector_counts')
        chiral = (row is not None and type(row.get('monomials')) is int and row['monomials'] >= 1
                  and isinstance(counts, list) and len(counts) == row['monomials'] and all(c == 1 for c in counts)
                  and isinstance(row.get('projectors'), list) and len(row['projectors']) == 1
                  and row.get('in_mass_terms') is False)
        canonical = value is not None and abs(value - 1j) <= VANISHING
        if chiral and canonical:
            waived.append({'fields': list(pair), 'projector': row['projectors'][0],
                           'reason': 'massless field with one chiral projector in every kinetic monomial; '
                                     'the coefficient with the projector removed is the canonical Dirac value I'})
        else:
            failures.append(f'kinetic term for {{{pair[0]}, {pair[1]}}} is not canonically normalized'
                            + ('' if row else ' (no witness row)'))
    return {'passed': not failures, 'failures': failures, 'waived': waived,
            'rule': 'A kinetic warning is waived only for a massless field whose every kinetic monomial carries one '
                    'chiral projector of a single kind and whose coefficient, with the projector set to 1, equals I.'}


def mass_diagnostics(native):
    """Adjudicate GetMassSpectrum sign warnings: waived only when the mass coefficient vanishes."""
    printed, rows = native.get('mass_printed'), native.get('mass_coefficients')
    if not isinstance(printed, str) or not isinstance(rows, list):
        return {'passed': False, 'failures': ['printed mass diagnostics or mass coefficients were not captured']}
    flagged, other = _warnings(printed, MASS_WARNING)
    failures = [f'unadjudicated mass diagnostic: {line}' for line in other]
    values = {}
    for row in rows:
        if isinstance(row, dict) and isinstance(row.get('fields'), list):
            values[frozenset(row['fields'])] = _complex(row.get('coefficient'))
    scale = max((abs(v) for v in values.values() if v is not None), default=0.0)
    waived = []
    for pair in flagged:
        value = values.get(frozenset(pair))
        if value is not None and scale > 0 and abs(value) <= VANISHING * scale:
            waived.append({'fields': list(pair), 'coefficient': [value.real, value.imag], 'scale': scale,
                           'reason': 'the mass term vanishes at this parameter point; a zero term has no sign'})
        else:
            failures.append(f'mass term for {{{pair[0]}, {pair[1]}}} has the wrong sign')
    return {'passed': not failures, 'failures': failures, 'waived': waived,
            'rule': f'A sign warning is waived only when the numerical mass coefficient is at most {VANISHING:g} '
                    'times the largest scalar or vector mass coefficient.'}


def provider_digest(tree):
    """Digest of a provider source tree's {relative path: sha256} map."""
    from ravel.physics.model_admission import _digest
    return _digest(tree['files'])


def pinned_provider_digest(version):
    from ravel.paths import package_data_path
    pins = json.loads(Path(package_data_path('model_admission', PROVIDER_PINS)).read_text())
    row = pins['feynrules'].get(version)
    if row is None:
        raise ValueError(f'no pinned FeynRules {version} provider digest')
    return row['provider_tree_digest']


def provider_pin(fr, version):
    """The packaged digest for this FeynRules version, after checking the supplied tree has it."""
    pin = pinned_provider_digest(version)
    observed = provider_digest(custody.source_tree(fr))
    if observed != pin:
        raise ValueError(f'FeynRules {version} source tree digest {observed} differs from the pinned {pin}')
    return pin


def script(c, fr, model, exported, receipt):
    """Fixed API calls; only literal paths and one validated source symbol vary."""
    validate_config(c)
    if c["operation"]=="sarah-source-ufo":
        from ravel.physics import model_sarah
        return model_sarah.derivation_script(c,fr,model,exported,receipt)
    q = lambda value: json.dumps(str(value), ensure_ascii=False)
    lag = 'Global`' + c['lagrangian_symbol']
    models = ', '.join(q(model/name) for name in c['model_files'])
    restrictions = ''.join('loadRestriction['+q(model/name)+'];\n' for name in c['restrictions'])
    physical_script=''; physical_receipt=''
    decays_requested='False'
    if 'physical_checks' in c:
        from ravel.physics import model_physical_checks
        physical_script=model_physical_checks.script(c['physical_checks'])
        physical_receipt=' \"physical_checks\"->physicalChecks,\n'
        decays_requested='True' if c['physical_checks']['partial_widths']['channels'] else 'False'
    if 'two_gauge_checks' in c:
        from ravel.physics import model_authoring
        physical_script += model_authoring.gauge_check_script(c['lagrangian_symbol'], c['two_gauge_checks']['new_terms_symbol'])
        physical_receipt += ' "gauge_checks"->gaugeChecks,\n'
    return (provider.namespace_load_script(fr) +
        'providerLoad = TrueQ[loaded] && TrueQ[providerNamespace["system_definitions_unchanged"]]'
        ' && providerNamespace["package_commutator_downvalues"] === 2'
        ' && providerNamespace["package_matrix_symbol_downvalues"] === 8;\n'
        'Clear['+lag+']; modelLoad=False;\n'
        'If[TrueQ[providerLoad], SetDirectory['+q(model)+'];\n'
        ' modelLoad=CheckAbort[Check[FeynRules`LoadModel['+models+'];True,False],False]];\n'
        'sourceLoads=<|"provider_load_without_messages"->TrueQ[providerLoad],\n'
        ' "model_load_without_messages"->TrueQ[modelLoad],"requested_model_files"->{'+models+'}|>;\n'
        'If[!TrueQ[providerLoad && modelLoad],\n'
        ' Export['+q(receipt)+',<|"schema_version"->1,"status"->"source_load_failed",\n'
        ' "process_id"->$ProcessID,"source_loads"->sourceLoads,"generated_events"->0|>,"RawJSON"]; Exit[2]];\n'
        'restrictionReports={};\n'
        'loadRestriction[file_] := Module[{ok,before,rr,n,counter,after},\n'
        ' Clear[FeynRules`M$Restrictions]; before=Length[FeynRules`MR$Restrictions];\n'
        ' ok=CheckAbort[Check[FeynRules`LoadRestriction[file];True,False],False];\n'
        ' rr=If[ListQ[FeynRules`M$Restrictions],FeynRules`M$Restrictions,{}]; n=Length[rr];\n'
        ' counter=PRIVATE`FR$restrictionCounter; after=Length[FeynRules`MR$Restrictions];\n'
        ' AppendTo[restrictionReports,<|"path"->file,"load_without_messages"->TrueQ[ok],\n'
        ' "rules_are_valid"->TrueQ[n>0 && AllTrue[rr,MatchQ[#,_Rule|_RuleDelayed]&]],\n'
        ' "source_rule_count"->n,"processed_rule_count"->counter,\n'
        ' "registry_count_before"->before,"registry_count_after"->after,\n'
        ' "evaluated_rule_expressions"->Map[ToString[#,InputForm]&,rr]|>]];\n'+restrictions+
        'lagDefined = Length[OwnValues['+lag+']] > 0; lag = '+lag+';\n'
        'ravelPrinted[expr_] := Module[{value, printed = {}},\n'
        ' value = Block[{Print = Function[Null, AppendTo[printed, StringJoin[Map[ToString, {##}]]]]}, expr];\n'
        ' {value, StringRiffle[printed, "\\n"]}];\nSetAttributes[ravelPrinted, HoldFirst];\n'
        '{kin, kinPrinted} = ravelPrinted[FeynRules`CheckKineticTermNormalisation[lag, FeynRules`FlavorExpand -> True]];\n'
        'kinTerms = FeynRules`GetKineticTerms[lag, FeynRules`FlavorExpand -> True];\n'
        '{spectrum, massPrinted} = ravelPrinted[FeynRules`GetMassSpectrum[lag, FeynRules`FlavorExpand -> True]];\n'
        'rows = If[Head[spectrum] === TableForm, Rest[First[spectrum]], {}];\n'
        'num[x_] := With[{v=N[x]}, If[NumberQ[v] && FreeQ[v,Indeterminate|ComplexInfinity|_DirectedInfinity],\n'
        ' <|"real"->Re[v],"imag"->Im[v]|>, <|"unevaluated"->ToString[v,InputForm]|>]];\n'
        'massRows = Map[Function[row, If[ListQ[row] && Length[row] === 3,\n'
        ' <|"particle"->ToString[row[[1]],InputForm],"analytic"->ToString[row[[2]],InputForm],\n'
        ' "calculated"->num[row[[3]]],"model_file"->num[FeynRules`NumericalValue[FeynRules`Mass[row[[1]]]]]|>,\n'
        ' <|"malformed"->ToString[row,InputForm]|>]],rows];\n'
        + DIAGNOSTIC_WITNESS_SCRIPT + physical_script +
        'FeynRules`WriteUFO[lag, FeynRules`Output -> '+q(exported)+', FeynRules`AddDecays -> False,\n'
        ' FeynRules`DialogBox -> Off, FeynRules`Optimization -> False];\n'
        'kernels=Kernels[];\n'
        'r=<|"schema_version"->1,"provider_root"->$FeynRulesPath,"model_root"->'+q(model)+',\n'
        ' "kernel_version"->$VersionNumber,"provider_version"->ToString[FeynRules`FR$VersionNumber],\n'
        ' "process_id"->$ProcessID,"model_name"->ToString[FeynRules`M$ModelName],\n'
        ' "model_files"->{'+models+'},"restrictions"->{'+','.join(q(model/name) for name in c['restrictions'])+'},\n'
        ' "source_loads"->sourceLoads,\n'
        ' "namespace_compatibility"->providerNamespace,\n'
        ' "restriction_loads"->restrictionReports,\n'
        ' "lagrangian_symbol"->'+q(c['lagrangian_symbol'])+',"lagrangian_defined"->TrueQ[lagDefined],\n'
        ' "lagrangian_leaf_count"->LeafCount[lag],"lagrangian_nonzero"->TrueQ[lag=!=0],\n'
        ' "kinetic_result"->TrueQ[kin],"kinetic_result_expression"->ToString[kin,InputForm],\n'
        ' "kinetic_printed"->kinPrinted,"mass_printed"->massPrinted,\n'
        ' "fermion_kinetic_witness"->fermionKinetic,"mass_coefficients"->massCoefficients,\n'
        ' "kinetic_nonzero"->TrueQ[kinTerms=!=0],"kinetic_leaf_count"->LeafCount[kinTerms],\n'
        ' "kinetic_api_downvalues"->Length[DownValues[FeynRules`CheckKineticTermNormalisation]],\n'
        ' "mass_api_downvalues"->Length[DownValues[FeynRules`GetMassSpectrum]],"mass_rows"->massRows,\n'
        ' "class_count"->Length[FeynRules`M$ClassesDescription],"parameter_count"->Length[FeynRules`M$Parameters],\n'
        ' "electric_charge_symbol_defined"->TrueQ[MemberQ[FeynRules`MR$QuantumNumbers,FeynRules`Q]],\n'
        ' "parallel_disabled"->TrueQ[FR$Parallel===False && FR$Parallelize===False],\n'
        ' "parallel_kernels_list"->ListQ[kernels],"parallel_kernel_count"->If[ListQ[kernels],Length[kernels],-1],\n'
        + physical_receipt +
        ' "export_root"->'+q(exported)+',"decay_calculation_requested"->'+decays_requested+',"generated_events"->0|>;\n'
        'Export['+q(receipt)+',r,"RawJSON"]; Exit[0];\n')


def _real(value):
    if not isinstance(value, dict) or set(value) != {'real', 'imag'}:
        raise ValueError('evaluated complex-number record required')
    real, imag = value['real'], value['imag']
    if (type(real) not in (int, float) or type(imag) not in (int, float)
            or not math.isfinite(real) or not math.isfinite(imag) or abs(imag) > 1e-12 or real < 0):
        raise ValueError('finite nonnegative real mass required')
    return real


def mass_witness(rows):
    """Independent arithmetic on all returned nonzero native mass-spectrum rows."""
    if not isinstance(rows, list) or not 1 <= len(rows) <= 10000:
        raise ValueError('nonvacuous bounded native mass population required')
    seen, result = set(), []
    for row in rows:
        custody._keys(row, ('particle', 'analytic', 'calculated', 'model_file'), 'mass row')
        if not isinstance(row['particle'], str) or not row['particle'] or row['particle'] in seen:
            raise ValueError('unique nonempty returned particle identity required')
        seen.add(row['particle'])
        if not isinstance(row['analytic'], str) or not row['analytic']:
            raise ValueError('native analytic mass expression required')
        calculated, supplied = _real(row['calculated']), _real(row['model_file'])
        relative = abs(calculated-supplied)/supplied if supplied else None
        passed = relative <= 0.001 if supplied else calculated <= 1e-12
        result.append({'particle': row['particle'], 'calculated': calculated, 'model_file': supplied,
                       'relative_difference': relative, 'passed': passed})
    return {'passed': all(row['passed'] for row in result) and any(row['model_file'] > 0 for row in result),
            'rows': result, 'complete_mass_population_checked':False,
            'quarantine':'Native GetMassSpectrum can mask negative/imaginary values and omit rows; omitted or masked populations remain unresolved.',
            'scope': 'Returned native rows only; neither complete mass-spectrum nor physical model acceptance.'}


def restriction_witness(reports, c, model):
    if not isinstance(reports, list) or len(reports) != len(c['restrictions']):
        return False
    for report, name in zip(reports,c['restrictions']):
        count = report.get('source_rule_count')
        if (report.get('path') != str(model/name) or report.get('load_without_messages') is not True
                or report.get('rules_are_valid') is not True or type(count) is not int or count <= 0
                or type(report.get('processed_rule_count')) is not int or report['processed_rule_count'] != count
                or type(report.get('registry_count_before')) is not int or report['registry_count_before'] < 0
                or type(report.get('registry_count_after')) is not int
                or report['registry_count_after'] < report['registry_count_before']+count
                or not isinstance(report.get('evaluated_rule_expressions'),list)
                or len(report['evaluated_rule_expressions']) != count
                or any(not isinstance(rule,str) or not rule for rule in report['evaluated_rule_expressions'])):
            return False
    return True


def literal_external_card(text):
    """Select literal exported UFO external values without importing executable UFO."""
    rows, names, addresses = [], set(), set()
    for statement in ast.parse(text).body:
        if not isinstance(statement, ast.Assign) or not isinstance(statement.value, ast.Call):
            continue
        call = statement.value
        factory = call.func.id if isinstance(call.func, ast.Name) else call.func.attr if isinstance(call.func, ast.Attribute) else None
        if factory != 'Parameter':
            continue
        keywords = {k.arg:k.value for k in call.keywords}
        if len(keywords) != len(call.keywords) or None in keywords:
            raise ValueError('canonical explicit UFO Parameter keywords required')
        try:
            nature = ast.literal_eval(keywords['nature'])
        except (ValueError, KeyError):
            raise ValueError('literal UFO parameter nature required')
        if nature != 'external':
            continue
        try:
            name, kind, value, block, codes = [ast.literal_eval(keywords[k]) for k in ('name', 'type', 'value', 'lhablock', 'lhacode')]
        except (ValueError, KeyError):
            raise ValueError('all exported external values/addresses must be literal')
        if (not isinstance(name, str) or not name or name in names or kind != 'real'
                or type(value) not in (int, float) or not math.isfinite(value)
                or not isinstance(block, str) or not re.fullmatch('[A-Za-z][A-Za-z0-9_]*', block)
                or not isinstance(codes, list) or not 1 <= len(codes) <= 8
                or any(type(code) is not int or code <= 0 for code in codes)):
            raise ValueError('unique real finite scalar external UFO parameter required')
        address = (block.lower(), tuple(codes))
        if address in addresses or (address[0] == 'decay' and (len(codes) != 1 or value < 0)):
            raise ValueError('unique external card address and scalar nonnegative widths required')
        addresses.add(address); names.add(name)
        rows.append({'name': name, 'block': address[0], 'codes': list(codes), 'value': value, 'source_line': statement.lineno})
    if not rows:
        raise ValueError('no canonical literal external UFO parameters')
    lines, current = [], None
    for row in sorted(rows, key=lambda r:(r['block'], r['codes'])):
        if row['block'] == 'decay':
            lines.append('DECAY '+str(row['codes'][0])+' '+format(row['value'], '.17g'))
        else:
            if current != row['block']:
                current = row['block']; lines.append('BLOCK '+current.upper())
            lines.append(' '.join(str(code) for code in row['codes'])+' '+format(row['value'], '.17g'))
    card = '\n'.join(lines)+'\n'
    from ravel.validation.model_tool_witness import card_values
    if len(card_values(card)) != len(rows):
        raise ValueError('exported card does not preserve every literal external address')
    return card, rows


def adjudicate(native, c, fr, model, exported, pid):
    if c["operation"]=="sarah-source-ufo":
        from ravel.physics import model_sarah
        return model_sarah.derivation_adjudicate(native,c,fr,model,exported,pid)
    mass = mass_witness(native.get('mass_rows'))
    kinetic, mass_signs = kinetic_diagnostics(native), mass_diagnostics(native)
    positive_int = lambda value: type(value) is int and value > 0
    loads = native.get('source_loads')
    checks = {
        'actual_owned_kernel': type(native.get('process_id')) is int and native['process_id'] == pid,
        'qualified_versions': (type(native.get('kernel_version')) in (int, float)
            and native['kernel_version'] == c['expected_kernel_version']
            and native.get('provider_version') == c['expected_provider_version']),
        'source_paths': native.get('provider_root') == str(fr) and native.get('model_root') == str(model)
            and native.get('export_root') == str(exported),
        'literal_source_selection': native.get('model_files') == [str(model/name) for name in c['model_files']]
            and native.get('restrictions') == [str(model/name) for name in c['restrictions']]
            and native.get('lagrangian_symbol') == c['lagrangian_symbol'],
        'complete_message_free_source_load': isinstance(loads, dict)
            and set(loads) == {'provider_load_without_messages', 'model_load_without_messages', 'requested_model_files'}
            and loads['provider_load_without_messages'] is True and loads['model_load_without_messages'] is True
            and loads['requested_model_files'] == [str(model/name) for name in c['model_files']],
        'message_free_namespace_compatibility': provider.namespace_checks(native.get('namespace_compatibility')),
        'evaluated_restriction_registration': restriction_witness(native.get('restriction_loads'),c,model),
        'nonvacuous_model': native.get('lagrangian_defined') is True and native.get('lagrangian_nonzero') is True
            and positive_int(native.get('lagrangian_leaf_count')) and native['lagrangian_leaf_count'] > 1
            and positive_int(native.get('class_count')) and positive_int(native.get('parameter_count')),
        'evaluated_kinetic_normalisation': kinetic['passed'] and native.get('kinetic_nonzero') is True
            and type(native.get('kinetic_result')) is bool
            and positive_int(native.get('kinetic_leaf_count')) and native['kinetic_leaf_count'] > 1
            and positive_int(native.get('kinetic_api_downvalues')) and positive_int(native.get('mass_api_downvalues')),
        'independent_returned_mass_agreement': mass['passed'],
        'adjudicated_mass_sign_diagnostics': mass_signs['passed'],
        'explicit_electric_charge_symbol': native.get('electric_charge_symbol_defined') is True,
        'no_parallel_kernels': native.get('parallel_disabled') is True and native.get('parallel_kernels_list') is True
            and type(native.get('parallel_kernel_count')) is int and native['parallel_kernel_count'] == 0,
        'no_unrequested_decays_or_events': native.get('decay_calculation_requested') is bool(c.get('physical_checks',{}).get('partial_widths',{}).get('channels',[]))
            and type(native.get('generated_events')) is int and native['generated_events'] == 0,
    }
    if 'expected_provider_digest' in c:
        try:
            checks['pinned_provider_digest'] = provider_digest(custody.source_tree(fr)) == c['expected_provider_digest']
        except (OSError, ValueError):
            checks['pinned_provider_digest'] = False
    result={'passed': all(checks.values()), 'checks': checks, 'mass_witness': mass, 'scope': SCOPE,
            'kinetic_diagnostics': kinetic, 'mass_sign_diagnostics': mass_signs}
    if 'physical_checks' in c:
        from ravel.physics import model_physical_checks
        physical=model_physical_checks.witness(native.get('physical_checks'),c['physical_checks'])
        checks['requested_physical_checks']=physical['passed']
        result.update(passed=all(checks.values()),physical_checks=physical)
    elif 'physical_checks' in native:
        checks['no_unrequested_physical_checks']=False
        result['passed']=False
    if 'two_gauge_checks' in c:
        from ravel.physics import model_authoring
        try:
            verdicts=model_authoring.adjudicate_gauge_checks(native.get('gauge_checks'))
        except ValueError as exc:
            verdicts={'passed':False,'failures':[str(exc)]}
        checks['two_gauge_verdicts']=verdicts['passed']
        result.update(passed=all(checks.values()),gauge_checks=verdicts)
    return result


def python_syntax_diagnostics(selected, tree, compatibility):
    """Refuse exported Python that does not parse; name the supported FeynRules raise conversion when it applies."""
    from ravel.physics import ufo_interop
    rows = []
    for name in tree['files']:
        if Path(name).suffix != '.py':
            continue
        text = (selected/name).read_text(errors='replace')
        try:
            ast.parse(text)
        except (SyntaxError, UnicodeError) as exc:
            row = {'file': name, 'kind': 'python-syntax-refusal', 'error': str(exc)}
            if compatibility == 'none':
                try:
                    ufo_interop.convert_text(text)  # parses the converted text or raises
                    row['remedy'] = ('the only Python-2 form is the literal FeynRules 2.3.49 UFOError raise; plan with '
                                     '--ufo-python-compatibility ' + ufo_interop.POLICY)
                except (SyntaxError, ValueError, UnicodeError, TokenError):
                    pass
            rows.append(row)
    return rows


def export_admission(selected, out):
    """Static model admission of the exported UFO: parse, per-vertex quantum numbers, conjugate vertices."""
    from ravel.physics import model_admission
    record = model_admission.static_admission(selected)
    custody._write(Path(out)/'export-static-admission.json', record)
    return record


def _approved(task, output):
    for root in (Path(output).absolute(), *Path(output).absolute().parents):
        if (root/'inputs/science-plan.json').is_file():
            from ravel.workflow import science
            selected = science.verify_worker(root); spec = science.execution_spec(root)
            if (spec['mode'] != 'model-derivation-bridge' or spec['task'] != task
                    or Path(output).resolve() != (root/selected['output_directory']).resolve()):
                raise ValueError('derivation differs from exact approved worker')
            return root, selected
    raise ValueError('derivation requires approved supervised worker')


def run(task, base, output):
    root, selected = _approved(task, output)
    path, c = _load(task, base)
    if c['max_seconds'] > selected['max_seconds']:
        raise ValueError('native derivation exceeds approved time')
    before = {str(p):custody._hash(p) for p in inputs(task, base)}
    out = Path(output).resolve(); out.mkdir(parents=True, exist_ok=True)
    work = root/'work/model-derivation-bridge'/out.name
    if work.exists() or any(p.is_symlink() for p in (work, *work.parents)):
        raise ValueError('fresh regular derivation workspace required')
    work.mkdir(parents=True)
    is_sarah=c['operation']=='sarah-source-ufo'
    fr, model, exported = work/('sarah' if is_sarah else 'feynrules'), work/'model_source', out/'exported-ufo'
    if exported.exists() or exported.is_symlink():
        raise ValueError('fresh receipt-bound UFO output required')
    custody._copy(c['provider_tree'], path.parent, fr); custody._copy(c['model_tree'], path.parent, model)
    private_before = {'provider':custody.source_tree(fr), 'model':custody.source_tree(model)}
    script_path = out/'derivation.wl'
    script_path.write_text(script(c, fr, model, exported, out/'native-derivation.json'))
    overrides = {key:os.environ.pop(key) for key in provider.INIT_ENVIRONMENT if key in os.environ}
    from ravel.physics.reinterpret_db import execute_native
    try:
        execution = execute_native([str(custody._pin(c['kernel'], path.parent)), '-noinit', '-noprompt',
                                    '-script', str(script_path)], out, c)
    finally:
        os.environ.update(overrides)
    native = custody._read(out/'native-derivation.json'); process = custody._read(out/'native-process.json')
    checks = adjudicate(native, c, fr, model, exported, process['pid'])
    custody._write(out/'derivation-checks.json',checks)
    if private_before != {'provider':custody.source_tree(fr), 'model':custody.source_tree(model)}:
        raise ValueError('provider/model source changed during derivation')
    if before != {str(p):custody._hash(p) for p in inputs(task, base)}:
        raise ValueError('original derivation source/runtime changed')
    export_diagnostics=[];exported_source=None;selected=exported;convention_census=None
    compatibility=c.get('ufo_python_compatibility','none');conversion=None
    try:
        for name in REQUIRED_UFO:custody._regular(name,exported)
        raw_tree=custody.source_tree(exported)
        custody._write(out/'raw-exported-ufo-source.json',raw_tree)
        if compatibility!='none':
            from ravel.physics import ufo_interop
            selected=out/'exported-ufo-python3'
            conversion=ufo_interop.convert_tree(exported,selected,compatibility)
            custody._write(out/'ufo-python-compatibility.json',conversion)
        tree=custody.source_tree(selected)
        export_diagnostics+=python_syntax_diagnostics(selected,tree,compatibility)
        if not export_diagnostics:
            admission=export_admission(selected,out)
            if admission['decision']!='passed':
                export_diagnostics.append({'kind':'model-admission-refusal','refusals':admission['refusals'],
                                           'not_evaluated':admission['not_evaluated']})
        if not export_diagnostics:
            card,rows=literal_external_card((selected/'parameters.py').read_text())
            if is_sarah:
                from ravel.physics import model_sarah
                convention_census=model_sarah.ufo_census(selected,c['particle_conventions'])
                custody._write(out/'ufo-convention-census.json',convention_census)
            card_path=out/'exported-source-card.dat';card_path.write_text(card)
            selected_card={'path':str(card_path),'sha256':custody._hash(card_path)}
            if is_sarah:
                selected_card=model_sarah.select_card(c,path.parent,rows,out/'supplied-source-card.dat')
            manifest=out/'exported-ufo-source.json';custody._write(manifest,tree)
            exported_source={'schema_version':1,'ufo':str(selected),'ufo_manifest':{'path':str(manifest),'sha256':custody._hash(manifest)},
                'parameter_card':selected_card,'external_parameters':rows,
                'point_policy':'All canonical literal exported external values selected as explicit point; no UFO import or default substitution.',
                'next_operation':'A successful supervised derivation receipt and scoped review must precede a fresh model-tool-bridge plan/approval/lease',
                'native_madgraph_run_performed':False,'generator_or_model_validity_inferred':False,
                'python_compatibility_policy':compatibility,'raw_ufo':str(exported)}
    except (OSError,ValueError,SyntaxError,UnicodeError,TokenError) as exc:
        export_diagnostics.append({'kind':'export-admission-refusal','error':str(exc)})
    custody._write(out/'export-admission.json',{'passed':not export_diagnostics,'diagnostics':export_diagnostics,
        'raw_ufo':str(exported),'selected_ufo':str(selected),'python_compatibility_policy':compatibility})
    passed=checks['passed'] and not export_diagnostics and exported_source is not None
    result = {'status':'passed' if passed else 'failed', 'physics_validated':False, 'scope':SCOPE,
        'source':c['source'], 'checks':checks, 'native_execution':execution, 'native_derivation':native,
        'exported_source':exported_source, 'handoff_eligible':passed,'export_diagnostics':export_diagnostics,
        'python_compatibility_policy':compatibility,'python_compatibility':conversion,
        'generated_events':0, 'decay_calculation_requested':bool(c.get('physical_checks',{}).get('partial_widths',{}).get('channels',[])),
        'limitations':['Kinetic and returned nonzero mass checks are necessary scoped native consistency checks, not a UV certificate.',
            'A FeynRules kinetic warning is waived only for a massless single-chirality field at canonical normalization, and a mass-sign warning only for a vanishing coefficient; both witnesses are recorded per field.',
            'Static export admission (per-vertex quantum numbers, conjugate vertices) is not a MadGraph gauge, Lorentz or permutation check; ravel model admit runs those on the requested process.',
            'Native GetMassSpectrum can mask negative/imaginary values and omit rows; unreported/masked mass populations remain quarantined, with no complete mass-spectrum acceptance.',
            'Exported literal source values define the explicit point; supplied total widths are preserved, not overwritten or certified by selected partial-width checks.',
            'Optional selected tree partial-width/reference checks do not establish complete decays, independent generated-amplitude agreement, loop accuracy or interaction applicability.',
            'MadGraph sampled amplitudes, independent references, loops, generator integration, showers and detector response require separate evidence.',
            'Finite kernel/app/provider/model source custody does not capture proprietary installed libraries/OS or authenticate license rights.']}
    if is_sarah:
        from ravel.physics import model_sarah
        result.update(scope=model_sarah.SCOPE,particle_convention_census=convention_census,
            handoff_eligible=passed and c['point_policy']=='supplied_complete_card',parameter_point_selected=c['point_policy']=='supplied_complete_card',
            effective_ufo_options=model_sarah.options(c['ufo_options']),check_model_physical_acceptance=None,
            limitations=['CheckModel printed diagnostics and raw return require scientific review; returned Null is not a Boolean certificate.',
                'Selected static conventions/card addresses and complete source reference census are not coupling evaluation, gauge/mass/width/amplitude or complete-interaction certification.',
                'Tree vertices only; no six-particle/effective-operator/RGE/loop/width/spectrum-solver work. Mandatory ASS and requested exclusions are retained.',
                'Native defaults (possible NaN mass100/width0) are retained diagnostic bytes. Only an explicitly supplied full card selects a point; no native MadGraph execution.',
                'Exact mirror source and kernel/app metadata do not establish redistribution rights, installed proprietary closure or future runtime compatibility.'])
    if is_sarah and exported_source is not None:
        exported_source['point_policy']=c['point_policy']
        exported_source['provided_parameter_card_input']=c['parameter_card']
        exported_source['native_export_default_card']={'path':str(out/'exported-source-card.dat'),'sha256':custody._hash(out/'exported-source-card.dat'),'selected_as_physical_point':False}
    if 'physical_checks' in c: result['requested_physical_checks']=c['physical_checks']
    result_path = out/'model-derivation-bridge.json'; custody._write(result_path, result)
    if passed and result['handoff_eligible']:
        handoff = {**exported_source, 'derivation_result':{'path':str(result_path),'sha256':custody._hash(result_path)},
            'requires_successful_supervised_derivation_receipt_and_scoped_review':True,
            'execution_authority_granted':False,'complete_mass_population_checked':False}
        if 'physical_checks' in c:
            handoff['physical_checks']=checks['physical_checks']
            handoff['total_width_substitution_requested']=False
        custody._write(out/'model-tool-handoff-candidate.json', handoff)
    return result


def qualified_handoff(rundir, destination):
    """Qualify reuse after actual successful execution and scoped three-role review."""
    from ravel.workflow import execution, physics_review, science
    root = custody._regular(rundir,Path.cwd(),directory=True)
    if science.verify_approval_envelope(root) or execution.stage_errors(root,'science'):
        raise ValueError('unchanged actual approved successful derivation required')
    status = physics_review.status(root)
    if (status['state'] != 'accepted' or status['claim_scope'] != 'model_source_derivation'
            or physics_review.gate_errors(root,'reuse')):
        raise ValueError('actual accepted model_source_derivation review required for handoff')
    stage = execution.load_execution(root)['stages']['science']
    if len(stage['outputs']) != 1:
        raise ValueError('one closed derivation output directory required')
    out = custody._regular(stage['outputs'][0],root,directory=True)
    result = custody._read(out/'model-derivation-bridge.json')
    if (result['status'] != 'passed' or result['physics_validated'] is not False
            or result['handoff_eligible'] is not True or result['checks']['passed'] is not True):
        raise ValueError('failed/diagnostic derivation cannot be qualified for reuse')
    candidate = custody._read(out/'model-tool-handoff-candidate.json')
    if any(candidate.get(key) != value for key,value in result['exported_source'].items()):
        raise ValueError('handoff source/card metadata differs from successful result')
    result_path = custody._pin(candidate['derivation_result'],out)
    if result_path != out/'model-derivation-bridge.json':
        raise ValueError('handoff result binding differs')
    model = custody._regular(candidate['ufo'],out,directory=True)
    if not model.is_relative_to(out):
        raise ValueError('exported scientific bytes are outside the receipt output')
    manifest = custody._pin(candidate['ufo_manifest'],out)
    if custody.source_tree(model) != custody._read(manifest):
        raise ValueError('handoff UFO source changed')
    custody._pin(candidate['parameter_card'],out)
    destination = Path(destination).expanduser().absolute()
    if destination.exists() or any(p.is_symlink() for p in (destination,*destination.parents)):
        raise ValueError('fresh regular qualified handoff path required')
    custody._regular(destination.parent,Path.cwd(),directory=True)
    record = custody._regular(stage['attempt_record'],root)
    document = {**candidate,'qualified_for_scoped_reuse':True,'execution_authority_granted':False,
        'successful_derivation_attempt':{'id':stage['attempt_id'],'path':str(record),'sha256':custody._hash(record)},
        'accepted_review':{'cycle_id':status['cycle_id'],'claim_scope':status['claim_scope'],
            'attestation':status['attestation']},'source_rebound':False,'native_recomputation_performed':False}
    with destination.open('x') as handle:
        json.dump(document,handle,indent=2,allow_nan=False);handle.write('\n')
    return document


def prepare(args):
    if not args.trust_model_source or not args.trust_provider_source:
        raise ValueError('explicit executable provider/model source trust required')
    root = Path(args.rundir).expanduser().absolute(); proposal = root.with_name(root.name+'-proposal')
    if root.exists() or proposal.exists():
        raise ValueError('fresh derivation run/proposal required')
    fr = custody._regular(args.feynrules, Path.cwd(), directory=True)
    model = custody._regular(args.model, Path.cwd(), directory=True)
    proposal.mkdir(parents=True)
    pin = lambda p:{'path':str(p),'sha256':custody._hash(p)}
    qualified_root = custody._regular(args.provider_readiness_run,Path.cwd(),directory=True)
    from ravel.workflow import execution
    qualified_stage = execution.load_execution(qualified_root)['stages']['science']
    readiness_path = custody._regular(args.provider_readiness_receipt, Path.cwd())
    readiness = qualified_receipt(custody._read(readiness_path))
    def tree(source, name):
        manifest = proposal/name; custody._write(manifest, custody.source_tree(source))
        return {'root':str(source),'manifest':pin(manifest)}
    c = {'schema_version':1,'operation':'feynrules-source-ufo','source':args.source,
        'kernel':pin(custody._regular(args.kernel,Path.cwd())),
        'application_metadata':pin(custody._regular(args.application_metadata,Path.cwd())),
        'provider_tree':tree(fr,'provider-source.json'),'model_tree':tree(model,'model-source.json'),
        'model_files':args.model_file,'restrictions':args.restriction,'lagrangian_symbol':args.lagrangian,
        'trusted_provider_source':True,'trusted_model_source':True,
        'provider_readiness_receipt':pin(readiness_path),
        'provider_readiness_run':{'path':str(qualified_root),'attempt_id':qualified_stage['attempt_id'],
            'attempt_record':pin(custody._regular(qualified_stage['attempt_record'],qualified_root))},
        'expected_kernel_version':readiness['native_provider']['kernel_version'],
        'expected_provider_version':readiness['native_provider']['provider_version'],
        'max_seconds':args.max_seconds,'max_ram_mib':args.max_ram_mib}
    if getattr(args,'physical_checks',None):
        c['physical_checks']=custody._read(custody._regular(args.physical_checks,Path.cwd()))
    if getattr(args,'ufo_python_compatibility','none')!='none':c['ufo_python_compatibility']=args.ufo_python_compatibility
    if getattr(args,'two_gauge_checks',None):c['two_gauge_checks']={'new_terms_symbol':args.two_gauge_checks}
    if getattr(args,'pinned_provider',False):c['expected_provider_digest']=provider_pin(fr,c['expected_provider_version'])
    config = proposal/'model-derivation-bridge.json'; custody._write(config,c); task = {'config':str(config)}
    inputs(task,proposal)
    policy = custody._read(custody._regular(args.review_policy,Path.cwd()))
    spec = {'schema_version':2,'mode':'model-derivation-bridge','source':args.source,
        'assumptions':['Pinned provider was operationally qualified; executable model source and explicit restrictions are trusted.',
            'Named Lagrangian kinetic/returned mass checks and fresh UFO custody establish a scoped derivation witness.',
            'Exported source values define a card; supplied total widths, complete decays, amplitudes, UV validity and generator/detector integration remain separate.'],
        'max_seconds':args.max_seconds+240,'max_attempts':1+policy['policy']['max_redos'],
        'approval_mode':args.approval_mode,'review_policy':policy,'task':task}
    if 'physical_checks' in c:
        spec['assumptions'].append('Explicit returned-list hermiticity/selected tree partial-width checks and declared analytic references have their own recorded scope; no supplied total-width substitution.')
    spec_path = proposal/'science.json'; custody._write(spec_path,spec)
    from ravel.workflow.science import plan
    plan(root,spec_path)
    print('Prepared source-to-UFO study; fresh actual CHECK-IN1 and native lease required. No derivation executed.')
    return 0


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__); sub = parser.add_subparsers(dest='command',required=True)
    h = sub.add_parser('handoff');h.add_argument('--rundir',required=True);h.add_argument('--out',required=True)
    p = sub.add_parser('plan')
    for name in ('kernel','application-metadata','feynrules','model','lagrangian','provider-readiness-receipt','provider-readiness-run',
                 'source','rundir','review-policy'):
        p.add_argument('--'+name,required=True)
    p.add_argument('--model-file',action='append',required=True)
    p.add_argument('--restriction',action='append',default=[])
    p.add_argument('--trust-provider-source',action='store_true'); p.add_argument('--trust-model-source',action='store_true')
    p.add_argument('--max-seconds',type=int,default=900); p.add_argument('--max-ram-mib',type=int,default=8192)
    p.add_argument('--physical-checks',help='Optional exact structured hermiticity/selected partial-width request JSON; no supplied total-width changes')
    p.add_argument('--approval-mode',choices=('physicist','scripted_yes'),default='physicist')
    p.add_argument('--two-gauge-checks',metavar='NEW_TERMS_SYMBOL',
                   help='also return typed Hermiticity, diagonal quadratic/mass and kinetic verdicts in Feynman and unitary gauge; names the symbol holding the new terms')
    from ravel.physics import ufo_interop
    p.add_argument('--ufo-python-compatibility',choices=('none',ufo_interop.POLICY),default='none')
    p.add_argument('--pinned-provider',action='store_true',
                   help='require the packaged FeynRules source-tree digest at plan time and in the derivation')
    from ravel.physics import model_sarah
    model_sarah.cli_arguments(sub.add_parser('plan-sarah'),derivation=True)
    args = parser.parse_args(argv)
    if args.command=='plan-sarah': return model_sarah.prepare_derivation(args)
    if args.command == 'handoff':
        qualified_handoff(args.rundir,args.out)
        print('Qualified unchanged actual accepted derivation output; a new model-tool approval/lease is still required.')
        return 0
    return prepare(args)


if __name__ == '__main__':
    raise SystemExit(main())


def read_qualified_handoff(path):
    """Authenticate a qualified-ufo.json for generation; return (UFO directory, document, handoff pin).

    Only a handoff written by ``qualified_handoff`` after an accepted
    model_source_derivation review is admitted, and only while its UFO bytes
    still equal the reviewed census. The UFO is read in place; nothing is copied
    into the installed toolchain.
    """
    p = custody._regular(path, Path.cwd())
    doc = custody._read(p)
    if type(doc) is not dict or doc.get('qualified_for_scoped_reuse') is not True:
        raise ValueError('model origin is not a qualified UFO handoff; qualify an accepted derivation first')
    review = doc.get('accepted_review')
    if type(review) is not dict or review.get('claim_scope') != 'model_source_derivation':
        raise ValueError('model origin lacks an accepted model_source_derivation review')
    attempt = doc.get('successful_derivation_attempt')
    if type(attempt) is not dict or not {'path', 'sha256'} <= set(attempt):
        raise ValueError('model origin lacks its successful derivation attempt')
    record = custody._regular(attempt['path'], p.parent)
    if custody._hash(record) != attempt['sha256']:
        raise ValueError('derivation attempt record changed since qualification')
    if type(doc.get('ufo')) is not str or not Path(doc['ufo']).is_absolute():
        raise ValueError('qualified handoff must name its UFO by absolute path')
    model = custody._regular(doc['ufo'], p.parent, directory=True)
    manifest = custody._pin(doc['ufo_manifest'], p.parent)
    if custody.source_tree(model) != custody._read(manifest):
        raise ValueError('qualified UFO bytes changed since review')
    missing = [name for name in REQUIRED_UFO if not (model / name).is_file()]
    if missing:
        raise ValueError('qualified UFO lacks ' + ', '.join(missing))
    return model, doc, {'path': str(p), 'sha256': custody._hash(p)}
