"""Source-bound Wolfram/FeynRules provider qualification, before model work.

An evaluated kernel and loaded definitions establish operational readiness only.
No model is loaded, no vertices or widths calculated, and no license secrets read.
"""
import argparse
import json
import os
from pathlib import Path
import re

from ravel.physics import model_tool_bridge as custody

ENTRYPOINTS = ('LoadModel', 'FeynmanRules', 'WriteUFO', 'CheckKineticTermNormalisation')
READINESS_KERNEL_VERSIONS = (14.3, 15.0)
INIT_ENVIRONMENT = ('WOLFRAMINIT', 'MATHKERNELINIT', 'WOLFRAM_BASE', 'WOLFRAM_USERBASE')


def validate(task):
    custody._keys(task, ('config',), 'model-provider-bridge task')
    if not isinstance(task['config'], str) or not task['config'].strip():
        raise ValueError('source-bound provider config required')
    return dict(task)


def validate_config(c):
    if isinstance(c,dict) and c.get("operation") == "wolfram-sarah-readiness":
        from ravel.physics import model_sarah
        return model_sarah.validate_readiness(c)
    custody._keys(c, ('schema_version', 'operation', 'source', 'kernel', 'application_metadata',
        'provider_tree', 'trusted_provider_source', 'expected_kernel_version', 'expected_provider_version',
        'existing_installation_license_status', 'max_seconds', 'max_ram_mib'), 'provider config')
    if type(c['schema_version']) is not int or c['schema_version'] != 1 or c['operation'] != 'wolfram-feynrules-readiness':
        raise ValueError('qualified operation is wolfram-feynrules-readiness schema1')
    if c['trusted_provider_source'] is not True or not isinstance(c['source'], str) or not c['source'].strip():
        raise ValueError('attributed explicitly trusted provider source required')
    if (type(c['expected_kernel_version']) not in (int, float)
            or c['expected_kernel_version'] not in READINESS_KERNEL_VERSIONS
            or c['expected_provider_version'] != '2.3.49'):
        raise ValueError('readiness requires an explicit Wolfram14.3 or15.0/FeynRules2.3.49 binding')
    if c['existing_installation_license_status'] != 'unverified_no_activation_or_credentials_requested':
        raise ValueError('existing runtime license uncertainty must remain declared')
    if type(c['max_seconds']) is not int or not 1 <= c['max_seconds'] <= 120:
        raise ValueError('provider time ceiling must be1..120seconds')
    if type(c['max_ram_mib']) is not int or not 512 <= c['max_ram_mib'] <= 4096:
        raise ValueError('provider sampled RAM ceiling must be512..4096MiB')
    return c


def _load(task, base):
    validate(task)
    path = custody._regular(task['config'], base)
    return path, validate_config(custody._read(path))


def inputs(task, base):
    path, c = _load(task, base)
    if c["operation"] == "wolfram-sarah-readiness":
        from ravel.physics import model_sarah
        return model_sarah.readiness_inputs(task,base)
    kernel = custody._pin(c['kernel'], path.parent)
    if not os.access(kernel, os.X_OK):
        raise ValueError('native kernel is not executable')
    metadata = custody._pin(c['application_metadata'], path.parent)
    root, manifest, files = custody._tree(c['provider_tree'], path.parent)
    for name in ('FeynRules.m', 'FeynRulesPackage.m', 'ToolBox.m'):
        if not (root/name).is_file():
            raise ValueError('missing provider source ' + name)
    match = re.search(r'FR\$VersionNumber\s*=\s*"([^"]+)"', (root/'FeynRulesPackage.m').read_text())
    if not match or match.group(1) != c['expected_provider_version']:
        raise ValueError('provider source version differs from the requested native qualification')
    sources = list(Path(__file__).resolve().parents[1].rglob('*.py'))
    return sorted(set([path, kernel, metadata, manifest, *files, *sources]))


def namespace_load_script(provider):
    """Keep the two provider names off protected System symbols in a fresh kernel.

    FeynRules 2.3.49 resolves names on the package context path before System.
    Creating the package symbols preserves installed source and System definitions;
    creating PRIVATE`Commutator alone does not shadow the System path lookup.
    """
    quoted = json.dumps(str(provider), ensure_ascii=False)
    system = ('{Attributes[System`Commutator], DownValues[System`Commutator], '
              'OwnValues[System`Commutator], Attributes[System`MatrixSymbol], '
              'DownValues[System`MatrixSymbol], OwnValues[System`MatrixSymbol]}')
    return ('$HistoryLength = 0;\nFR$Parallel = False;\n'
        'systemBefore = Hash['+system+', "SHA256", "HexString"];\n'
        'FeynRules`Commutator;\nFeynRules`MatrixSymbol;\n'
        '$FeynRulesPath = '+quoted+';\nSetDirectory[$FeynRulesPath];\n'
        'loaded = CheckAbort[Check[Get[FileNameJoin[{$FeynRulesPath,"FeynRules.m"}]]; True, False], False];\n'
        'loadMessages = ToString[#, InputForm]& /@ $MessageList;\n'
        'systemAfter = Hash['+system+', "SHA256", "HexString"];\n'
        'providerNamespace = <|"mode" -> "package_context_symbols_v1",\n'
        ' "message_free_load" -> TrueQ[loaded], "load_messages" -> loadMessages,\n'
        ' "system_definitions_unchanged" -> SameQ[systemBefore,systemAfter],\n'
        ' "package_commutator_downvalues" -> Length[DownValues[FeynRules`Commutator]],\n'
        ' "package_matrix_symbol_downvalues" -> Length[DownValues[FeynRules`MatrixSymbol]]|>;\n')


def namespace_checks(receipt):
    if not isinstance(receipt, dict):
        return False
    return (receipt.get('mode') == 'package_context_symbols_v1'
        and receipt.get('message_free_load') is True and receipt.get('load_messages') == []
        and receipt.get('system_definitions_unchanged') is True
        and type(receipt.get('package_commutator_downvalues')) is int
        and receipt['package_commutator_downvalues'] == 2
        and type(receipt.get('package_matrix_symbol_downvalues')) is int
        and receipt['package_matrix_symbol_downvalues'] == 8)


def script(provider, output):
    """Fixed script: no supplied expressions, model, vertices or license probes."""
    quoted = lambda value: json.dumps(str(value), ensure_ascii=False)
    definitions = ', '.join(quoted(name)+' -> Length[DownValues[FeynRules`'+name+']]' for name in ENTRYPOINTS)
    return (namespace_load_script(provider) +
        'kernels = Kernels[];\n'
        'receipt = <|"schema_version" -> 1, "provider_root" -> $FeynRulesPath,\n'
        ' "kernel_version" -> $VersionNumber, "kernel_version_string" -> $Version,\n'
        ' "system_id" -> $SystemID, "process_id" -> $ProcessID, "word_length" -> $SystemWordLength,\n'
        ' "kernel_arithmetic_control" -> (2+2), "provider_loaded" -> (TrueQ[loaded] && TrueQ[FR$Loaded]),\n'
        ' "provider_version" -> ToString[FeynRules`FR$VersionNumber],\n'
        ' "namespace_compatibility" -> providerNamespace,\n'
        ' "parallel_disabled" -> TrueQ[FR$Parallel === False && FR$Parallelize === False],\n'
        ' "parallel_kernels_list" -> ListQ[kernels], "parallel_kernel_count" -> If[ListQ[kernels],Length[kernels],-1],\n'
        ' "entrypoint_downvalues" -> <|'+definitions+'|>,\n'
        ' "obsolete_undefined_entrypoint_downvalues" -> Length[DownValues[FeynRules`CheckKineticTerms]],\n'
        ' "model_calculation_performed" -> False, "generated_events" -> 0|>;\n'
        'Export['+quoted(output)+',receipt,"RawJSON"];\nExit[0];\n')


def adjudicate(receipt, c, provider, native_pid):
    if isinstance(c,dict) and c.get("operation") == "wolfram-sarah-readiness":
        from ravel.physics import model_sarah
        return model_sarah.readiness_adjudicate(receipt,c,provider,native_pid)
    checks = {
        'local_source_path': receipt.get('provider_root') == str(provider),
        'actual_owned_kernel': type(receipt.get('process_id')) is int and receipt['process_id'] == native_pid,
        'kernel_version': receipt.get('kernel_version') == c['expected_kernel_version'],
        'kernel_arithmetic_control': type(receipt.get('kernel_arithmetic_control')) is int and receipt['kernel_arithmetic_control'] == 4,
        'provider_loaded': receipt.get('provider_loaded') is True,
        'message_free_namespace_compatibility': namespace_checks(receipt.get('namespace_compatibility')),
        'provider_version': receipt.get('provider_version') == c['expected_provider_version'],
        'no_parallel_kernels': receipt.get('parallel_disabled') is True and receipt.get('parallel_kernels_list') is True
            and type(receipt.get('parallel_kernel_count')) is int and receipt['parallel_kernel_count'] == 0,
        'evaluated_required_definitions': isinstance(receipt.get('entrypoint_downvalues'), dict)
            and set(receipt['entrypoint_downvalues']) == set(ENTRYPOINTS)
            and all(type(n) is int and n > 0 for n in receipt['entrypoint_downvalues'].values()),
        'undefined_legacy_call_refused': type(receipt.get('obsolete_undefined_entrypoint_downvalues')) is int
            and receipt['obsolete_undefined_entrypoint_downvalues'] == 0,
        'no_model_calculation': receipt.get('model_calculation_performed') is False
            and type(receipt.get('generated_events')) is int and receipt['generated_events'] == 0,
    }
    return {'passed': all(checks.values()), 'checks': checks,
            'scope': 'Operational local kernel, loaded provider definitions and source custody only; no model validity.'}


def _approved(task, output):
    for rd in (Path(output).absolute(), *Path(output).absolute().parents):
        if (rd/'inputs/science-plan.json').is_file():
            from ravel.workflow import science
            selected = science.verify_worker(rd); spec = science.execution_spec(rd)
            if spec['mode'] != 'model-provider-bridge' or spec['task'] != task or Path(output).resolve() != (rd/selected['output_directory']).resolve():
                raise ValueError('provider qualification differs from the exact approved worker')
            return rd, selected
    raise ValueError('provider execution requires its approved supervised worker')


def run(task, base, output):
    rd, selected = _approved(task, output)
    path, c = _load(task, base)
    if c['max_seconds'] > selected['max_seconds']:
        raise ValueError('provider native time exceeds approved supervision')
    before = {str(p): custody._hash(p) for p in inputs(task, base)}
    out = Path(output).resolve(); out.mkdir(parents=True, exist_ok=True)
    work = rd/'work/model-provider-bridge'/out.name
    if work.exists() or any(x.is_symlink() for x in (work,*work.parents)):
        raise ValueError('fresh regular provider attempt workspace required')
    work.mkdir(parents=True)
    is_sarah=c['operation']=='wolfram-sarah-readiness'
    provider = work/('sarah' if is_sarah else 'feynrules'); custody._copy(c['provider_tree'], path.parent, provider)
    source_before = custody.source_tree(provider)
    executable = custody._pin(c['kernel'], path.parent)
    wl = out/'qualification.wl'
    if is_sarah:
        from ravel.physics import model_sarah
        wl.write_text(model_sarah.readiness_script(provider,out/'native-provider.json'))
    else: wl.write_text(script(provider, out/'native-provider.json'))
    command = [str(executable), '-noinit', '-noprompt', '-script', str(wl)]
    from ravel.physics.reinterpret_db import execute_native
    overrides = {key:os.environ.pop(key) for key in INIT_ENVIRONMENT if key in os.environ}
    try:
        native = execute_native(command, out, c)
    finally:
        os.environ.update(overrides)
    receipt = custody._read(out/'native-provider.json')
    process = custody._read(out/'native-process.json')
    checks = adjudicate(receipt,c,provider,process['pid'])
    if source_before != custody.source_tree(provider) or before != {str(p):custody._hash(p) for p in inputs(task,base)}:
        raise ValueError('provider/runtime source custody changed during qualification')
    result = {'status':'passed' if checks['passed'] else 'failed','physics_validated':False,
        'scope':checks['scope'],'source':c['source'],'checks':checks,'native_execution':native,
        'native_provider':receipt,'generated_events':0,'model_calculation_performed':False,
        'license_evidence':'Actual startup under the existing installation if passed; no activation, credentials, legal rights or future availability inferred.',
        'limitations':['This receipt qualifies source load and evaluated API definitions; no Lagrangian, vertices, UFO export, widths or model consistency.',
           'The loader explicitly reserves two FeynRules package symbols to avoid System name collisions; fresh namespace observations are required, and older readiness evidence remains scoped to its original loader.',
           'Kernel executable/application metadata and complete FeynRules source are pinned; proprietary installed libraries and OS runtime remain outside this finite capsule.']}
    if is_sarah:
        result['limitations']=['Readiness loads SARAH definitions only; no Start, model consistency, UFO, width or numerical physics qualification.',
            'Pinned mirror4.15.4 source is not a claim of current official release/distribution rights; full proprietary runtime remains outside this finite capsule.']
    custody._write(out/'model-provider-bridge.json',result)
    return result


def prepare(args):
    if not args.trust_provider_source:
        raise ValueError('explicit --trust-provider-source is required')
    rd=Path(args.rundir).expanduser().absolute(); proposal=rd.with_name(rd.name+'-proposal')
    if rd.exists() or proposal.exists():raise ValueError('fresh provider study/proposal required')
    root=custody._regular(args.feynrules,Path.cwd(),directory=True)
    kernel=custody._regular(args.kernel,Path.cwd()); metadata=custody._regular(args.application_metadata,Path.cwd())
    proposal.mkdir(parents=True)
    manifest=proposal/'provider-source.json';custody._write(manifest,custody.source_tree(root))
    pin=lambda p:{'path':str(p),'sha256':custody._hash(p)}
    c={'schema_version':1,'operation':'wolfram-feynrules-readiness','source':args.source,
       'kernel':pin(kernel),'application_metadata':pin(metadata),'provider_tree':{'root':str(root),'manifest':pin(manifest)},
       'trusted_provider_source':True,'expected_kernel_version':args.expected_kernel_version,'expected_provider_version':'2.3.49',
       'existing_installation_license_status':'unverified_no_activation_or_credentials_requested',
       'max_seconds':args.max_seconds,'max_ram_mib':args.max_ram_mib}
    doc=proposal/'model-provider-bridge.json';custody._write(doc,c);task={'config':str(doc)};inputs(task,proposal)
    policy=custody._read(custody._regular(args.review_policy,Path.cwd()))
    spec={'schema_version':2,'mode':'model-provider-bridge','source':args.source,
      'assumptions':['The exact existing proprietary kernel may or may not start unattended; no activation or credentials are requested.',
          'The attributed provider source is trusted executable Wolfram code; loading definitions is an operational qualification.',
          'Model derivation, exported UFO consistency, widths, independent amplitudes and generator/detector validity require subsequent scoped evidence.'],
      'max_seconds':args.max_seconds+240,'max_attempts':1+policy['policy']['max_redos'],
      'approval_mode':args.approval_mode,'review_policy':policy,'task':task}
    path=proposal/'science.json';custody._write(path,spec)
    from ravel.workflow.science import plan
    plan(rd,path)
    print('Prepared local provider qualification; actual CHECK-IN1 approval is required before kernel/source execution.')
    return 0


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    sub=parser.add_subparsers(dest='command',required=True);p=sub.add_parser('plan')
    p.add_argument('--kernel',required=True);p.add_argument('--application-metadata',required=True)
    p.add_argument('--expected-kernel-version',type=float,choices=READINESS_KERNEL_VERSIONS,default=14.3,
        help='Required actual $VersionNumber; changing the runtime requires a fresh source-bound readiness study.')
    p.add_argument('--feynrules',required=True);p.add_argument('--source',required=True)
    p.add_argument('--trust-provider-source',action='store_true');p.add_argument('--rundir',required=True)
    p.add_argument('--review-policy',required=True);p.add_argument('--max-seconds',type=int,default=60)
    p.add_argument('--max-ram-mib',type=int,default=2048)
    p.add_argument('--approval-mode',choices=('physicist','scripted_yes'),default='physicist')
    from ravel.physics import model_sarah
    model_sarah.cli_arguments(sub.add_parser('plan-sarah'))
    args=parser.parse_args(argv)
    return model_sarah.prepare_readiness(args) if args.command=='plan-sarah' else prepare(args)
