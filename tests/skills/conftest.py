"""Run the code blocks a handbook's review record lists as executable."""
import pytest

from ravel.validation import tool_handbooks as hb


def listed(skill):
    return list(hb.review_record(hb.handbook_root() / skill)["executable_blocks"])


def load(skill, block_id):
    """Execute one listed block in a fresh namespace and return the namespace."""
    skill_dir = hb.handbook_root() / skill
    if block_id not in listed(skill):
        raise AssertionError(f"{skill}: block {block_id} is not listed as executable")
    code = hb.blocks(skill_dir)[block_id]["code"]
    namespace = {"__name__": f"handbook_{skill.replace('-', '_')}_{block_id.replace('-', '_')}"}
    exec(compile(code, f"<{skill}:{block_id}>", "exec"), namespace)
    return namespace


@pytest.fixture
def handbook():
    class Handbook:
        listed = staticmethod(listed)
        load = staticmethod(load)
    return Handbook
