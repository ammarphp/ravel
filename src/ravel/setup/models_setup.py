"""Guided provider discovery, model recommendation and operator configuration."""
import argparse
from datetime import datetime, timezone
import json
import math
import os
import shlex
import shutil
import subprocess
import sys
import uuid

from ravel.workflow import model_catalogue as mc, models_cli as models, transport_registry as tr
from . import model_usage


CLI_FAMILIES = {'claude': 'anthropic', 'codex': 'openai', 'gemini': 'google'}


def _status(argv, *, help_text=False):
    try:
        done = subprocess.run(argv, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE if help_text else subprocess.DEVNULL,
                              stderr=subprocess.DEVNULL, text=True, timeout=10)
        return done.returncode, (done.stdout or '') if help_text else ''
    except (OSError, subprocess.SubprocessError) as exc:
        return None, type(exc).__name__


def discover_providers(documents=None):
    """Print credential names and presence only; never request password output."""
    documents = tr.all_declarations() if documents is None else documents
    result = {'clis': {}, 'environment': {}}
    for name in CLI_FAMILIES:
        executable = shutil.which(name)
        status = 'not_installed'
        if executable:
            status = 'unknown, verify on first use'
            if name == 'codex':
                code, _ = _status([executable, 'login', 'status'])
                status = 'logged_in' if code == 0 else 'not_logged_in' if code is not None else 'unknown, verify on first use'
            elif name == 'claude':
                code, help_text = _status([executable, 'auth', '--help'], help_text=True)
                if code == 0 and 'status' in help_text.split():
                    code, _ = _status([executable, 'auth', 'status'])
                    status = 'logged_in' if code == 0 else 'not_logged_in' if code is not None else 'unknown, verify on first use'
        result['clis'][name] = {'installed': executable is not None, 'login': status}
        print(f'{name}: {status}')
    for name in sorted(models._credential_names(documents)):
        result['environment'][name] = bool(os.environ.get(name))
        print(f'{name}: {"present" if result["environment"][name] else "absent"}')
    return result


def _provider_fix(documents):
    names = sorted(models._credential_names(documents))
    variables = ', '.join(names) or 'an API credential variable from a transport declaration'
    print('No provider found. Install one of the CLIs (claude, codex, gemini) or export one of '
          f'the named variables ({variables}), then rerun `ravel setup-models`.')


def _chosen(doc):
    chosen = {}
    for tier in tr.TIERS:
        for transport in doc['transport_preference']:
            model = doc['tier_models'][tier].get(transport)
            if model:
                chosen[tier] = {'model': model, 'transport': transport}
                break
    return chosen


def _observed_model(text, names, launcher=None):
    """Read only model metadata from structured CLI output, discarding answer text."""
    if launcher in CLI_FAMILIES:
        from ravel.workflow import cli_agent_host
        parse = (cli_agent_host._claude if launcher == 'claude' else cli_agent_host._codex
                 if launcher == 'codex' else lambda output: cli_agent_host._google('gemini', output))
        try:
            observed = parse(text).get('observed_model')
            if models.safe_model(observed, names):
                return observed
        except (ValueError, TypeError, KeyError, AttributeError, cli_agent_host.AgentCLIError):
            pass  # A CLI version may report metadata in a simpler JSON envelope.
    found = []
    def visit(value):
        if isinstance(value, dict):
            for key in ('model', 'observed_model', 'model_reported'):
                if models.safe_model(value.get(key), names):
                    found.append(value[key])
            for key in ('modelUsage', 'models'):
                if isinstance(value.get(key), dict):
                    found.extend(model for model in value[key] if models.safe_model(model, names))
            for child in value.values():
                if isinstance(child, (dict, list)):
                    visit(child)
        elif isinstance(value, list):
            for child in value:
                visit(child)
    try:
        visit(json.loads(text))
    except ValueError:
        for line in text.splitlines():
            try:
                visit(json.loads(line))
            except ValueError:
                continue
    return found[-1] if found else None


def qualification_remedy(transport, model):
    return (f'Run `ravel transports probe {transport}`, then as the operator run '
            f'`ravel transport qualify {transport} --rundir /path/to/empty-qualification '
            f'--model {model}` (paid conformance; use a separate empty directory per model). '
            'For a controller run, add `--controller-rundir /path/to/controller-run`.')


def static_role_coverage(preferences, documents=None):
    """Check effective cards against declared candidates, without probes or qualification custody.

    This is structural eligibility only. The real selector still requires current
    observed capabilities and protected qualification records before dispatch.
    """
    from ravel.controller.step import seats
    from ravel.workflow import role_registry
    documents = tr.all_declarations() if documents is None else documents
    indexed = {d['id']: d for d in documents}
    inventory = seats.wired_transports()
    wired = set(inventory['wired'])
    excluded = {r['transport']: r['reason'] for r in inventory['excluded']}
    covered, uncovered = {}, []
    cards = role_registry.all_cards()
    for card in cards:
        candidates = []
        for transport in preferences['transport_preference']:
            document = indexed.get(transport)
            tier, model = card['model']['tier'], None
            missing = []
            if document is None:
                missing.append('declaration:' + transport)
            else:
                if transport not in wired:
                    missing.append(excluded.get(transport, 'governed_transport:not_wired'))
                structural = seats.seat_problem(document)
                if structural:
                    missing.append(structural)
                # Use declared capabilities for this static question. Qualification
                # is the one evidence prerequisite deliberately left for live setup.
                missing.extend(reason for reason in tr.unmet(
                    document, document['capabilities'], card, registered={}) if reason != 'qualification')
                if card['model']['effort'] is not None and not document['capabilities']['effort_control']:
                    missing.append('effort')
                tier = tr.effective_tier(card, document, preferences)
                model = preferences['tier_models'].get(tier, {}).get(transport)
                if not model:
                    missing.append('model:' + str(tier))
                else:
                    for problem in (mc.problem(model), tr.catalogue_requirement_problem(
                            model, tier, card['model']['effort']), tr.model_problem(
                                document, model, preferences.get('model_families'))):
                        if problem:
                            missing.append(problem)
            candidate = {'transport': transport, 'model': model, 'tier': tier,
                         'effort': card['model']['effort'], 'missing': sorted(set(missing))}
            candidates.append(candidate)
            if not missing:
                covered[card['id']] = candidate
                break
        else:
            uncovered.append({'role': card['id'], 'candidates': candidates})
    return {'roles': len(cards), 'covered': covered, 'uncovered': uncovered}


def print_static_role_coverage(result):
    if not result['uncovered']:
        print(f'Static capability coverage: {len(result["covered"])}/{result["roles"]} registered roles '
              'have a suitable configured candidate; live qualification remains required.')
        return
    print(f'Static capability coverage failed: {len(result["uncovered"])}/{result["roles"]} registered '
          'roles have no structurally suitable configured candidate.')
    groups = {}
    for row in result['uncovered']:
        for candidate in row['candidates']:
            key = (candidate['transport'], candidate['model'], candidate['tier'], candidate['effort'],
                   tuple(candidate['missing']))
            groups.setdefault(key, []).append(row['role'])
    for (transport, model, tier, effort, missing), roles in groups.items():
        print(f'{transport} / {model}: tier={tier}, required effort={effort}; missing: '
              + ', '.join(missing) + f'; {len(roles)} affected roles: ' + ', '.join(roles))
    print('Choose a capable provider/transport and a catalogue model row supporting the required tier and effort; '
          'rerun `ravel setup-models --preset balanced`. Keep the card requirements unchanged. '
          'After static coverage succeeds, probe and qualify the chosen candidates as the operator.')
    print(qualification_remedy('TRANSPORT_ID', 'MODEL_ID'))


def verify_models(doc, *, yes=False, documents=None, cost_cap_usd=1.0):
    """Operator opt-in to the existing governed live conformance qualification."""
    from ravel.controller.authority import operator
    from ravel.controller.step import seats
    from ravel.workflow.transports import cli_worker
    operator._refuse_agent('ravel setup-models --verify')
    if not math.isfinite(cost_cap_usd) or cost_cap_usd <= 0:
        raise ValueError('verification cost cap must be finite and positive')
    documents = tr.all_declarations() if documents is None else documents
    indexed = {d['id']: d for d in documents}
    wired = set(seats.wired_transports()['wired'])
    targets = list(dict.fromkeys((c['transport'], c['model']) for c in _chosen(doc).values()))
    if not targets:
        print('No selected models to qualify; configure candidates with `ravel setup-models --preset balanced`.')
        return False
    if any(t not in wired or t not in indexed for t, _ in targets):
        print('Selected transport is not wired for governed seats; run `ravel transports list` and choose a wired route.')
        return False
    # The conformance spec allows eight turns, twelve broker calls and 600 seconds.
    # Full CLI context and provider reasoning are not bounded by this token scenario.
    costs = [mc.price(dict(zip(mc._USAGE_KEYS, (64000, 0, 0, 16000))), m)['cost_usd'] for _, m in targets]
    total = None if None in costs else math.fsum(costs)
    print(f'Live qualification: {len(targets)} conformance runs; ESTIMATED USD '
          f'{total if total is not None else "unknown"} scenario (8 turns, 8000 input and 2000 output '
          'tokens per turn). Each run permits up to 8 turns, 12 broker calls and 600 seconds. '
          'The scenario is not an upper bound. Subscription billing uses the operator login; no monetary '
          'cap is enforced for subscription qualification. API qualification requires an authorised finite cap. '
          'Qualification tests broker read/write, structured completion, isolation and identity; '
          'it is a paid task, not a tiny prompt. Unknown or substituted model identity fails setup verification.')
    for transport, model in targets:
        if indexed[transport]['billing'] == 'subscription':
            print(f'{transport}: subscription billing; max_cost_usd=None (no monetary cap).')
        else:
            print(f'{transport}: authorised maximum USD {cost_cap_usd} per conformance run.')
            if indexed[transport]['billing'] == 'api':
                try:
                    bound = mc.call_bound(model)['cost_usd']
                except ValueError:
                    print(f'{model}: conservative call bound unknown; add catalogue pricing/context limits before qualification.')
                    return False
                print(f'{model}: context-full call reservation USD {bound}; up to 8 calls USD {8 * bound}.')
                if cost_cap_usd < bound:
                    print('Verification cap is below one conservative call reservation. Rerun with an explicitly '
                          'authorised `--verification-cost-cap-usd` value at least that reservation.')
                    return False
    if not yes and input('Run these paid conformance qualifications? [y/N] ').strip().lower() != 'y':
        print('Live qualification skipped; selected candidates remain unverified.')
        return True
    records = []
    for transport, model in targets:
        row = {'transport_id': transport, 'requested_model': model, 'observed_model': None,
               'status': 'failed'}
        try:
            run = tr.state_dir() / 'setup-qualifications' / uuid.uuid4().hex
            result = cli_worker.qualify(transport, rundir=run, model=model,
                                        max_cost_usd=None if indexed[transport]['billing'] == 'subscription'
                                        else cost_cap_usd)
            observed = result.get('observed', {})
            row['observed_model'] = observed.get('model')
            steps = result.get('steps')
            if (result.get('status') == 'live_qualified' and result.get('transport_id') == transport
                    and observed.get('requested_model') == model and seats.model_matches(model, observed.get('model'))
                    and steps and all(s.get('passed') is True for s in steps)):
                row['status'] = 'qualified'
        except (OSError, ValueError) as exc:
            row['error_class'] = type(exc).__name__
        records.append(row)
        print(f'{model}: {row["status"]}; observed_model={row["observed_model"]}')
        if row['status'] != 'qualified':
            print(qualification_remedy(transport, model))
    models._write_private(tr.state_dir() / 'models-setup.receipt.json',
                          {'schema_version': 1, 'kind': 'model-verification',
                           'verified_utc': datetime.now(timezone.utc).isoformat(), 'receipts': records})
    return all(row['status'] == 'qualified' for row in records)


def parser():
    ap = argparse.ArgumentParser(prog='ravel setup-models', description=__doc__)
    ap.add_argument('--yes', action='store_true', help='choose balanced defaults and confirm optional verification')
    ap.add_argument('--preset', choices=('premium', 'balanced', 'economy'))
    ap.add_argument('--verify', action='store_true', help='opt in to paid governed conformance qualification')
    ap.add_argument('--verification-cost-cap-usd', type=float, default=1.0,
                    help='positive per-qualification API spending cap in USD (default 1; subscriptions have no monetary cap)')
    ap.add_argument('--cost-cap-usd', type=float, help='optional per-run operator spending ceiling')
    ap.add_argument('--usage-context', help='private account-plan, remaining-capacity and reset-window JSON snapshot')
    ap.add_argument('--prior-usage', action='append', default=[],
                    help='exported measured model-cost JSON from a comparable prior run; repeat for an envelope')
    ap.add_argument('--prior-run', action='append', default=[],
                    help='existing controller run id whose reconciled usage supplies a comparable workload')
    return ap


def main(argv=None):
    args = parser().parse_args(argv)
    try:
        if not math.isfinite(args.verification_cost_cap_usd) or args.verification_cost_cap_usd <= 0:
            raise ValueError('verification cost cap must be finite and positive')
        if args.cost_cap_usd is not None and (not math.isfinite(args.cost_cap_usd) or args.cost_cap_usd < 0):
            raise ValueError('spending cap must be finite and nonnegative; use `--cost-cap-usd 1` or omit it')
        usage_context = model_usage.load_context(args.usage_context) if args.usage_context else None
        prior_usage = [model_usage.load_prior(path) for path in args.prior_usage]
        prior_usage.extend(model_usage.load_run(run_id) for run_id in args.prior_run)
        documents = tr.all_declarations()
        providers = discover_providers(documents)
        record = models.detect_models(documents)
        for row in record['transports']:
            if row['status'] == 'unreachable':
                print(f'{row["id"]}: {row["error_class"]}; check network/credentials; rerun `ravel models detect`.')
        # A known failed login is unavailable; a CLI without a status command remains declared.
        unavailable = {name for name, state in providers['clis'].items() if state['login'] == 'not_logged_in'}
        for row in record['transports']:
            doc = next(d for d in documents if d['id'] == row['id'])
            if doc['launcher'] in unavailable and doc['auth']['kind'] == 'login':
                row['status'] = 'no_credential'
        models._write_private(models.detection_path(), record)
        inventory = record['governed_inventory']
        print('Governed wired transports: ' + (', '.join(inventory['wired']) or 'none'))
        for exclusion in inventory['excluded']:
            print(f'{exclusion["transport"]}: excluded from governed seats: {exclusion["reason"]}')
        if not inventory['wired']:
            print('No wired governed route. Configure a supported worker/loop transport; '
                  'then probe and qualify it as the operator. `ravel transports list` shows declarations.')
            print(qualification_remedy('TRANSPORT_ID', 'MODEL_ID'))
        available, _ = models.available_documents(record)
        if not available:
            _provider_fix(documents)
            return 2
        preset = args.preset or 'balanced'
        preferred, excluded, cap = None, [], args.cost_cap_usd
        if not args.yes and args.preset is None:
            spending = input('Spending per typical run: generous, balanced, economical [balanced]: ').strip().lower()
            choices = {'': 'balanced', 'generous': 'premium', 'premium': 'premium', 'balanced': 'balanced',
                       'economical': 'economy', 'economy': 'economy'}
            if spending not in choices:
                raise ValueError('choose generous, balanced or economical; rerun `ravel setup-models`')
            preset = choices[spending]
            provider_list = input('Preferred provider families, comma-separated (prefix exclusions with -) [all wired candidates]: ').strip()
            choices = [x.strip() for x in provider_list.split(',') if x.strip()]
            preferred = [x for x in choices if not x.startswith('-')] or None
            excluded = [x[1:] for x in choices if x.startswith('-')]
            known = dict(tr.FAMILY_PATTERNS)
            if any(x not in known for x in (preferred or []) + excluded):
                raise ValueError('unknown provider family; choose from ' + ', '.join(known))
            answer = input('Optional per-run spending cap in USD [keep current]: ').strip()
            if answer:
                cap = float(answer)
            if cap is not None and (not math.isfinite(cap) or cap < 0):
                raise ValueError('spending cap must be a finite nonnegative USD amount')
        doc, omitted, _ = models.preferences(preset, record=record, preferred=preferred, excluded=excluded)
        alternatives = [models.preferences(other, record=record, preferred=preferred, excluded=excluded)[0]
                        for other in ('premium', 'balanced', 'economy') if other != preset] if usage_context else []
        doc, usage_report = model_usage.recommend(doc, documents=documents, context=usage_context,
                                                 prior_runs=prior_usage, alternatives=alternatives)
        if usage_report['status'] == 'recommended':
            print('Usage recommendation: measured prior-run scenario, account plans and current reset windows; '
                  f'unknown capacity components={usage_report["unknown_capacity_components"]}.')
        else:
            print('Usage recommendation: unknown (' + ', '.join(usage_report['reasons']) + '); preset retained.')
        problems = models.preference_problems(doc)
        if problems:
            print('\n'.join(problems))
            return 2
        chosen = _chosen(doc)
        if any(tier not in chosen for tier in tr.TIERS):
            for row in record['transports']:
                for model in row['models']:
                    if model['status'] == 'listed' and not model['catalogued']:
                        print(mc.remedy(model['id']))
            _provider_fix(documents)
            print('No complete tier selection; add catalogue rows for the omitted tiers: ' + json.dumps(omitted))
            return 2
        coverage = static_role_coverage(doc, documents)
        print_static_role_coverage(coverage)
        if coverage['uncovered']:
            return 2
        if not any(m['status'] == 'qualified' for r in record['transports'] for m in r['models']
                   if r['id'] in doc['transport_preference']):
            print('No selected route has current model qualification evidence; candidates can be configured now.')
        for tier, choice in chosen.items():
            row = next(r for r in record['transports'] if r['id'] == choice['transport'])
            evidence = next((m['status'] for m in row['models'] if m['id'] == choice['model']), 'declared')
            print(f'{tier}: {choice["model"]} via {choice["transport"]}: {evidence}'
                  + (' (unverified candidate)' if evidence in ('declared', 'listed') else ''))
            if evidence != 'qualified':
                print(qualification_remedy(choice['transport'], choice['model']))
        print('Preferences select candidates; governed roles still require current probe and '
              'qualification evidence in the controller run. Listing does not establish qualification.')
        print(f'Recommended preset: {preset}. Tier candidates: '
              f'judgment={chosen["judgment"]["model"]}, agent={chosen["agent"]["model"]}, '
              f'cheap={chosen["cheap"]["model"]}. Role selection checks capabilities, effort and qualification.')
        models.print_estimate(models.estimate(preset, document=doc))
        from ravel.controller.authority import operator
        try:
            operator._refuse_agent('ravel operator set')
        except ValueError as exc:
            print(str(exc))
            command = 'ravel operator set --agent-preferences ' + shlex.quote(json.dumps(doc, separators=(',', ':')))
            if cap is not None:
                command += ' --budget ' + shlex.quote(f'cost_usd={cap}')
            if operator.operator_config()['source'] == 'default':
                print('First initialize the operator ledger: ravel operator init --mode physicist-in-the-loop')
            print(command)
            return 2
        if args.verify and not verify_models(doc, yes=args.yes, documents=documents,
                                              cost_cap_usd=args.verification_cost_cap_usd):
            return 2
        models.write_preferences(doc, cap)
        models._write_private(tr.state_dir() / 'models-setup.usage.json', usage_report)
        print('Operator model preferences saved.' + (f' Per-run cap: USD {cap}.' if cap is not None else ''))
        return 0
    except (OSError, ValueError, KeyError, EOFError) as exc:
        print(str(exc))
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
