"""Ordinary bounded prospective separation; no generator, fitter or new runner."""
from copy import deepcopy
from pathlib import Path
from ravel.workflow import quantitative_predictive_checks as checks


def validate(task):
    checks._keys(task,('schema_version','binding'))
    if type(task['schema_version']) is not int or task['schema_version']!=1:raise ValueError('quantitative-predictive task/v1 required')
    checks.validate_binding(task['binding']);return deepcopy(task)


def inputs(task,base_dir):
    validate(task);return checks.inputs(task['binding'],base_dir)


def execution_seconds(task,base_dir):
    validate(task);return checks.guidance(task['binding'],base_dir)['requirements']['effective']['wall_seconds']


def context(task,base_dir):
    validate(task);return checks.guidance(task['binding'],base_dir)


def run(task,base_dir,out):
    from ravel.workflow.state_io import atomic_json
    from ravel.workflow.research_cycle import _pin
    from ravel.workflow.research_presentation import document
    validate(task);out=Path(out);out.mkdir(parents=True,exist_ok=True)
    path=out/'result.json'
    if path.exists():raise ValueError('fresh ordinary quantitative result required')
    value=checks.separation(task['binding'],base_dir=base_dir)
    value['status']='passed' if value['delivery_status']=='complete' else 'failed'
    intended=checks._encoded(value);atomic_json(path,deepcopy(value));pin=_pin(path)
    if checks._encoded(value)!=intended or checks._encoded(document(pin,out,64*1024**2))!=intended:
        raise ValueError('ordinary quantitative output differs from intended bytes')
    report=out/'quantitative-report.md';report.write_text(checks.markdown(value))
    value['status']='passed' if value['delivery_status']=='complete' else 'failed'
    for p in value['input_pins']:
        from ravel.workflow.research_cycle import _check_pin
        _check_pin(p,base_dir)
    return value


class Guard:
    """Commit the adapter's original return before common worker callbacks."""
    def __init__(self,result,task,base_dir,out):
        self.binding=deepcopy(task['binding']);self.base=base_dir;self.out=Path(out)
        self.intended=checks._encoded(result);self.report=checks.markdown(result).encode()
        self.finish(result)

    def finish(self,result):
        from ravel.workflow.research_cycle import _pin
        from ravel.workflow.research_presentation import document
        if checks._encoded(result)!=self.intended:
            raise ValueError('returned quantitative result changed after its original commitment')
        checks.verify_value(self.binding,result,base_dir=self.base,observation_pin=None)
        if checks._encoded(document(_pin(self.out/'result.json'),self.out,64*1024**2))!=self.intended:
            raise ValueError('common quantitative publication differs from original intended result')
        if (self.out/'quantitative-report.md').read_bytes()!=self.report:
            raise ValueError('common quantitative report differs from original intended bytes')
