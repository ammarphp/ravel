"""Required supplied diagnostic plans and typed input refusals."""
from pathlib import Path
import json
import math
import os
from ravel.workflow.state_io import atomic_json


class PlanError(ValueError):
    def __init__(self, code, field, message):
        self.code, self.field = code, field
        super().__init__(f'{code}: {field}: {message}')


def required(record, field):
    if not isinstance(record, dict) or field not in record:
        raise PlanError('missing_input', field, 'supply this field in the selected plan')
    return record[field]


def fields(record, keys, label):
    for key in keys:required(record,key)
    require(set(record)==set(keys),label,'unknown input fields')


def require(value, field, message):
    if not value:
        raise PlanError('invalid_input', field, message)


def positive(value, field, *, integer=False, zero=False):
    require(type(value) is int if integer else type(value) in (int, float), field, 'exact number required')
    require(math.isfinite(value) and (value >= 0 if zero else value > 0), field, 'finite bounded number required')
    return value


def relative(value):
    require(type(value) is str and value, 'output.file', 'relative filename required')
    p = Path(value)
    require(bool(p.parts) and not p.is_absolute() and '..' not in p.parts and p.as_posix() == value, 'output.file', 'canonical owned relative filename required')
    return p


def selected(document, fields=()):
    plan = required(document, 'plan')
    require(isinstance(plan, dict), 'plan', 'object required')
    identity = required(plan, 'study_identity')
    require(type(identity) is str and identity, 'study_identity', 'supplied identity required')
    grid = required(plan, 'parameter_grid')
    require(isinstance(grid, list) and grid and all(isinstance(row, dict) and row for row in grid), 'parameter_grid', 'finite point list required')
    for row in grid:
        for key, value in row.items():
            require(type(key) is str and key, 'parameter_grid', 'parameter names required')
            require(type(value) in (int, float) and math.isfinite(value), 'parameter_grid', 'finite parameter values required')
    population = required(plan, 'dataset_population')
    require(isinstance(population, list) and population and all(type(x) is str and x for x in population) and len(set(population)) == len(population), 'dataset_population', 'unique supplied dataset identities required')
    output = required(plan, 'output')
    require(isinstance(output, dict) and set(output) == {'format', 'file'}, 'output', 'format and file required')
    require(output['format'] in ('json', 'jsonl'), 'output.format', 'supported formats are json and jsonl')
    relative(output['file'])
    for field in fields:
        required(plan, field)
    return plan


def limits(record, fields):
    require(isinstance(record, dict), 'limits', 'object required')
    for field in fields:
        positive(required(record, field), 'limits.'+field, integer=True)
    return record


def tolerances(record):
    keys = ('fit_requested', 'objective_agreement', 'stationarity', 'independent_density', 'gradient_atol', 'gradient_rtol', 'step_scale')
    fields(record,keys,'tolerances')
    for field in keys:
        positive(record[field], 'tolerances.'+field)
    return record


def metadata(plan):
    return {key: plan[key] for key in ('study_identity', 'parameter_grid', 'dataset_population')}


def publish(out, plan, report):
    path = Path(out)/relative(plan['output']['file'])
    require(not any(p.is_symlink() for p in (path, *path.parents)), 'output.file', 'nonsymlink output required')
    report.update(metadata(plan))
    report['output_format'] = plan['output']['format']
    path.parent.mkdir(parents=True, exist_ok=True)
    if plan['output']['format'] == 'json':
        atomic_json(path, report)
    else:
        temporary = path.with_name(path.name+'.partial')
        with temporary.open('w') as stream:
            stream.write(json.dumps(report, allow_nan=False, separators=(',', ':'))+'\n')
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    return path
