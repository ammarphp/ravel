"""Portable admission controls: python -B -S test_verify.py. No original workspace required."""
from pathlib import Path
import copy, hashlib, json, math, runpy, shutil, tempfile, unittest
HERE=Path(__file__).resolve().parent
V=runpy.run_path(str(HERE/'verify.py'))
BASE=V['strict']((HERE/'data/evidence.json').read_bytes())

def setpath(data,path,value):
    for key in path[:-1]:data=data[key]
    data[path[-1]]=value

def manifest(folder):
    files={p.relative_to(folder).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in folder.rglob('*') if p.is_file() and p.name!='manifest.json'}
    (folder/'manifest.json').write_bytes(V['encoded']({'schema_version':1,'files':files}))

class Admission(unittest.TestCase):
    def test_positive(self):
        self.assertEqual(V['verify']()['limits'],18)
    def test_pure_semantic_positive(self):V['validate_evidence'](copy.deepcopy(BASE))
    def test_wrong_source_root_fails(self):
        with tempfile.TemporaryDirectory() as td:
            with self.assertRaises(FileNotFoundError):V['verify'](source_root=Path(td))
    def test_duplicate_json_keys(self):
        with self.assertRaises(ValueError):V['strict']('{"native":1,"native":2}')
    def test_json_nan(self):
        with self.assertRaises(ValueError):V['strict']('{"value":NaN}')
    def test_absolute_path(self):
        with self.assertRaises(ValueError):V['safe'](HERE,'/outside')
    def test_parent_path(self):
        with self.assertRaises(ValueError):V['safe'](HERE,'data/../../outside')
    def test_noncanonical_path(self):
        with self.assertRaises(ValueError):V['safe'](HERE,'data//evidence.json')
    def test_symlink_same_bytes(self):
        with tempfile.TemporaryDirectory() as td:
            folder=Path(td)/'bundle';shutil.copytree(HERE,folder)
            p=folder/'data/evidence.json';p.unlink();p.symlink_to(HERE/'data/evidence.json')
            with self.assertRaises(ValueError):V['verify'](folder)
    def test_symlink_directory(self):
        with tempfile.TemporaryDirectory() as td:
            folder=Path(td)/'bundle';shutil.copytree(HERE,folder)
            shutil.rmtree(folder/'data');(folder/'data').symlink_to(HERE/'data',target_is_directory=True)
            with self.assertRaises(ValueError):V['verify'](folder)
    def test_added_file(self):
        with tempfile.TemporaryDirectory() as td:
            folder=Path(td)/'bundle';shutil.copytree(HERE,folder);(folder/'extra.txt').write_text('unexpected')
            with self.assertRaises(ValueError):V['verify'](folder)
    def test_extra_file_even_refreshed_manifest(self):
        with tempfile.TemporaryDirectory() as td:
            folder=Path(td)/'bundle';shutil.copytree(HERE,folder);(folder/'extra.txt').write_text('unexpected');manifest(folder)
            with self.assertRaises(ValueError):V['verify'](folder)
    def test_extra_nested_manifest(self):
        with tempfile.TemporaryDirectory() as td:
            folder=Path(td)/'bundle';shutil.copytree(HERE,folder);(folder/'data/manifest.json').write_text('{}')
            with self.assertRaises(ValueError):V['verify'](folder)
    def test_missing_role_with_refreshed_manifest(self):
        with tempfile.TemporaryDirectory() as td:
            folder=Path(td)/'bundle';shutil.copytree(HERE,folder)
            sm=V['strict']((folder/'source-map.json').read_bytes());sm['original_roles'].pop('anchor150_model');(folder/'source-map.json').write_bytes(V['encoded'](sm));manifest(folder)
            with self.assertRaises(ValueError):V['verify'](folder)
    def test_rebound_role_with_refreshed_manifest(self):
        with tempfile.TemporaryDirectory() as td:
            folder=Path(td)/'bundle';shutil.copytree(HERE,folder)
            sm=V['strict']((folder/'source-map.json').read_bytes());sm['original_roles']['anchor50_report']['path']='made/up.json';(folder/'source-map.json').write_bytes(V['encoded'](sm));manifest(folder)
            with self.assertRaises(ValueError):V['verify'](folder)
    def test_physics_promotion_with_refreshed_manifest(self):
        with tempfile.TemporaryDirectory() as td:
            folder=Path(td)/'bundle';shutil.copytree(HERE,folder);d=copy.deepcopy(BASE);d['scope']['physics_certified']=True;(folder/'data/evidence.json').write_bytes(V['encoded'](d));manifest(folder)
            with self.assertRaises(ValueError):V['verify'](folder)
    def test_figure_drift_with_refreshed_manifest(self):
        with tempfile.TemporaryDirectory() as td:
            folder=Path(td)/'bundle';shutil.copytree(HERE,folder);(folder/'figures/fresh-anchor-diagnostics.png').write_bytes(b'other plot');manifest(folder)
            with self.assertRaises(ValueError):V['verify'](folder)
    def test_csv_drift_with_refreshed_manifest(self):
        with tempfile.TemporaryDirectory() as td:
            folder=Path(td)/'bundle';shutil.copytree(HERE,folder);p=folder/'tables/anchors.csv';p.write_bytes(p.read_bytes().replace(b'20000',b'19000',1));manifest(folder)
            with self.assertRaises(ValueError):V['verify'](folder)
    def test_privacy_even_refreshed_manifest(self):
        with tempfile.TemporaryDirectory() as td:
            folder=Path(td)/'bundle';shutil.copytree(HERE,folder);p=folder/'README.md';p.write_text(p.read_text()+'\n/Users/private-user\n');manifest(folder)
            with self.assertRaises(ValueError):V['verify'](folder)

CASES=[
 ('scope_coverage',['scope','coverage_validated'],True),
 ('scope_raw',['scope','raw_payloads_reread'],True),
 ('scope_plane',['scope','remaining_nominal_points_uncompleted'],0),
 ('scope_bool',['scope','new_events'],False),
 ('mass_swap',['anchors',0,'lsp_GeV'],48),
 ('selected_denominator',['anchors',0,'original_events'],24),
 ('inclusive_N',['anchors',0,'inclusive','original_events'],20000),
 ('wrong_mass_rate',['anchors',0,'inclusive','sigma_lo_pb'],.574784),
 ('double_K',['anchors',0,'native','K'],1.18**2),
 ('zero_integration',['anchors',0,'inclusive','integration_error_pb'],0),
 ('censored_root',['anchors',0,'fit_roots','status','observed'],'above_scan'),
 ('missing_root',['anchors',0,'fit_roots','expected'],[1,2,3,4]),
 ('reversed_expected',['anchors',0,'fit_roots','expected'],[5,4,3,2,1]),
 ('root_mu',['anchors',0,'limits',0,'mu95'],.2),
 ('pb_fb',['anchors',0,'limits',0,'inclusive_sigma95_fb'],.615628),
 ('wrong_residual_sign',['anchors',0,'limits',0,'residual_percent'],-16.835),
 ('invented_band',['anchors',0,'limits',1,'reference_sigma95_pb'],.52692),
 ('invented_reference_error',['anchors',0,'limits',0,'public_uncertainty'],.1),
 ('nan_limit',['anchors',0,'limits',0,'mu95'],float('nan')),
 ('infinite_moment',['anchors',0,'channels',0,'sumw2_pb2'],float('inf')),
 ('boolean_count',['anchors',0,'channels',0,'selected_events'],True),
 ('wrong_channel',['anchors',0,'channels',0,'channel'],'unknown'),
 ('missing_channel',['anchors',0,'channels'],BASE['anchors'][0]['channels'][:-1]),
 ('double_luminosity',['anchors',0,'luminosity_pb_inverse'],278000),
 ('constraint_removed',['anchors',0,'channels',0,'likelihood_mc_constraint'],None),
 ('model_moment',['anchors',0,'model_channel_identity',0,'sumw2'],1),
 ('histogram_replaced_by_fixedN',['anchors',0,'channels',0,'histogram_relative_mc'],.447157),
 ('zero_finite_precision',['anchors',0,'channels',6,'histogram_relative_mc'],0),
 ('zero_floor_pass',['anchors',0,'channels',6,'diagnostic_5percent'],'meets_target'),
 ('pool_n_as_independent',['anchors',2,'channels',0,'streams',0,'N'],60000),
 ('pool_parent_count',['anchors',2,'channels',0,'streams',0,'selected'],40),
 ('pool_alpha_squared',['anchors',2,'channels',0,'sumw2_pb2'],1e-10),
 ('pool_false_zero',['anchors',2,'channels',0,'selected_events'],0),
 ('union_double_count',['anchors',0,'unions',0,'selected_events'],25),
 ('union_sumw2',['anchors',0,'unions',0,'sumw2_pb2'],1e-6),
 ('fresh_checks',['anchors',0,'numerical','fresh_check_evaluations'],17),
 ('cls_exceeds',['anchors',0,'numerical','root_cls_max_error'],.1),
 ('wrong_reference_row',['anchors',0,'reference','source_row_index'],57),
 ('parent_vs_LSP_axis',['anchors',0,'primary_limit_rows',3,'value'],45),
 ('receipt_omitted',['anchors',0,'inherited_receipt_projection','fresh'],BASE['anchors'][0]['inherited_receipt_projection']['fresh'][:-1]),
 ('prefix_full_claim',['anchors',0,'inherited_receipt_projection','inclusive'],BASE['anchors'][0]['inherited_receipt_projection']['fresh']),
 ('fraction_missing',['fractions'],BASE['fractions'][:-1]),
 ('fraction_own_sigma',['fractions',0,'inclusive_LO_pb'],.1350625),
 ('fraction_luminosity',['fractions',0,'inclusive_reco_fraction'],.1),
 ('fraction_unit',['anchors',0,'fraction_reference','regions','SR-S-high','acceptance','display_to_fraction'],1),
 ('fraction_primary',['anchors',0,'primary_fraction_rows','c',0,'value'],.9),
 ('fraction_reference_LSP',['anchors',0,'primary_fraction_rows','c',2,'value'],45),
 ('fraction_covariance',['fractions',4,'fixed_N_conditional_mc_standard_error'],.0002),
 ('fraction_hist_as_fixed',['fractions',4,'histogram_mc_standard_error'],BASE['fractions'][4]['fixed_N_conditional_mc_standard_error']),
 ('fraction_error_missingness',['fractions',0,'public_uncertainty'],0),
 ('fraction_error_doublecount',['fractions',0,'inclusive_integration_only_standard_error'],.0001),
 ('failure_relabel',['preserved_failures','fraction_v1_completion','status'],'accepted'),
 ('review_roles',['independent_review_roles'],['anchor50_review']),
]
for name,path,value in CASES:
    def check(self,path=path,value=value):
        d=copy.deepcopy(BASE);setpath(d,path,value)
        with self.assertRaises(ValueError):V['validate_evidence'](d)
    setattr(Admission,'test_semantic_'+name,check)

if __name__=='__main__':unittest.main(verbosity=2)
