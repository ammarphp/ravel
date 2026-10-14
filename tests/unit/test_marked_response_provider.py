"""Pure fabricated mark algebra and metadata; no density/compiler/fit calls."""
from copy import deepcopy
from fractions import Fraction as F
from itertools import product
from pathlib import Path
import ast
import hashlib
import json
import tempfile
import unittest

from ravel.physics import marked_response_provider as p
from ravel.physics import marked_response as m
from ravel.physics import mc_auxiliary as mc
from ravel.physics import marked_joint_qualification as qualification


def fixture(categories=3):
    ids = ["A", "B", "unselected"] if categories == 3 else ["c"+str(i) for i in range(categories)]
    d = {"schema_version": 1, "category_ids": ids, "destination_ids": ["SR", "CR", "outside"],
         "fitted_destinations": ["SR", "CR"], "axes": [{"name": "a", "knots": [0, 1]}, {"name": "b", "knots": [0, 1]}],
         "reference_point": {"a": 0, "b": 0}, "category_weights": [1]*categories,
         "denominator_marks": [1]*categories, "scale": 100, "total_groups": 10, "anchors": [],
         "provenance": {"category_partition": "complete artificial categorical experiment",
                        "joint_anchor_identity": "identical category identities at every joint corner",
                        "interpolation": "new_piecewise_multilinear_fixed_mark_law", "calibration": "not physical calibration"}}
    for a, b in product([0, 1], repeat=2):
        d["anchors"].append({"point": [a, b], "allocation": [[a*b, 1-a*b, 0]]+[[0, 1, 0]]*(categories-2)+[[0, 0, 1]]})
    config = {"axis_to_source": {"a": "alpha", "b": "beta"}, "source_data_id": "response", "group_ledger_source_id": "group-marks", "sampling_independence": "supplied_source_and_new_MC_auxiliaries_independent"}
    source = {"active_parameter_names": ["alpha", "beta", "background_rate"],
              "active_parameter_domains": {"alpha": {"bounds": [0, 1], "initial": .3, "fixed": False}, "beta": {"bounds": [0, 1], "initial": .4, "fixed": False}, "background_rate": {"bounds": [.1, 4], "initial": 1, "fixed": False}},
              "retained_auxiliaries": [{"name": n, "coordinate": n, "pdf": "normal", "sigma": 1, "factor": 1, "observed": 0} for n in ("alpha", "beta", "background_rate")]}
    raw = p._bytes(d)
    design = {"kind": "fixed_n_categories", "sampling_law": "iid_fixed_mark_categories", "fixed_marks": True, "support_complete": True,
              "ledger_source": "ledger", "independence": "iid_groups_within_one_fixed_N_stream", "total_groups": 10, "kappa": 100,
              "normalization_source": "response", "normalization_meaning": "constructed complete-group conditional count scale"}
    doc = {"schema_version": 2, "model_id": "artificial-complete-population", "sources": [
        {"id": n, "path": n+".json", "sha256": hashlib.sha256(raw if n == "response" else b"{}").hexdigest(), "reference": "fabricated source fixture"} for n in ("response", "ledger")],
        "bins": [{"id": "SR", "role": "signal", "source": "response"}, {"id": "CR", "role": "control", "source": "response"}],
        "mc_design": design, "classes": [], "assumptions": ["complete artificial IID categories", "source and MC experiments independent"]}
    for i, name in enumerate(ids):
        observed = [2, 3, 5][i] if categories == 3 else int(i == categories-1)*10
        doc["classes"].append({"id": name, "contribution": [0, int(i < categories-1)], "denominator_mark": 1, "exposure": None,
                               "observed": observed, "observed_group_ids": [name+"-"+str(j) for j in range(observed)], "initial": 1/categories, "source": "response"})
    return d, config, source, doc


def group_ledger(document, mc_document):
    records=p.category_mark_records(document)
    signatures={r['id']:hashlib.sha256(p._bytes(r)).hexdigest() for r in records}
    return {'schema_version':1,'sampling_unit':'same_complete_IID_generator_groups_at_all_anchors','category_marks':records,
            'groups':[{'id':g,'class_id':c['id'],'category_mark_sha256':signatures[c['id']]} for c in mc_document['classes'] for g in c['observed_group_ids']]}


P = {"A": .2, "B": .3, "unselected": .5}


class ProviderTests(unittest.TestCase):
    def bind(self, values=None, order=None):
        d, c, s, aux = values or fixture()
        return p.bind_mark_law(d, c, s, aux, {"alpha", "beta"}, order or ["SR", "CR"])

    def test_complete_zero_nominal_law_binds_all_factors_once(self):
        d, c, s, aux = fixture(); mc.prepare(aux)
        result = self.bind((d, c, s, aux))
        self.assertEqual(result["source_auxiliary_order"], s["retained_auxiliaries"])
        self.assertEqual(result["MC_auxiliary_factors"], 1)
        self.assertEqual(result["added_auxiliary_factors"], 0)
        self.assertEqual(result["normalization"]["N"], 10)

    def test_absolute_joint_corner_jet_and_background_chain(self):
        d, c, s, aux = fixture(); self.bind((d, c, s, aux))
        point = {"alpha": .5, "beta": .25, "background_rate": 1}
        jet = p.mark_jet(d, point, P, s["active_parameter_names"], c["axis_to_source"], ["SR", "CR"])
        self.assertEqual(jet["signal"], [2.5, 47.5])
        self.assertEqual(jet["source_jacobian"], [[5, 10, 0], [-5, -10, 0]])
        means, jac = p.assemble_main_jet([4, 6], [[0, 0, 4], [0, 0, 6]], jet, 2)
        self.assertEqual(means, [9, 101])
        self.assertEqual(jac[0][:4], [2.5, 10, 20, 4])
        # Exact independent formula SR = 4*r + mu*100*pA*a*b.
        self.assertEqual(jac[0][4]-jac[0][6], 25)

    def test_permutation_and_complete_columns(self):
        d, c, s, _ = fixture(); self.bind(order=["CR", "SR"])
        jet = p.mark_jet(d, {"alpha": .5, "beta": .25}, P, s["active_parameter_names"], c["axis_to_source"], ["CR", "SR"])
        self.assertEqual(jet["signal"], [47.5, 2.5])
        self.assertEqual(jet["source_jacobian"][0], [-5, -10, 0])
        with self.assertRaisesRegex(ValueError, "complete and injective"): self.bind(order=["SR", "SR"])

    def test_zero_nominal_source_and_latent_derivatives_are_not_lost(self):
        d, c, s, _ = fixture()
        jet = p.mark_jet(d, {"alpha": 0, "beta": 1}, P, s["active_parameter_names"], c["axis_to_source"], ["SR", "CR"])
        self.assertEqual(jet["signal"][0], 0)
        self.assertEqual(jet["source_jacobian"][0], [20, 0, 0])
        self.assertEqual(p.assemble_main_jet([1, 2], [[0]*3, [0]*3], jet, 0)[1][0][:4], [0, 0, 0, 0])

    def test_ratio_derivatives_against_independent_rational_algebra(self):
        d, c, s, aux = fixture(); d["denominator_marks"] = [2, 1, .5]
        for row, den in zip(aux["classes"], d["denominator_marks"]): row["denominator_mark"] = den
        self.bind((d, c, s, aux)); theta = {"alpha": .5, "beta": .25}
        jet = p.mark_jet(d, theta, P, s["active_parameter_names"], c["axis_to_source"], ["SR", "CR"])
        probs = [F(1,5), F(3,10), F(1,2)]; den = sum(a*b for a,b in zip(probs,[F(2),F(1),F(1,2)]))
        numer = F(1,8)*probs[0]
        for k, mark in enumerate([F(1,8),F(0),F(0)]):
            expected = 100*(mark/den-numer*[F(2),F(1),F(1,2)][k]/den**2)
            self.assertAlmostEqual(jet["latent_jacobian"][0][k], float(expected), places=12)

    def test_same_population_shared_covariance_retained(self):
        d, _, _, _ = fixture()
        result = m.joint_covariance(d, P, [{"a": 0, "b": 0}, {"a": 1, "b": 1}])
        # CR nominal=A+B; SR displaced=A; covariance 100^2/N*(pA-(pA+pB)*pA).
        self.assertAlmostEqual(result["covariance"][1][3], 100)
        self.assertEqual(result["scope"], "exact_fixed_N_linear_estimator_covariance")
        self.assertFalse(result["likelihood_inferred"])

    def test_nine_categories_are_not_merged_or_dropped(self):
        d, c, s, aux = fixture(9); mc.prepare(aux)
        bound = self.bind((d, c, s, aux)); self.assertEqual(len(bound["MC_order"]), 9)
        aux["schema_version"] = 1
        with self.assertRaises(ValueError): mc.prepare(aux)

    def test_single_source_region_needs_no_fabricated_control(self):
        _, _, _, aux = fixture()
        aux["bins"] = aux["bins"][:1]
        for row in aux["classes"]: row["contribution"] = row["contribution"][:1]
        self.assertEqual(len(mc.prepare(aux)["bins"]), 1)

    def test_no_arbitrary_count_or_scale_ceiling_but_complete_ids_required(self):
        _, _, _, aux = fixture(); aux["mc_design"]["kappa"] = 2e6
        mc.prepare(aux)
        aux["mc_design"]["total_groups"] = 100001
        with self.assertRaisesRegex(ValueError, "fixed N"): mc.prepare(aux)

    def test_nominal_population_equality_cannot_hide_changed_marks(self):
        values = fixture(); d, _, _, aux = values
        # Equal sum at the uniform initial probabilities; per-category wrong.
        aux["classes"][0]["contribution"][1] = .5
        aux["classes"][1]["contribution"][1] = 1.5
        with self.assertRaisesRegex(ValueError, "per-category reference"): self.bind(values)

    def test_nuisance_and_auxiliary_census_refusals(self):
        values = fixture(); values[1]["axis_to_source"]["b"] = "alpha"
        with self.assertRaisesRegex(ValueError, "injective"): self.bind(values)
        values = fixture(); values[2]["retained_auxiliaries"].append(deepcopy(values[2]["retained_auxiliaries"][0]))
        with self.assertRaisesRegex(ValueError, "duplicate"): self.bind(values)
        values = fixture()
        with self.assertRaisesRegex(ValueError, "dependency"): p.bind_mark_law(*values, {"alpha"}, ["SR", "CR"])

    def test_missing_support_normalization_and_count_refuse(self):
        for key in ("denominator_marks", "total_groups", "scale", "category_ids"):
            values = fixture(); d = values[0]
            if key == "denominator_marks": d[key][0] = 2
            elif key == "category_ids": d[key] = list(reversed(d[key]))
            else: d[key] += 1
            with self.assertRaises(ValueError): self.bind(values)

    def test_response_hull_cannot_shrink_source_domain(self):
        values = fixture(); values[2]["active_parameter_domains"]["alpha"]["bounds"] = [-1, 1]
        with self.assertRaisesRegex(ValueError, "unchanged source domain"): self.bind(values)
        values[2]["active_parameter_domains"]["alpha"].update(fixed=True, initial=.5)
        self.bind(values)  # actually fixed point, not an invented free-domain cut

    def test_kink_refuses_even_when_one_population_cancels_it(self):
        d, c, s, aux = fixture(); d["axes"][0]["knots"] = [0, .5, 1]
        for b in (0, 1): d["anchors"].append({"point": [.5, b], "allocation": [[0,1,0],[0,1,0],[0,0,1]]})
        with self.assertRaisesRegex(ValueError, "nonsmooth category mark"): self.bind((d,c,s,aux))

    def test_redundant_collinear_knot_and_corner_slopes(self):
        d, c, s, aux = fixture(); d["axes"][0]["knots"] = [0,.5,1]
        for b in (0,1): d["anchors"].append({"point":[.5,b], "allocation":[[.5*b,1-.5*b,0],[0,1,0],[0,0,1]]})
        self.bind((d,c,s,aux))
        jet = p.mark_jet(d, {"alpha":.5,"beta":1}, P, s["active_parameter_names"], c["axis_to_source"], ["SR","CR"])
        self.assertEqual(jet["source_jacobian"][0], [20,10,0])

    def test_negative_current_mean_kept_for_domain_then_density_refuses(self):
        d,c,s,aux=fixture(); d["category_weights"][1]=-1; aux["classes"][1]["contribution"][1]=-1
        self.bind((d,c,s,aux))
        jet=p.mark_jet(d,{"alpha":1,"beta":1},{"A":.4,"B":.1,"unselected":.5},s["active_parameter_names"],c["axis_to_source"],["SR","CR"])
        self.assertEqual(jet["signal"],[40,-10])
        with self.assertRaisesRegex(ValueError,"negative aggregate"):p.assemble_main_jet([100,100],[[0]*3]*2,jet,1)

    def test_full_source_and_latent_constraint_tangent(self):
        d,c,s,_=fixture(); x={"alpha":.5,"beta":.25}
        jet=p.mark_jet(d,x,P,s["active_parameter_names"],c["axis_to_source"],["SR","CR"])
        # Independent dSR for da=.1, db=-.2, dpA=.02, dpB=.01, dpU=-.03.
        expected=100*(F(1,5)*(F(1,4)*F(1,10)+F(1,2)*F(-1,5))+F(1,8)*F(1,50))
        got=sum(a*b for a,b in zip(jet['source_jacobian'][0],[.1,-.2,0]))+sum(a*b for a,b in zip(jet['latent_jacobian'][0],[.02,.01,-.03]))
        self.assertAlmostEqual(got,float(expected),places=14)

    def test_provider_source_capture_and_ending_refusal(self):
        d,c,s,aux=fixture()
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp).resolve()/'marks.json';raw=p._bytes(d);path.write_bytes(raw)
            class MC:
                _captured={str(path):raw, 'group-marks':p._bytes(group_ledger(d,aux))}
                def assert_custody(self):return None
                def document(self):return deepcopy(aux)
            group_raw=p._bytes(group_ledger(d,aux))
            aux['sources'].append({'id':'group-marks','path':'group-marks.json','sha256':hashlib.sha256(group_raw).hexdigest(),'reference':'complete artificial signatures'})
            provider=p.MarkedResponseProvider(path=path,sha256=hashlib.sha256(raw).hexdigest(),configuration=c)
            provider.bind(s,MC(),{'alpha','beta'},['SR','CR'])
            self.assertEqual(provider.supported_categories(),[0,1])
            path.write_bytes(raw+b' ')
            with self.assertRaisesRegex(ValueError,'source changed'):provider.jet({'alpha':.2,'beta':.3},P)



    def test_group_variation_signature_cannot_be_nominal_only(self):
        d,_,_,doc=fixture();ledger=group_ledger(d,doc)
        self.assertEqual(p.verify_group_marks(d,doc,ledger)['observed_group_count'],10)
        d['anchors'][-1]['allocation'][0]=[.5,.5,0]
        with self.assertRaisesRegex(ValueError,'joint-anchor marks'):p.verify_group_marks(d,doc,ledger)

    def test_complete_group_identity_and_signature_refusals(self):
        d,_,_,doc=fixture()
        for mutation in ('missing','duplicate','unknown','different_signature'):
            ledger=group_ledger(d,doc)
            if mutation=='missing':ledger['groups'].pop()
            elif mutation=='duplicate':ledger['groups'][1]=deepcopy(ledger['groups'][0])
            elif mutation=='unknown':ledger['groups'][0]['class_id']='not-in-population'
            else:ledger['groups'][0]['category_mark_sha256']='0'*64
            with self.assertRaises(ValueError):p.verify_group_marks(d,doc,ledger)

    def test_exact_tangent_transport_uses_last_probability_column(self):
        result={'coordinate_order':['mu','source:a','MC:x','MC:y','MC:z'],
                'gradient':[7,11,13,17,19], 'distribution_mean_jacobian':[[2,3,5,7,11],[13,17,19,23,29]]}
        gradient,jac=qualification._tangent_columns(result,['mu','source:a','MC:x','MC:y'],'z')
        self.assertEqual(gradient,[7,11,-6,-2]);self.assertEqual(jac,[[2,3,-6,-4],[13,17,-10,-6]])

    def test_shift_keeps_complete_simplex_and_other_coordinates(self):
        point={'mu':1,'source':{'a':.5},'latent':{'x':.2,'y':.3,'z':.5}}
        moved=qualification._shift(point,'MC:y',.125,'z')
        self.assertEqual(moved['latent'],{'x':.2,'y':.425,'z':.375})
        self.assertEqual(point['latent']['y'],.3)
        self.assertAlmostEqual(sum(moved['latent'].values()),1)


if __name__ == '__main__': unittest.main()
