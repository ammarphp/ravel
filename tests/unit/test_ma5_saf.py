"""Portable native-format examples: supplied bytes only, no MA5 engine."""
import pytest
from ravel.physics import ma5_saf, ma5_saf_reader as reader
from ravel.workflow import science


def framed(content):
    return '<SAFheader>\n</SAFheader>\n'+content+'\n<SAFfooter>\n</SAFfooter>\n'


def histogram():
    # Deliberately weighted and negative-sign populated, with both flows.
    return framed('''<Histo>
<Description>
"momentum [GeV]"
2 0 20
Resolved
</Description>
<Statistics>
8 3
12.5 4.25
6 2
9.25 3.5
20.125 7.75
-2.5 -1.0
48.0 13.25
</Statistics>
<Data>
1.25 0.25
2.5 1.0
4.0 1.5
1.5 0.75
</Data>
</Histo>''')


def counter():
    return framed('''<InitialCounter>
"Initial number of events"
8 3
12.5 4.25
20.125 7.75
</InitialCounter>
<Counter>
"weighted cut"
6 2
9.25 3.5
18.0 7.0
</Counter>''')


def test_complete_literal_channels_flows_and_unavailable_bin_variance():
    h, = reader.histograms(histogram())
    assert h['name']=='momentum [GeV]' and (h['nbins'],h['xmin'],h['xmax'])==(2,0.,20.)
    assert h['regions']==['Resolved']
    assert h['positive']['array']==[2.5,4.0] and h['negative']['array']==[1.,1.5]
    assert (h['positive']['underflow'],h['positive']['overflow'])==(1.25,1.5)
    assert (h['negative']['underflow'],h['negative']['overflow'])==(.25,.75)
    assert h['positive']['nentries']==6 and h['negative']['nentries']==2
    assert h['positive']['sumw2']==20.125 and h['negative']['sumw2']==7.75
    assert h['positive']['sumwx']==-2.5 and h['negative']['sumwx']==-1.
    assert h['positive']['sumwx2']==48. and h['negative']['sumwx2']==13.25
    assert 'sumw2x' not in h['positive']
    assert h['native_moment_definitions']['sumwx2']=='sum(value^2*weight)'
    assert h['native_numeric_tokens']['statistics'][5]==['-2.5','-1.0']
    assert h['per_bin_sumw2'] is None and h['cross_bin_covariance'] is None


def test_complete_integer_counter_tokens_and_region_denominator():
    c=reader.counters(counter())
    assert c['initial']['positive']=={'nentries':8,'sumw':12.5,'sumw2':20.125}
    assert c['initial']['negative']=={'nentries':3,'sumw':4.25,'sumw2':7.75}
    assert c['cuts'][0]['name']=='weighted cut'
    assert c['cuts'][0]['native_numeric_tokens']==[['6','2'],['9.25','3.5'],['18.0','7.0']]
    assert reader.regions(framed('<RegionSelection>\n"Resolved"\n"Boosted"\n</RegionSelection>'))==['Resolved','Boosted']


@pytest.mark.parametrize('old,new',[
 ('<SAFheader>','<Unknown>'),('</Histo>','</Counter>'),
 ('1.5 0.75\n</Data>','</Data>'),('2 0 20','2 20 0'),
 ('2 0 20','2.5 0 20'),('9.25 3.5','nan 3.5'),('2.5 1.0','-2.5 1.0'),
 ('8 3','8.0 3'),('Resolved\n</Description>','Resolved\nResolved\n</Description>')])
def test_whole_histogram_adversaries_refuse(old,new):
    with pytest.raises(ValueError):reader.histograms(histogram().replace(old,new))


def test_duplicate_and_incomplete_counter_and_region_refuse():
    with pytest.raises(ValueError):reader.counters(counter().replace('"weighted cut"','"Initial number of events"'))
    with pytest.raises(ValueError):reader.counters(counter().replace('18.0 7.0\n',''))
    with pytest.raises(ValueError):reader.regions(framed('<RegionSelection>\n"Resolved"\n"Resolved"\n</RegionSelection>'))


def test_public_mode_resolves_adapter_and_requires_prospective_schema2():
    s={'schema_version':1,'mode':'ma5-saf','source':'Explicitly synthetic portable source-control description',
       'assumptions':['No engine, common-event or inference validation'], 'max_seconds':30,
       'approval_mode':'physicist','task':{'input':'supplied-input.json'}}
    assert science.adapter(s) is ma5_saf and science._new_capability(s)
    science.validate(s)
    for task in ({'input':''},{'input':1},{'input':'x','execute':True}):
        with pytest.raises(ValueError):ma5_saf.validate(task)
