"""Compatibility access to the explicitly selected supplied routine."""
from ravel.physics.analysis_packages import selected_attribute

def __getattr__(name):
    return selected_attribute(name)
