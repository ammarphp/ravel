"""Declared output contracts: intake reading, obligation rows and the final observation.

Failure class: a request names where its deliverables go and what they may hold, but no
obligation records it and no final check observes it, so a run can finish with the declared
file missing, malformed, linked elsewhere or surrounded by undeclared files. Every request,
path and file here is fictional; nothing is executed and no model is called.
"""
import json
import os
from pathlib import Path

import pytest

from ravel.workflow import output_contract as oc
from ravel.workflow import task_completion as tc


def items(prompt):
    return [{k: v for k, v in item.items() if k not in ('evidence', 'id')} for item in oc.read(prompt)['items']]


def files(prompt):
    return [(i['anchor'], i['path']) for i in items(prompt) if i['type'] == 'file']


def locations(prompt):
    return [(i['path'], i['exclusive'], i['allowed'], i['required']) for i in items(prompt) if i['type'] == 'location']


def bound_rows(prompt, workspace, room=64):
    return oc.obligations(oc.bind(oc.read(prompt), workspace), room=room)


def write(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data.encode() if isinstance(data, str) else data)
    return path


def codes(report):
    return sorted({v['code'] for v in report['violations']})


# ------------------------------------------------------------------ reading: what is declared
@pytest.mark.parametrize('prompt, expected', [
    ('Write your final answer to `results/answer.yaml`.', [('workspace', 'results/answer.yaml')]),
    ('Save the fitted values as fit.json.', [('workspace', 'fit.json')]),
    ('Store the table in out/table.csv.', [('workspace', 'out/table.csv')]),
    ('Final answer: `answer.yaml`', [('workspace', 'answer.yaml')]),
    ('The results must be written to out/final.json.', [('workspace', 'out/final.json')]),
    ('Results go in `out/run.json`.', [('workspace', 'out/run.json')]),
    ('Your submission must be a single YAML file named `prediction.yaml` in the `submit/` directory.',
     [('workspace', 'submit/prediction.yaml')]),
    ('Deliver the summary at /tmp/fictional-ws/summary.txt.', [('absolute', '/tmp/fictional-ws/summary.txt')]),
    ('Save it to ~/fictional/res.json.', [('home', 'fictional/res.json')]),
    ("Don't forget to write the answer to final.json.", [('workspace', 'final.json')]),
    ('Write the answer to ./out/../out/a.yaml.', [('workspace', 'out/a.yaml')]),
    ('Create a file named `notes` holding your reasoning.', [('workspace', 'notes')]),
])
def test_output_cues_declare_their_paths(prompt, expected):
    assert files(prompt) == expected


@pytest.mark.parametrize('prompt', [
    'Use the cards in cards/param_card.dat.',
    'Read the inputs from data/events.lhe.',
    'Do not write to data/out.json.',
    'Never save anything in /etc/fictional.conf.',
    'Use the events stored in events/sample.hepmc.',
    'Results should match those in ref/table.csv.',
    'Results are available in results/old.json.',
    'Please save the limits as limits.json in the output folder.',  # location named only in words
    'Compute the rate (see entry:12.34, e.g. Fig. 3, version 1.3.0) and report it.',
    'Use SR/CR definitions and/or the numerator/denominator from the paper.',
    'Example:\n```\nwrite the answer to example/answer.yaml\n```\n',
    '> Earlier note: save everything to quoted/old.json\nSummarise the note.',
])
def test_inputs_negations_and_undetermined_paths_declare_nothing(prompt):
    assert oc.read(prompt)['items'] == []


@pytest.mark.parametrize('prompt', [
    'Normalise the histogram to unit area and report it in a.u.',
    'Report the fitted signal strength as np.float64.',
    'Return the result as `np.float64`.',
    'Report the limit as the fitlib.infer output.',
    'The helper should return json.loads(text) unchanged.',
])
def test_dotted_identifiers_and_abbreviations_are_not_declared_files(prompt):
    # A bare dotted name is a file only when its extension names a file type; otherwise the
    # final check would refuse delivery for a file nobody asked for.
    assert oc.read(prompt)['items'] == []


def test_bare_names_with_file_type_extensions_and_named_files_are_declared():
    assert files('Save the model as model.onnx.') == [('workspace', 'model.onnx')]
    assert files('Write the macro to plot.C and the plugin to plugin.so.') == [
        ('workspace', 'plot.C'), ('workspace', 'plugin.so')]
    assert files('Store the fitted values as values.npz.') == [('workspace', 'values.npz')]
    assert files('Write the couplings to couplings.f.') == [('workspace', 'couplings.f')]
    assert files('Write the answer to `answer.ndjson`.') == [('workspace', 'answer.ndjson')]
    assert files('Create a file named `notes.v2` with your reasoning.') == [('workspace', 'notes.v2')]
    assert files('Write the table to out/table.v2.') == [('workspace', 'out/table.v2')]


def test_inputs_and_outputs_in_one_sentence_are_separated():
    prompt = 'Read the events from data/events.lhe and write the histogram to out/hist.csv.'
    assert files(prompt) == [('workspace', 'out/hist.csv')]
    prompt = 'Create a plot from data in data/x.csv and save it as plot.png.'
    assert files(prompt) == [('workspace', 'plot.png')]
    prompt = 'Load the model in models/m.onnx and save predictions in out/pred.csv.'
    assert files(prompt) == [('workspace', 'out/pred.csv')]


def test_a_contrasted_or_separately_placed_directory_is_not_joined():
    assert files('Write the results to out.json, not to data/.') == [('workspace', 'out.json')]
    prompt = 'Write intermediate files to scratch/ and the final answer to answer.yaml'
    assert files(prompt) == [('workspace', 'answer.yaml')]
    assert locations(prompt) == [('scratch', None, [], True)]


def test_a_pronoun_places_the_previous_file_in_its_named_directory():
    prompt = 'Write `answer.yaml`. It must be the only file in the `out/` directory.'
    assert files(prompt) == [('workspace', 'out/answer.yaml')]
    assert locations(prompt) == [('out', 'only', ['answer.yaml'], False)]
    assert files('Write answer.yaml. Put it in the `final/` directory.') == [('workspace', 'final/answer.yaml')]


def test_formats_follow_extension_or_statement():
    assert items('Write the answer to out/a.yml.')[0]['format'] == 'yaml'
    assert items('Write the result to result.txt in JSON format.')[0]['format'] == 'json'
    assert items('Save the plot as plot.pdf.')[0]['format'] == 'pdf'
    assert items('Write the events to events/run.lhe.gz.')[0]['format'] is None


@pytest.mark.parametrize('prompt, names, closed, container', [
    ('Write a JSON file with fields mass and width to results/fit.json', ['mass', 'width'], False, 'keys'),
    ('Write out/hist.csv with columns bin, count.', ['bin', 'count'], False, 'columns'),
    ('Deliver answer.json containing only the keys "value" and "error".', ['value', 'error'], True, 'keys'),
    ('Write answer.yaml with keys `mass` and `width` and nothing else.', ['mass', 'width'], True, 'keys'),
    ('Write answer.yaml with the field `limit`.', ['limit'], False, 'keys'),
])
def test_declared_keys_and_columns(prompt, names, closed, container):
    assert items(prompt)[0]['keys'] == {'names': names, 'closed': closed, 'container': container}


@pytest.mark.parametrize('prompt', [
    'Write answer.yaml with the fields described below.',
    'Write answer.yaml with the field limit.',  # a single bare word is not an exact list
    'Write answer.yaml with keys mass, width or coupling.',  # alternatives are not a declared set
])
def test_inexact_key_statements_declare_no_keys(prompt):
    assert items(prompt)[0]['keys'] is None


def test_a_fenced_template_after_a_format_statement_declares_required_keys():
    prompt = ('Write your answer to answer.yaml in the following format:\n```yaml\nmass_gev: <value>\n'
              'excluded: <true|false>\n```\nThank you.')
    [item] = items(prompt)
    assert item['keys'] == {'names': ['mass_gev', 'excluded'], 'closed': False, 'container': 'keys'}
    unparsable = 'Write your answer to answer.yaml in the following format:\n```\n: : [\n```\n'
    assert items(unparsable)[0]['keys'] is None


@pytest.mark.parametrize('prompt, expected', [
    ('The output directory `deliverables/` must contain only `summary.json` and `plot.pdf`.',
     [('deliverables', 'only', ['plot.pdf', 'summary.json'], True)]),
    ('Results go in `out/run.json`; do not create any other files.', [('out', 'no_new', ['run.json'], False)]),
    ('Write the answer to out/a.yaml. Do not put anything else in out/.', [('out', 'no_new', ['a.yaml'], False)]),
    ('Deliver exactly one file, /tmp/fictional-ws/answer.json.',
     [('/tmp/fictional-ws', 'no_new', ['answer.json'], False)]),
    ('Write only `answer.yaml`.', [('.', 'no_new', ['answer.yaml'], False)]),
    ('No other files may be written. Save the result as res.json.', [('.', 'no_new', ['res.json'], False)]),
    # An unnamed location is not known to be the file's parent alone: only "nothing new" is certain.
    ('Write answer.yaml; the submission directory must contain only answer.yaml.',
     [('.', 'no_new', ['answer.yaml'], False)]),
])
def test_exclusivity_statements_govern_their_locations(prompt, expected):
    assert locations(prompt) == expected


@pytest.mark.parametrize('prompt', [
    'Write the report to report.md. Only the report will be read.',
    'Make sure to write only the final answer to out.txt',  # content, not other files
    'In answer.txt, write only the number; do not write anything else.',
    'Put the plot in figures/ and nothing else.',  # names no deliverable to allow
])
def test_content_restrictions_and_unlocatable_exclusivity_are_not_location_rules(prompt):
    assert all(row[1] is None for row in locations(prompt))


def test_evidence_spans_are_exact_and_reading_is_deterministic():
    prompt = 'Intro line.\nWrite the answer to `out/a.json` with keys `x` and `y`. Do not create any other files.'
    first, second = oc.read(prompt), oc.read(prompt)
    assert first == second and first['workspace'] is None
    assert first['prompt_sha256'] == __import__('hashlib').sha256(prompt.encode()).hexdigest()
    for item in first['items']:
        assert item['evidence']
        for span in item['evidence']:
            assert prompt[span['start']:span['end']] == span['text']
    assert [i['id'] for i in first['items']] == ['F1', 'L2']


def test_reader_refuses_unbounded_input_and_too_many_paths():
    with pytest.raises(ValueError):
        oc.read('   ')
    many = ' '.join(f'Write part {i} to out/p{i}.json.' for i in range(oc.MAX_ITEMS + 1))
    with pytest.raises(ValueError, match='more than'):
        oc.read(many)
    unbroken = ', '.join(f'save part {i} to out/p{i}.json' for i in range(4 * oc.MAX_ITEMS))
    with pytest.raises(ValueError, match='more than'):
        oc.read(unbroken)


class _Scanned:
    """A compiled pattern that counts the characters each of its calls may scan."""

    def __init__(self, pattern, counter):
        self.pattern, self.counter = pattern, counter

    def _call(self, name, string, pos=0, endpos=None):
        end = len(string) if endpos is None else min(endpos, len(string))
        self.counter[0] += max(0, end - pos)
        return getattr(self.pattern, name)(string, pos, end)

    def search(self, *args):
        return self._call('search', *args)

    def finditer(self, *args):
        return self._call('finditer', *args)

    def __getattr__(self, name):
        return getattr(self.pattern, name)


def test_reading_work_grows_linearly_along_an_unbroken_line_of_paths(monkeypatch):
    # A pasted listing on one line is one long sentence; a look-back from every path to the
    # sentence start made reading quadratic, and intake reads every routed request.
    counter = [0]
    for name in ('_CUE', '_LINKED', '_LOCATION_LEAD', '_ALLOWED_LEAD', '_NEGATION', '_UNNAMED_LOCATION'):
        monkeypatch.setattr(oc, name, _Scanned(getattr(oc, name), counter))

    def work(count):
        counter[0] = 0
        prompt = ' '.join(f'see data{i}/part{i}.json' for i in range(count)) + ' and write the answer to out/a.json'
        assert files(prompt) == [('workspace', 'out/a.json')]
        return counter[0]
    assert work(1200) < 2.5 * work(600)


def test_a_negation_beyond_the_look_back_declares_nothing():
    listing = ' '.join(f'see data{i}/part{i}.json' for i in range(100))
    assert len(listing) > 2000
    assert files('Do not ' + listing + ' write the answer to out/a.json.') == []
    assert files('Do not ' + listing + ', then write the answer to out/a.json.') == [('workspace', 'out/a.json')]


# ------------------------------------------------------------------ obligations and intake binding
def test_obligations_extend_a_valid_task_census(tmp_path):
    prompt = 'Write the answer to `out/a.json` with keys `x` and `y`. Do not create any other files.'
    census = tc.initial_requirements(prompt)
    rows = bound_rows(prompt, tmp_path)
    census['obligations'] += rows
    tc.validate_requirements({'prompt': prompt, 'task_requirements': census})
    assert [r['id'] for r in rows] == ['output-contract-F1', 'output-contract-L2']
    assert all(r['kind'] == 'deliverable' for r in rows)
    declared = rows[0]['criteria'][oc.CRITERIA_KEY]
    assert declared['workspace'] == str(tmp_path) and declared['path'] == 'out/a.json'
    assert 'out/a.json' in rows[0]['statement'] and 'x, y' in rows[0]['statement']
    assert rows[1]['criteria'][oc.CRITERIA_KEY]['baseline'] == {'names': []}
    assert oc.rows({'task_requirements': census}) == rows


def test_a_short_census_receives_one_combined_obligation(tmp_path):
    prompt = 'Write a.json to out/a.json. Write b.json to out/b.json. Do not create any other files.'
    rows = bound_rows(prompt, tmp_path, room=1)
    assert len(rows) == 1 and rows[0]['id'] == 'output-contract-all'
    assert [i['id'] for i in rows[0]['criteria'][oc.CRITERIA_KEY]['items']] == ['F1', 'F2', 'L3']
    write(tmp_path / 'out/a.json', '{}')
    assert codes(oc.check(rows)) == ['missing']
    with pytest.raises(ValueError, match='no room'):
        bound_rows(prompt, tmp_path, room=0)
    assert oc.obligations(oc.read('Summarise the paper.'), room=0) == []


def test_binding_records_existing_entries_of_a_no_new_location(tmp_path):
    write(tmp_path / 'supplied/input.dat', 'fictional')
    rows = bound_rows('Write the answer to answer.yaml; do not create any other files.', tmp_path)
    assert rows[1]['criteria'][oc.CRITERIA_KEY]['baseline'] == {'names': ['supplied']}
    with pytest.raises(ValueError, match='existing directory'):
        oc.bind(oc.read('Write the answer to answer.yaml.'), tmp_path / 'absent')


def test_a_large_baseline_is_recorded_by_digest(tmp_path):
    for i in range(400):
        write(tmp_path / f'supplied-input-file-{i:04d}.dat', 'x')
    rows = bound_rows('Write the answer to answer.yaml; do not create any other files.', tmp_path)
    baseline = rows[1]['criteria'][oc.CRITERIA_KEY]['baseline']
    assert set(baseline) == {'count', 'sha256'} and baseline['count'] == 400
    write(tmp_path / 'answer.yaml', 'a: 1\n')
    assert oc.check(rows)['satisfied']
    write(tmp_path / 'sidecar.log', 'extra')
    assert codes(oc.check(rows)) == ['location_changed']


def test_a_digest_baseline_excludes_a_deliverable_present_at_intake(tmp_path):
    for i in range(400):
        write(tmp_path / f'supplied-input-file-{i:04d}.dat', 'x')
    write(tmp_path / 'answer.yaml', 'draft: 1\n')  # an earlier draft of the declared deliverable
    rows = bound_rows('Write the answer to answer.yaml; do not create any other files.', tmp_path)
    assert 'sha256' in rows[1]['criteria'][oc.CRITERIA_KEY]['baseline']
    assert oc.check(rows)['satisfied']
    (tmp_path / 'answer.yaml').unlink()
    assert codes(oc.check(rows)) == ['missing']
    write(tmp_path / 'answer.yaml', 'a: 1\n')
    write(tmp_path / 'sidecar.log', 'extra')
    assert codes(oc.check(rows)) == ['location_changed']


def test_resolution_keeps_the_original_binding(tmp_path):
    prompt = 'Write the answer to answer.yaml; do not create any other files.'
    first = oc.census_rows(prompt, room=10, workspace=tmp_path)
    write(tmp_path / 'created-later.txt', 'scratch')
    again = oc.census_rows(prompt, room=10, workspace=tmp_path / 'created-later.txt', retained=first)
    assert again == first
    other = oc.census_rows('Write the answer to other.yaml; do not create any other files.', room=10,
                           workspace=tmp_path)
    with pytest.raises(ValueError, match='differ'):
        oc.census_rows(prompt, room=10, retained=other)
    assert oc.census_rows('Summarise the paper.', room=10, workspace=tmp_path) == []


def test_record_validation_rejects_open_or_malformed_records():
    record = oc.read('Write the answer to answer.yaml.')
    for change in ({'extra': 1}, {'workspace': 'relative/ws'}, {'schema_version': 2}):
        with pytest.raises(ValueError):
            oc.validate_record({**record, **change})
    broken = json.loads(json.dumps(record))
    broken['items'][0]['anchor'] = 'absolute'
    with pytest.raises(ValueError, match='absolute'):
        oc.validate_record(broken)


# ------------------------------------------------------------------ the final observation
def test_conforming_deliverables_satisfy_the_contract(tmp_path):
    prompt = ('Write the answer to `out/a.json` containing only the keys "value" and "error". '
              'Do not create any other files.')
    rows = bound_rows(prompt, tmp_path)
    write(tmp_path / 'out/a.json', '{"value": 1.5, "error": 0.2}')
    report = oc.require(rows)
    assert report['satisfied'] and report['declared'] and not report['semantic_content_verified']
    observed = report['items'][0]['observed']
    assert observed['size'] == len('{"value": 1.5, "error": 0.2}') and len(observed['sha256']) == 64


def test_missing_link_special_and_empty_deliverables_are_violations(tmp_path):
    rows = bound_rows('Write the answer to out/a.json.', tmp_path)
    assert codes(oc.check(rows)) == ['missing']
    write(tmp_path / 'elsewhere.json', '{}')
    (tmp_path / 'out').mkdir()
    os.symlink(tmp_path / 'elsewhere.json', tmp_path / 'out/a.json')
    assert codes(oc.check(rows)) == ['symbolic_link']
    (tmp_path / 'out/a.json').unlink()
    (tmp_path / 'out/a.json').mkdir()
    assert codes(oc.check(rows)) == ['not_regular_file']
    (tmp_path / 'out/a.json').rmdir()
    write(tmp_path / 'out/a.json', '')
    assert codes(oc.check(rows)) == ['empty']


@pytest.mark.parametrize('name, data, code', [
    ('a.json', '{"value": 1, "value": 2}', 'format'),
    ('a.json', '{"value": NaN}', 'format'),
    ('a.json', 'not json', 'format'),
    ('a.yaml', 'value: 1\nvalue: 2\n', 'format'),
    ('a.yaml', 'a: 1\n---\nb: 2\n', 'format'),
    ('a.csv', 'x,y\n1,2,3\n', 'format'),
    ('a.toml', 'x = [', 'format'),
    ('a.txt', b'\xff\xfe', 'format'),
    ('a.pdf', 'plain text', 'format'),
    ('a.png', b'\x89PNG\r\n\x1a\n' + b'\x00' * 8, None),
])
def test_declared_formats_are_parsed_strictly(tmp_path, name, data, code):
    rows = bound_rows(f'Write the answer to out/{name}.', tmp_path)
    write(tmp_path / 'out' / name, data)
    assert codes(oc.check(rows)) == ([code] if code else [])


def test_declared_keys_and_columns_are_observed(tmp_path):
    rows = bound_rows('Deliver answer.json containing only the keys "value" and "error".', tmp_path)
    write(tmp_path / 'answer.json', '{"value": 1}')
    assert codes(oc.check(rows)) == ['missing_keys']
    write(tmp_path / 'answer.json', '{"value": 1, "error": 2, "note": "x"}')
    report = oc.check(rows)
    assert codes(report) == ['extra_keys'] and 'note' in report['violations'][0]['message']
    write(tmp_path / 'answer.json', '[1, 2]')
    assert codes(oc.check(rows)) == ['not_mapping']
    table = bound_rows('Write out/hist.csv with columns bin, count.', tmp_path)
    write(tmp_path / 'out/hist.csv', 'bin,total\n1,2\n')
    assert codes(oc.check(table)) == ['missing_keys']
    write(tmp_path / 'out/hist.csv', 'bin,count,extra\n1,2,3\n')
    assert oc.check(table)['satisfied']  # an open column list allows more columns


def test_exclusive_locations_report_undeclared_entries(tmp_path):
    only = bound_rows('The output directory `deliverables/` must contain only `summary.json` and `plot.pdf`.',
                      tmp_path)
    assert codes(oc.check(only)) == ['location_missing']
    write(tmp_path / 'deliverables/summary.json', '{}')
    assert oc.check(only)['satisfied']
    write(tmp_path / 'deliverables/.hidden-sidecar', 'x')
    write(tmp_path / 'deliverables/nested/log.txt', 'x')
    report = oc.check(only)
    assert codes(report) == ['extra_entry']
    message = report['violations'][0]['message']
    assert '.hidden-sidecar' in message and 'nested' in message
    (tmp_path / 'deliverables/.hidden-sidecar').unlink()
    (tmp_path / 'deliverables/nested/log.txt').unlink()
    (tmp_path / 'deliverables/nested').rmdir()
    os.symlink(tmp_path, tmp_path / 'deliverables/plot.pdf')
    assert codes(oc.check(only)) == ['special_entry']


def test_no_new_locations_keep_entries_present_at_intake(tmp_path):
    write(tmp_path / 'task/brief.txt', 'fictional')
    rows = bound_rows('Results go in `out.json`; do not create any other files.', tmp_path)
    write(tmp_path / 'out.json', '{}')
    assert oc.check(rows)['satisfied']
    write(tmp_path / 'task/added-later.txt', 'x')  # inside a pre-existing entry: not governed
    assert oc.check(rows)['satisfied']
    write(tmp_path / 'out.json.sidecar', 'x')
    write(tmp_path / 'notes/plan.md', 'x')
    report = oc.check(rows)
    assert codes(report) == ['extra_entry']
    assert 'out.json.sidecar' in report['violations'][0]['message']


def test_required_output_location_must_hold_a_file(tmp_path):
    rows = bound_rows('Write the summary into the `report` directory.', tmp_path)
    assert codes(oc.check(rows)) == ['location_missing']
    (tmp_path / 'report').mkdir()
    assert codes(oc.check(rows)) == ['empty_location']
    write(tmp_path / 'report/summary.md', 'x')
    assert oc.check(rows)['satisfied']


def test_unbound_relative_paths_use_an_explicit_workspace_or_fail(tmp_path):
    rows = oc.obligations(oc.read('Write the answer to out/a.json.'))
    assert codes(oc.check(rows)) == ['no_workspace']
    write(tmp_path / 'out/a.json', '{}')
    assert oc.check(rows, workspace=tmp_path)['satisfied']
    other = tmp_path / 'other'
    other.mkdir()
    bound = bound_rows('Write the answer to out/a.json.', tmp_path)
    assert oc.check(bound, workspace=other)['satisfied']  # the intake binding is authoritative


def test_no_new_without_an_intake_record_is_reported(tmp_path):
    rows = oc.obligations(oc.read('Write the answer to answer.yaml; do not create any other files.'))
    write(tmp_path / 'answer.yaml', 'a: 1\n')
    assert codes(oc.check(rows, workspace=tmp_path)) == ['no_baseline']


def test_withdrawn_and_unrelated_obligations_are_not_observed(tmp_path):
    rows = bound_rows('Write the answer to out/a.json.', tmp_path)
    withdrawn = [{**rows[0], 'withdrawn': True}]
    report = oc.check(withdrawn + [{'id': 'original-request', 'criteria': {'request': 'x'}}])
    assert report['satisfied'] and report['items'][0]['status'] == 'withdrawn'
    assert oc.check([{'id': 'original-request', 'criteria': {'request': 'x'}}]) == {
        'schema_version': 1, 'kind': oc.CHECK_KIND, 'declared': False, 'items': [], 'violations': [],
        'satisfied': True, 'semantic_content_verified': False}


def test_malformed_declarations_are_reported_not_trusted(tmp_path):
    rows = bound_rows('Write the answer to out/a.json.', tmp_path)
    rows[0]['criteria'][oc.CRITERIA_KEY]['format'] = 'unknown-format'
    assert codes(oc.check(rows)) == ['invalid_declaration']


def test_oversized_parse_is_reported(tmp_path, monkeypatch):
    rows = bound_rows('Write the answer to out/a.json.', tmp_path)
    write(tmp_path / 'out/a.json', '{"value": 1}')
    monkeypatch.setattr(oc, 'MAX_PARSE_BYTES', 4)
    assert codes(oc.check(rows)) == ['too_large']


def test_require_names_every_violation(tmp_path):
    rows = bound_rows('Write a.json to out/a.json. Write b.yaml to out/b.yaml.', tmp_path)
    with pytest.raises(ValueError) as raised:
        oc.require(rows)
    message = str(raised.value)
    assert message.startswith('declared output contract violated before delivery')
    assert 'output-contract-F1' in message and 'output-contract-F2' in message


def test_the_checker_only_observes(tmp_path):
    rows = bound_rows('Write the answer to out/a.json; do not create any other files.', tmp_path)
    write(tmp_path / 'out/a.json', '{}')
    write(tmp_path / 'out/extra.txt', 'x')
    before = sorted((p.relative_to(tmp_path).as_posix(), p.stat().st_mtime_ns) for p in tmp_path.rglob('*'))
    oc.check(rows)
    after = sorted((p.relative_to(tmp_path).as_posix(), p.stat().st_mtime_ns) for p in tmp_path.rglob('*'))
    assert before == after


# ------------------------------------------------------------------ intake placement
def test_a_run_directory_inside_an_exclusive_location_conflicts(tmp_path):
    rows = bound_rows('Write the answer to answer.yaml; do not create any other files.', tmp_path)
    assert oc.placement_conflicts(rows, tmp_path / 'run-1')
    assert oc.placement_conflicts(rows, tmp_path.parent / 'run-elsewhere') == []
    file_rows = bound_rows('Write the answer to out/answer.yaml.', tmp_path)
    assert oc.placement_conflicts(file_rows, tmp_path / 'out/answer.yaml/run')
    assert oc.placement_conflicts(file_rows, tmp_path / 'out/run') == []


# ------------------------------------------------------------------ read-only command
def test_command_reads_a_request(capsys):
    assert oc.main(['read', '--prompt', 'Write the answer to out/a.json.']) == 0
    assert json.loads(capsys.readouterr().out)['items'][0]['path'] == 'out/a.json'


def test_entries_present_at_intake_are_not_entered(tmp_path, monkeypatch):
    for i in range(30):
        write(tmp_path / f'supplied/part-{i}.dat', 'x')
    rows = bound_rows('Write the answer to answer.yaml; do not create any other files.', tmp_path)
    monkeypatch.setattr(oc, 'MAX_ENTRIES', 10)
    write(tmp_path / 'answer.yaml', 'a: 1\n')
    assert oc.check(rows)['satisfied']
    assert oc.placement_conflicts(rows, tmp_path / 'supplied/run') == []
    write(tmp_path / 'notes/a.md', 'x')
    write(tmp_path / 'notes/b.md', 'x')
    report = oc.check(rows)
    assert codes(report) == ['extra_entry']
    assert report['violations'][0]['message'].endswith('undeclared entries: notes')
