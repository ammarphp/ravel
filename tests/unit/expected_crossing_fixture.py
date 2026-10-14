"""Artificial Poisson/Gaussian facade, never a ROOT/native fit."""
from types import SimpleNamespace as NS
from fractions import Fraction as F
from pathlib import Path
import math
from copy import deepcopy
from statistics import NormalDist
from test_regional_expected import fixture, fake, fit
from ravel.physics import regional_expected as e, statistical_construction as r, native_likelihood as n

def known_document(path,b=20.25,s=3.5,maximum=20.,refine=False,cap=100,auxiliary=False):
 d=fixture(path)
 d['parameters']=d['parameters'][:1];d['parameters'][0]['bounds']=['0',str(maximum)]
 d['bins']=d['bins'][:1]
 d['terms'][0]['powers']={};d['terms'][0]['coefficients']=[str(b)]
 d['terms'][1]['coefficients']=[str(s)]
 for term in d['terms']:term['log_response']=[['0'] if auxiliary else []]
 if not auxiliary:d['auxiliary'].update(names=[],observed=[],factor=[],eta_bounds=[])
 d['expected_data']['point']={'mu':'0',**({'ravel_aux_0':'1/2'} if auxiliary else {})}
 if refine:d['expected_data']['crossing']={'mode':'verify_or_refine','max_profile_evaluations':cap}
 r.validate(d);return d

def roots(b,s):
 normal=NormalDist();result=[]
 for p in e.QUANTILES:
  target=(normal.inv_cdf(p)+normal.inv_cdf(1-.05*p))**2
  lo=0.;hi=10000./s
  for _ in range(100):
   mid=(lo+hi)/2;q=2*(mid*s-b*math.log1p(mid*s/b))
   if q<target:lo=mid
   else:hi=mid
  result.append({'limit':(lo+hi)/2,'quantileExpected':p})
 return result

def setup(path,d,rows=None):
 root,w,mc,data,calls=fake(path,d);response=r.response(d)
 # This explicit fixture avoids an actual native scientific runtime. Its only
 # profile nuisance, when present, is an independent full Gaussian coordinate.
 class Mini(root.RooMinimizer):
  def minimize(self,*args):
   if d['auxiliary']['names']:w.var('ravel_aux_0').setVal(w.var('ravel_aux_0_In').getVal())
   return 0
  def save(self):
   from test_regional_expected import Collection
   floats=Collection([w.var('ravel_aux_0')]);const=Collection([w.var('mu')])
   return NS(status=lambda:0,covQual=lambda:3,edm=lambda:0.,minNll=nll.getVal,numInvalidNLL=lambda:0,numStatusHistory=lambda:2,statusLabelHistory=lambda i:['Migrad','Hesse'][i],statusCodeHistory=lambda i:0,floatParsFinal=lambda:floats,constPars=lambda:const,covarianceMatrix=lambda:[[1.]])
 root.RooMinimizer=Mini
 def get_nll():
  means=r.mean_jet(d,{name:str(F(w.var(name).getVal())) for name in response['coordinates']})['means']
  counts=e._counts(data,d['bins'])
  return sum(mean-counts[b['id']]*math.log(mean) for mean,b in zip(means,d['bins']))+sum(.5*(w.var('ravel_aux_'+str(i)).getVal()-w.var('ravel_aux_'+str(i)+'_In').getVal())**2 for i in range(len(d['auxiliary']['names'])))
 nll=NS(getVal=get_nll)
 prep=e.prepare(root,w,mc,data,nll,response,path/'preparation.json');e.validate_delivery(prep,response)
 f=fit();f['domain']=d['parameters'][0]['bounds']
 rows=roots(float(F(d['terms'][0]['coefficients'][0])),float(F(d['terms'][1]['coefficients'][0]))) if rows is None else rows
 request={'fit':f,'inference':n.extract_rows(deepcopy(rows),f),'preparation':prep}
 return root,w,mc,data,nll,response,request
