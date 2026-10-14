import copy
import unittest
from ravel.validation.cr_signal_switch import construct, canonical, SWITCH


def source():
    signal = {"name": "sig", "data": [2.0], "modifiers": [
        {"name": "mu", "type": "normfactor", "data": None},
        {"name": "shared", "type": "histosys", "data": {"lo_data": [1.0], "hi_data": [3.0]}},
        {"name": "err", "type": "shapesys", "data": [0.3]}]}
    background = {"name": "bkg", "data": [4.0], "modifiers": [
        {"name": "shared", "type": "normsys", "data": {"lo": 0.8, "hi": 1.3}}]}
    return {"channels": [{"name": name, "samples": [copy.deepcopy(background), copy.deepcopy(signal)]}
                         for name in ("CR", "SR")],
            "observations": [{"name": name, "data": [7]} for name in ("CR", "SR")],
            "measurements": [{"name": "M", "config": {"poi": "mu", "parameters": []}}], "version": "1.0.0"}


class SwitchTests(unittest.TestCase):
    def make(self, w, **kwargs):
        return construct(w, signal_name="sig", control_channels=["CR"], measurement_name="M", **kwargs)

    def test_both_endpoints_preserve_original_responses_and_input(self):
        w = source(); original = canonical(w)
        for level in (0, 1):
            out = self.make(w, level=level)
            self.assertEqual(canonical(w), original)
            self.assertEqual(out["channels"][1], w["channels"][1])
            self.assertEqual(out["channels"][0]["samples"][0], w["channels"][0]["samples"][0])
            self.assertEqual(out["channels"][0]["samples"][1]["modifiers"][:-1],
                             w["channels"][0]["samples"][1]["modifiers"])
            self.assertEqual(out["observations"], w["observations"])
            self.assertEqual(out["measurements"][0]["config"]["parameters"][-1]["inits"], [level])

    def test_the_two_arms_differ_only_by_fixed_initial_value(self):
        a, b = (self.make(source(), level=i) for i in (0, 1))
        a["measurements"][0]["config"]["parameters"][-1]["inits"] = [1.0]
        self.assertEqual(a, b)

    def test_refuses_nonendpoint_and_boolean(self):
        for value in (True, False, 0.0, 0.5, 2, -1):
            with self.assertRaises(ValueError): self.make(source(), level=value)

    def test_refuses_parameter_or_modifier_collision(self):
        for position in ("parameter", "modifier"):
            w = source()
            if position == "parameter": w["measurements"][0]["config"]["parameters"].append({"name": SWITCH})
            else: w["channels"][1]["samples"][0]["modifiers"].append({"name": SWITCH})
            with self.assertRaises(ValueError): self.make(w, level=0)

    def test_missing_or_duplicate_signal_and_channel(self):
        for kind in ("missing_signal", "duplicate_signal", "missing_channel", "duplicate_channel"):
            w = source()
            if kind == "missing_signal": w["channels"][0]["samples"].pop()
            if kind == "duplicate_signal": w["channels"][0]["samples"].append(copy.deepcopy(w["channels"][0]["samples"][-1]))
            if kind == "missing_channel": w["channels"].pop(0)
            if kind == "duplicate_channel": w["channels"].append(copy.deepcopy(w["channels"][0]))
            with self.assertRaises(ValueError): self.make(w, level=0)

    def test_optional_original_parameter_list(self):
        w=source();del w["measurements"][0]["config"]["parameters"]
        self.assertEqual(self.make(w, level=0)["measurements"][0]["config"]["parameters"][-1]["fixed"], True)

    def test_duplicate_cr_or_missing_measurement(self):
        with self.assertRaises(ValueError):
            construct(source(),signal_name="sig",control_channels=["CR","CR"],measurement_name="M",level=0)
        w=source();w["measurements"][0]["name"]="other"
        with self.assertRaises(ValueError): self.make(w,level=0)


if __name__ == "__main__": unittest.main()
