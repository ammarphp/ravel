"""Lossless raw expansion transport for disjoint complete physical groups.

Partitions are a coverage decomposition, never separately normalized studies.
The declared event/group law remains a scientific premise, not a proof of
independence. No numerical SDK or remote reader is imported here.
"""
from copy import deepcopy
from ravel.physics import root_stream_core as c

ENTRY_LAW='poissonized_independent_physical_events_with_event_common_weights'
GROUP_LAW='poissonized_independent_declared_physical_groups_with_common_record_weights'
IDENTITY='authenticated complete member-entry and declared physical-group census; independent declared groups'


def dump_moments(m):
    return {'contract':deepcopy(m.contract),'sum_partials':[deepcopy(x.partials) for x in m.sums],
            'product_partials':[[deepcopy(x.partials) for x in row] for row in m.products],
            'counts':deepcopy(m.counts),'negative_weight_records':deepcopy(m.negative)}


def restore_moments(row,contract):
    c.keys(row,('contract','sum_partials','product_partials','counts','negative_weight_records'),'raw partition expansions')
    c.require(row['contract']==contract,'partition schema/bin/normalization/weight order differs')
    m=c.Moments(contract);d=len(m.sums)
    c.require(type(row['sum_partials']) is list and len(row['sum_partials'])==d and
              type(row['product_partials']) is list and len(row['product_partials'])==d,'complete expansion dimensions required')
    def add(target,values):
        c.require(type(values) is list and len(values)<=2048,'bounded full float expansion required')
        for value in values:target.add(c.scalar(value))
    for target,values in zip(m.sums,row['sum_partials']):add(target,values)
    for i,(targets,values) in enumerate(zip(m.products,row['product_partials'])):
        c.require(type(values) is list and len(values)==d,'complete cross-moment expansions required')
        for j,(target,partials) in enumerate(zip(targets,values)):
            c.require(j>=i or partials==[],'lower-triangle expansion must remain empty')
            add(target,partials)
            if i==j:c.require(target.value()>=0,'nonnegative physical-group second moment required')
    c.keys(row['counts'],m.counts,'partition event/fill counters')
    for name,value in row['counts'].items():c.integer(value,0,10**18,'full partition counter')
    count=row['counts'];c.require(count['empty_records']<=count['records'] and count['fills']==count['in_range']+count['flow'],'partition counters disagree')
    c.keys(row['negative_weight_records'],m.names,'full negative-weight counters')
    for value in row['negative_weight_records'].values():c.integer(value,0,count['records'],'negative group/event counter')
    m.counts=deepcopy(count);m.negative=deepcopy(row['negative_weight_records']);return m


def merge_moments(target,row):
    source=restore_moments(row,target.contract)
    for a,b in zip(target.sums,source.sums):
        for value in b.partials:a.add(value)
    for i in range(len(target.sums)):
        for j in range(i,len(target.sums)):
            for value in source.products[i][j].partials:target.products[i][j].add(value)
    for name in target.counts:target.counts[name]+=source.counts[name]
    for name in target.negative:target.negative[name]+=source.negative[name]


class GroupMoments(c.Moments):
    """Sum a complete correlated record group before forming its outer product."""
    def __init__(self,contract):
        super().__init__(contract);self.group=[c.Adder() for _ in self.sums];self.group_fills=0;self.admitted=0
    def event(self,weights,fills):
        c.keys(weights,self.names,'all original group weights');c.require(type(fills) is list,'group record fill list required')
        multiplicity={};self.admitted+=1
        for fill in fills:
            c.require(type(fill) is list and len(fill)==len(self.contract['axes']),'group fill dimensions differ')
            for x in fill:c.scalar(x)
            i=next((j for j,b in enumerate(self.bins) if all(lo<=x<hi for x,lo,hi in zip(fill,b['low'],b['high']))),len(self.bins))
            multiplicity[i]=multiplicity.get(i,0)+1;self.group_fills+=1;self.counts['fills']+=1
            self.counts['in_range' if i<len(self.bins) else 'flow']+=1
        for k,name in enumerate(self.names):
            w=c.scalar(weights[name])
            for i,n in multiplicity.items():self.group[k*self.stride+i].add(c.scalar(w*n))
            self.group[k*self.stride+len(self.bins)+1].add(w)
    def flush_group(self):
        if self.admitted:
            values=[x.value() for x in self.group];self.counts['records']+=1;self.counts['empty_records']+=self.group_fills==0
            for k,name in enumerate(self.names):self.negative[name]+=values[k*self.stride+len(self.bins)+1]<0
            for i,a in enumerate(values):
                self.sums[i].add(a)
                for j in range(i,len(values)):self.products[i][j].add(c.scalar(a*values[j]))
        self.group=[c.Adder() for _ in self.sums];self.group_fills=0;self.admitted=0


class PartitionStream(c.Stream):
    def __init__(self,ds,a,limits,master,part):
        super().__init__(ds,a,limits);self.master=master;self.part=part;self.grouped=master['grouping']['kind']=='declared_groups'
        self.intervals=part['intervals'];lookup={(s['id'],m['id']):(s,m) for s,m in self.members}
        self.members=[(lookup[(x['sample'],x['member'])][0],{**lookup[(x['sample'],x['member'])][1],'entries':x['stop']}) for x in self.intervals]
        self.offset=self.intervals[0]['start'];self.group_id=None;self.previous_group=None
        self.record2={s['id']:c.Adder() for s in ds['samples'] if s['kind']!='data'}
        self.group_raw=c.Adder();self.group_sample=None
        if self.grouped:self.moments={s['id']:{q['id']:GroupMoments(q['contract']) for q in a['quantities']} for s in ds['samples']}
    def flush(self):
        if self.previous_group is None:return
        for moment in self.moments[self.group_sample].values():moment.flush_group()
        if self.group_sample in self.raw:
            value=self.group_raw.value();self.raw[self.group_sample][1].add(c.scalar(value*value))
        self.group_raw=c.Adder();self.previous_group=None
    def chunk(self,sample_id,member_id,start,stop,entries,records,weight_rows):
        if not self.grouped:
            super().chunk(sample_id,member_id,start,stop,entries,records,weight_rows)
        else:
            c.require(self.index<len(self.members),'extra partition interval')
            s,m=self.members[self.index];interval=self.intervals[self.index]
            c.require(self.group_id==interval['group'],'actual complete group identity differs')
            if self.previous_group!=self.group_id:
                self.flush();self.previous_group=self.group_id;self.group_sample=sample_id
            c.require((sample_id,member_id)==(s['id'],m['id']) and type(start) is int and type(stop) is int and start==self.offset and
                      (start<stop<=m['entries'] or start==stop==m['entries']==0) and stop-start<=self.limits['chunk_entries'],'partition group interval gap/overlap/order')
            c.require(type(entries) is list and entries==sorted(set(entries)) and all(type(e) is int and start<=e<stop for e in entries),'exact group source entries required')
            if s['kind']!='data':c.require(entries==list(range(start,stop)),'group MC source rows cannot be omitted')
            c.require(type(records) is list and type(weight_rows) is list and len(records)==len(entries)==len(weight_rows),'complete admitted group rows required')
            for entry,record,row in zip(entries,records,weight_rows):
                c.keys(record,('source_entry','fills'),'group kernel record');c.require(record['source_entry']==entry and type(record['source_entry']) is int,'group source entry differs')
                c.keys(record['fills'],tuple(q['id'] for q in self.a['quantities']),'all original group quantities')
                if s['kind']!='data':
                    raw=c.scalar(row[self.a['weight_contract']['raw_mc_weight']]);self.raw[sample_id][0].add(raw)
                    self.group_raw.add(raw);self.record2[sample_id].add(c.scalar(raw*raw))
                weights=c.weights(s,self.a['weight_contract'],row)
                for q in self.a['quantities']:self.moments[sample_id][q['id']].event(weights,record['fills'][q['id']])
            self.chunks+=1;c.require(self.chunks<=self.limits['max_chunks'],'full partition chunk ceiling')
            self.coverage.append({'sample':sample_id,'member':member_id,'start':start,'stop':stop});self.offset=stop
            if stop==m['entries']:self.index+=1;self.offset=0
        if self.index<len(self.intervals) and self.offset==0:self.offset=self.intervals[self.index]['start']
    def finish(self):
        c.require(self.index==len(self.members),'partition interval population incomplete')
        if self.grouped:self.flush()
        else:
            # In this law every source entry is its independent group.
            for sid in self.record2:
                for value in self.raw[sid][1].partials:self.record2[sid].add(value)
        return {'schema_version':1,'kind':'root-stream-partition-moments','master_sha256':self.master['master_sha256'],
                'partition_id':self.part['id'],'sampling_law':GROUP_LAW if self.grouped else ENTRY_LAW,
                'coverage':deepcopy(self.coverage),'coverage_sha256':c.digest(self.coverage),'group_ids':deepcopy(self.part['group_ids']),
                'samples':[{'id':s['id'],'raw_mc_partials':None if s['kind']=='data' else
                    {'sumw':deepcopy(self.raw[s['id']][0].partials),'sumw2':deepcopy(self.raw[s['id']][1].partials),'record_sumw2':deepcopy(self.record2[s['id']].partials)},
                    'quantities':{q['id']:dump_moments(self.moments[s['id']][q['id']]) for q in self.a['quantities']}} for s in self.ds['samples']],
                'normalization_applied':False,'physics_validated':False}
