"""Explicit complete-marked subtype of the ordinary joint qualification route.

This module only adapts the task discriminator. The numerical implementation,
source capture, budgets, progressive returns and refusal criteria live in the
separately reviewed marked_joint_qualification module.
"""
from ravel.physics import marked_joint_qualification as implementation


def _task(task):
    if (type(task) is not dict or set(task) != {'input', 'response_family'} or
            task['response_family'] != 'complete_marked_categories'):
        raise ValueError('explicit complete_marked_categories qualification task required')
    child = {'input': task['input']}
    implementation.validate(child)
    return child


def validate(task):
    _task(task)


def inputs(task, base_dir):
    return implementation.inputs(_task(task), base_dir)


def resource_bounds(task, base_dir):
    return implementation.resource_bounds(_task(task), base_dir)


def execution_seconds(task, base_dir):
    return implementation.execution_seconds(_task(task), base_dir)


def run(task, base_dir, output_dir):
    return implementation.run(_task(task), base_dir, output_dir)
