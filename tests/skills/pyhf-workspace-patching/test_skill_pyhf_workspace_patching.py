"""pyhf-workspace-patching block on a tiny synthetic workspace."""
import pytest

from ravel.physics.published_model import canonical_background_digest

SKILL = "pyhf-workspace-patching"
BACKGROUND = {
    "channels": [{"name": "SR", "samples": [{"name": "bkg", "data": [10.0],
                  "modifiers": [{"name": "mu_dummy", "type": "normfactor", "data": None}]}]}],
    "observations": [{"name": "SR", "data": [11.0]}],
    "measurements": [{"name": "meas", "config": {"poi": "mu_sig", "parameters": [
        {"name": "mu_dummy", "fixed": True, "inits": [1.0]}]}}],
    "version": "1.0.0",
}
PATCH = [{"op": "add", "path": "/channels/0/samples/-", "value": {
    "name": "signal", "data": [2.0], "modifiers": [{"name": "mu_sig", "type": "normfactor", "data": None}]}}]


def test_record_lists_exactly_the_tested_blocks(handbook):
    assert handbook.listed(SKILL) == ["patch-with-digest"]


def test_patch_applies_only_to_its_background(handbook):
    patched = handbook.load(SKILL, "patch-with-digest")["patched_model"]
    model, data = patched(BACKGROUND, PATCH, canonical_background_digest(BACKGROUND))
    assert model.config.poi_name == "mu_sig" and list(model.config.samples) == ["bkg", "signal"]
    assert list(data)[:1] == [11.0]
    with pytest.raises(ValueError, match="patch was made for background"):
        patched(BACKGROUND, PATCH, "0" * 64)
