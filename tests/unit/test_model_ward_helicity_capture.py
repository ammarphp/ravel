"""Source/mock loop provenance controls; no MG5/UFO/native evaluation."""
import ast
from copy import deepcopy
import itertools
from pathlib import Path
from types import SimpleNamespace
import pytest
from ravel.physics import model_ward as ward

LABELS=list(map(list,itertools.product((-1,1),repeat=4)))

class Matrix:
    def __init__(self):self.helEvals=[[list(label),1.0] for label in LABELS]

def test_executed_labels_preserve_order_and_are_copies():
    matrix=Matrix();matrix.helEvals.reverse();declared=list(reversed(deepcopy(LABELS)))
    labels=ward._executed_helicities(matrix,Matrix,declared,[[0j,0j] for _ in LABELS])
    assert labels==declared
    matrix.helEvals[0][0][0]=8
    assert labels==declared

@pytest.mark.parametrize('fault',['missing_instance','foreign_instance','missing_class','foreign_class',
    'missing_rows','tuple_rows','missing_row','ragged_row','tuple_label','three_leg_label',
    'bool_label','invalid_label','different_order','jamp_census'])
def test_observed_loop_refuses_false_row_identity(fault):
    matrix=Matrix();expected=Matrix;declared=deepcopy(LABELS);jamp=[[0j,0j] for _ in LABELS]
    if fault=='missing_instance':matrix=None
    elif fault=='foreign_instance':matrix=SimpleNamespace(helEvals=matrix.helEvals)
    elif fault=='missing_class':expected=None
    elif fault=='foreign_class':expected=type('OtherMatrix',(),{})
    elif fault=='missing_rows':del matrix.helEvals
    elif fault=='tuple_rows':matrix.helEvals=tuple(matrix.helEvals)
    elif fault=='missing_row':matrix.helEvals.pop()
    elif fault=='ragged_row':matrix.helEvals[0]=[matrix.helEvals[0][0]]
    elif fault=='tuple_label':matrix.helEvals[0][0]=tuple(matrix.helEvals[0][0])
    elif fault=='three_leg_label':matrix.helEvals[0][0].pop()
    elif fault=='bool_label':matrix.helEvals[0][0][0]=True
    elif fault=='invalid_label':matrix.helEvals[0][0][0]=0
    elif fault=='different_order':matrix.helEvals.reverse()
    elif fault=='jamp_census':jamp.pop()
    with pytest.raises(ValueError):ward._executed_helicities(matrix,expected,declared,jamp)

@pytest.mark.parametrize('gauge',[True,False])
def test_actual_producer_class_observes_loop_not_post_writer_object(gauge):
    # Extract only the real nested wrapper AST. Its parent is a harmless synthetic
    # exporter/evaluator stand-in; no native_worker or model code is invoked.
    tree=ast.parse(Path(ward.__file__).read_text())
    classes=[node for node in ast.walk(tree) if isinstance(node,ast.ClassDef) and node.name=='AnchoredEvaluator']
    assert len(classes)==1
    process=SimpleNamespace(MatrixElementEvaluator=None)
    calls=[];fixed=[[5.,0.,0.,5.],[5.,0.,0.,-5.],[5.,1.,0.,0.],[5.,-1.,0.,0.]]
    class Process(dict):
        def shell_string(self):return 'synthetic_only'
    proc=Process(legs=[{'id':pdg,'number':i+1,'state':i>=2} for i,pdg in enumerate([21,21,6,-6])],
        orders={'QCD':2,'QED':0},forbidden_particles=[],perturbation_couplings=[])
    class Element(dict):
        def __init__(self):super().__init__(processes=[proc],color_basis={(("T",(1,2,3,4)),):None});self.labels=deepcopy(LABELS)
        def get_helicity_matrix(self):return deepcopy(self.labels)
    class Generated:
        def __init__(self):self.helEvals=[[deepcopy(label),1.] for label in LABELS]
    class Parent:
        def __init__(self):self.full_model=SimpleNamespace(get_mass=lambda pdg:0.)
        def evaluate_matrix_element(self,element,**kwargs):
            assert kwargs['p']==fixed
            process.data=Generated();setattr(process,'Matrix_synthetic_only',Generated)
            if kwargs['gauge_check']:
                # Mirrors the pinned writer's removal after exporter helicity
                # capture. These triples are metadata, not evaluated amplitudes.
                element.labels=list(map(list,itertools.product((-1,1),repeat=3)))
            calls.append(kwargs['gauge_check'])
            return {'m2':1.,'jamp':[[0j] for _ in LABELS]}
    process.MatrixElementEvaluator=Parent
    evaluations=[]
    namespace={'process_checks':process,'fixed':fixed,'evaluations':evaluations,
        '_executed_helicities':ward._executed_helicities,
        'bridge':SimpleNamespace(_snapshot=lambda model:{},_complex=lambda value:{'real':value.real,'imag':value.imag})}
    module=ast.fix_missing_locations(ast.Module(body=classes,type_ignores=[]))
    exec(compile(module,'exact-wrapper-AST-synthetic-parent','exec'),namespace)
    element=Element();result=namespace['AnchoredEvaluator']().evaluate_matrix_element(element,gauge_check=gauge,output='jamp')
    assert calls==[gauge] and len(result['jamp'])==16
    assert len(evaluations)==1
    observed=evaluations[0]
    assert observed['helicities']==LABELS
    provenance=observed['helicity_provenance']
    assert provenance['source']=='actual_generated_Matrix.smatrix.helEvals'
    assert provenance['pre_export_matrix']==LABELS
    assert len(provenance['post_writer_matrix'])==(8 if gauge else 16)
    assert {len(row) for row in provenance['post_writer_matrix']}==({3} if gauge else {4})
