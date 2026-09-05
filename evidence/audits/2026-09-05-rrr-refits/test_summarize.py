"""Retained-data integrity controls; standard library only and no inference."""
import importlib.util
import json
from pathlib import Path
import shutil
import tempfile
import unittest

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("retained_refit_summary", HERE / "summarize.py")
audit = importlib.util.module_from_spec(spec)
spec.loader.exec_module(audit)


class RetainedAuditTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / "audit"
        shutil.copytree(HERE, self.root, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))

    def change_json(self, relative, mutation):
        path = self.root / relative
        value = json.loads(path.read_text())
        mutation(value)
        path.write_text(json.dumps(value) + "\n")

    def test_positive_and_failure_denominator(self):
        summary = audit.build_summary(self.root)
        self.assertEqual((summary["native_resolved_count"], summary["native_failed_count"]), (3, 1))
        failed = summary["native_anchors"][2]
        self.assertEqual(len(failed["attempts"]), 2)
        self.assertIsNone(failed["refit"])
        self.assertFalse(summary["atlas_anchor"]["published_background_identity"]["matches_patchset_declared_background"])
        self.assertTrue(summary["atlas_anchor"]["published_background_identity"]["retained_and_official_numeric_structure_equal"])

    def test_input_mismatch_rejected(self):
        self.change_json("results/m50_dm5-jax-refit.json", lambda value: value.update(patch_sha256="0" * 64))
        with self.assertRaisesRegex(ValueError, "input identity mismatch"):
            audit.build_summary(self.root)

    def test_numeric_equivalence_cannot_accept_bool_or_changed_number(self):
        for value in (True, 1.1):
            with self.assertRaises(ValueError):
                audit.equivalent_numbers({"data": [1]}, {"data": [value]})
        self.assertEqual(len(audit.equivalent_numbers({"data": [1]}, {"data": [1.0]})), 1)

    def test_coherent_scalar_change_rejected_without_retained_root(self):
        def mutation(value):
            result = value["result"]
            result["obs_limit"] *= 1.001
            result["limits"]["observed"]["value"] = result["obs_limit"]
        self.change_json("results/m50_dm5-jax-refit.json", mutation)
        with self.assertRaisesRegex(ValueError, "not evaluated"):
            audit.build_summary(self.root)

    def test_failure_evidence_cannot_disappear(self):
        (self.root / "logs/m150_dm20-tight-refit.log").write_text("incomplete\n")
        with self.assertRaisesRegex(ValueError, "failure evidence absent"):
            audit.build_summary(self.root)

    def test_unreviewed_extra_result_cannot_hide_in_denominator(self):
        (self.root / "results/extra-result.json").write_text("{}\n")
        with self.assertRaisesRegex(ValueError, "result population"):
            audit.build_summary(self.root)

    def test_control_nominal_yields_cannot_change_with_modifiers(self):
        relative = "inputs/atlas-m150_dm20-no-signal-nuisances-patch.json"
        self.change_json(relative, lambda value: value[0]["value"]["data"].__setitem__(0, 999.0))
        # Update the declared hash too: the independent control-content comparison must reject.
        self.change_json("results/atlas-m150_dm20-no-signal-nuisances-refit.json",
                         lambda value: value["inputs"]["patch"].update(sha256=audit.digest(self.root / relative)))
        with self.assertRaisesRegex(ValueError, "changes more than signal modifiers"):
            audit.build_summary(self.root)

    def test_expected_normalization_disagreement_rejected(self):
        self.change_json("inputs/comparison-context.json",
                         lambda value: value["points"][0].update(mu95_exp=0.123))
        with self.assertRaisesRegex(ValueError, "normalization factors differ"):
            audit.build_summary(self.root)

    def test_manifest_and_derived_summary_checked(self):
        audit.seal(self.root)
        self.assertTrue(audit.check(self.root)["pass"])
        self.change_json("summary.json", lambda value: value.update(native_failed_count=0))
        with self.assertRaisesRegex(ValueError, "manifest mismatch"):
            audit.check(self.root)
        # Even deliberate resealing cannot make a false derived summary pass.
        audit.seal(self.root)
        with self.assertRaisesRegex(ValueError, "summary differs"):
            audit.check(self.root)


if __name__ == "__main__":
    unittest.main()
