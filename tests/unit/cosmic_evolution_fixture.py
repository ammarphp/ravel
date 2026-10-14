"""Disclosed synthetic small ABI and inert clients, never CosmicIC/Nyx physics."""
from pathlib import Path
from copy import deepcopy
import io,json,os,struct,time,hashlib
from ravel.physics import cosmic_evolution as op, cosmic_evolution_core as core, cosmic_evolution_worker as worker
from ravel.workflow.state_io import atomic_json
FIELDS=['density','xmom','ymom','zmom','rho_e','Temp','phi_grav','particle_mass_density','particle_count']
ZS=[7,6,5,4,3,2]
LIMITS={'max_input_files':500,'max_input_bytes':16*1024**2,'max_output_files':1000,'max_output_bytes':32*1024**2,
        'max_seconds':60,'cleanup_seconds':5,'max_controller_bytes':1024**2,'max_controller_calls':100,'handshake_seconds':5}
def pin(p):
    p=Path(p).absolute();raw=p.read_bytes();return {'path':str(p),'sha256':hashlib.sha256(raw).hexdigest(),'size':len(raw)}
def write(p,value):
    p=Path(p);p.parent.mkdir(parents=True,exist_ok=True)
    if type(value) is bytes:p.write_bytes(value)
    elif type(value) is str:p.write_text(value)
    else:atomic_json(p,value)
    return pin(p)
def schema():
    j={k:[k] for k in ('job_id','uid','submit','start','restarts','state','nodes')}
    s={k:[k] for k in ('job_id','step_id','uid','start','state','nodes')}
    return {'job':{'records':['jobs'],'fields':j,'timestamp_format':'unix-seconds'},
            'step':{'records':['steps'],'fields':s,'timestamp_format':'unix-seconds'}}
def fixture(root, operation='source-preparation', generated=False, writer=True):
    root=Path(root);root.mkdir(parents=True)
    req=write(root/'original.txt','Synthetic test request: source-bound IC and full nine-field six-redshift delivery. No science.\n')
    src=root/'source';s=write(src/'writer.cpp','Synthetic ABI fixture only; not actual CosmicIC writer source.\n')
    w={'kind':'AMReX-BinaryFile','byte_order':'little','long_bytes':8,'int_bytes':4,'real_bytes':8,'dimension':3,'extra_values':4,'source_evidence':[s]}
    wp=write(root/'writer.json',w) if writer else None
    iccard=write(root/'input.par','np=2\nz_in=200\nPrintFormat=6\nseed=343240149\nsigma8=0.83\n')
    nyx='amr.n_cell=2 2 2\nnyx.initial_z=200\nnyx.final_z=2\nnyx.plot_z_values=7 6 5 4 3 2\namr.plot_vars=density xmom ymom zmom rho_e\namr.derive_plot_vars=Temp phi_grav particle_mass_density particle_count\nnyx.analysis_z_values=7 6 5 4 3 2\namr.checkpoint_files_output=1\namr.probin_file=""\nnyx.particle_init_type=BinaryMetaFile\nnyx.binary_particle_file=FileList\n'
    nyxcard=write(root/'inputs',nyx)
    tf=write(root/'cmb.tf','# k/h species signed columns\n.01 -1 0\n.1 -2 0.2\n')
    norm=write(root/'normalization.txt','Declared synthetic units and original normalization; unqualified.\n')
    icroot=root/'retained-ic';chunk=write(icroot/'chunk.bin',struct.pack('<qii',8,3,4)+bytes(8*7*8))
    fl=write(icroot/'FileList','chunk.bin\n')
    scope={'ic_shape':[2,2,2],'nyx_shape':[2,2,2],'initial_redshift':200,'final_redshift':2,
           'fields':FIELDS,'redshifts':ZS,'analysis_redshifts':ZS,'checkpoint':True,
           'other_obligations':['full particle/binary levels','halo','in-situ','parameters','jobInfo','comoving_a']}
    required=[f'nyx/native/plt{z}/Header' for z in ZS]+[f'nyx/native/plt{z}/Level_0/Cell_D_00000' for z in ZS]+['nyx/native/chk/Header','nyx/native/halo.txt','nyx/native/insitu.txt','nyx/native/jobInfo','nyx/native/comoving_a','nyx/native/parameters']
    markers=[{'path':f'nyx/native/plt{z}/Header','lines':FIELDS+[f'z={z}']} for z in ZS]
    payload=write(root/'native','#!/bin/false\n');(root/'native').chmod(0o700)
    def phase(id,kind,copies,argv,payload=payload,ic_handoff=None):
        return {'id':id,'kind':kind,'payload':payload,'argv':argv,'copies':copies,'ranks':2,'nodes':2,'gpus_per_node':0,'max_seconds':15,'ic_handoff':ic_handoff}
    phases=[phase('build','build',[],[]),phase('ic','cosmicic',[{'file':iccard,'to':'input.par'},{'file':tf,'to':'cmb.tf'}],['input.par','cmb.tf','ics'],{'build_phase':'build','path':'init'}),
            phase('nyx','nyx',[{'file':nyxcard,'to':'inputs'}],['inputs'],payload,{'file_list_to':'FileList','chunks_to':['chunk.bin']})]
    if generated:phases[-1]['ic_handoff']['chunks_to']=['ics/chunk.bin']
    sc=schema();schemap=write(root/'slurm-schema.json',sc)
    runtime={'python':payload,'slurm':{k:payload for k in ('srun','scontrol','scancel')},'schemas':schemap,
             'version':'slurm synthetic-1','allocation':{'cluster':'fixture','job_id':17,'uid':os.getuid(),'submit':1,'start':2,'restarts':0,'nodes':['n0','n1']},'environment':{},'files':[s]}
    case={'id':'fixture','ic_card':iccard,'nyx_card':nyxcard,'transfer':{'columns':['k/h','Tcb','Tnu'],'units':['1/Mpc','declared','declared'],'redshift':200,'normalization':norm,'file':tf},
          'ic':{'generated_phase':'ic','file_list':'ics/FileList','shape':[2,2,2]} if generated else {'file_list':fl,'chunks':[chunk],'shape':[2,2,2],'reader_base':str(icroot)},
          'scope':scope,'outputs':{'required_files':required,'text_markers':markers,'scope':deepcopy(scope)},'retained_root':None,'phases':phases if operation=='site-local-execution' else [],'data_files':[]}
    if generated and not case['phases']:case['phases']=phases
    d={'schema_version':1,'source':'Synthetic engineering fixture, no actual native runtime/source evidence','operation':operation,'original_requests':[req],
       'source_trees':[{'root':str(src),'files':[s]}],'writer_contract':wp,'cases':[case], 'runtime':runtime if operation=='site-local-execution' else None,'resources':deepcopy(LIMITS)}
    path=root/'request.json';write(path,d);return path,d,w,sc

def save(path,d):write(path,d);return {'input':str(path)}
def payload_outputs(work):
    work=Path(work)
    for z in ZS:
        write(work/f'plt{z}/Header','\n'.join(FIELDS+[f'z={z}'])+'\n');write(work/f'plt{z}/Level_0/Cell_D_00000',b'opaque synthetic native bytes')
    for f in ('chk/Header','halo.txt','insitu.txt','jobInfo','comoving_a','parameters'):write(work/f,b'synthetic complete declared output\n')

class FakeController:
    last=None
    def __init__(self,runtime,root,capture,limits,deadline):
        self.runtime=runtime;self.env={**os.environ,'SLURM_JOB_ID':'17'};self.calls=[];self.state='RUNNING';self.step=0;self.start=int(time.time());type(self).last=self
    def invoke(self,argv):
        self.calls.append({'argv':argv,'inert':True})
        return b'slurm synthetic-1\n' if '--version' in argv else b'ClusterName = fixture\n'
    def expand_nodes(self,v):assert v=='n[0-1]';return ['n0','n1']
    def observe(self,kind,job,step):
        self.calls.append({'kind':kind,'job':job,'step':step,'inert':True})
        if kind=='job':return json.dumps({'jobs':[{**{k:v for k,v in self.runtime['allocation'].items() if k!='cluster'},'state':'RUNNING'}]}).encode()
        if kind=='cancel':self.state='CANCELLED';return b''
        return json.dumps({'steps':[{'job_id':17,'step_id':step,'uid':os.getuid(),'start':self.start,'state':self.state,'nodes':['n0','n1']}]}).encode()
class FakeClient:
    def __init__(self,argv,cwd,env,max_bytes):
        self.stdout=io.BytesIO();self.plan=worker._document(argv[-2],argv[-1]);self.done=False;self.ctl=FakeController.last;self.ctl.step+=1;self.step=self.ctl.step;self.ctl.state='RUNNING';self.ctl.start=int(time.time())
        for i in range(self.plan['ranks']):
            atomic_json(Path(self.plan['handshake'])/f'rank-{i}.json',{'nonce':self.plan['nonce'],'job_id':17,'step_id':self.step,'uid':os.getuid(),'rank':i,'node':['n0','n1'][i%2],'payload':self.plan['payload']})
    def poll(self):
        if not (Path(self.plan['handshake'])/'ack.json').exists():return None
        if not self.done:
            self.done=True;work=Path(self.plan['native_cwd'])
            if self.plan['phase_id']=='build':write(work/'init','#!/bin/false\n');(work/'init').chmod(0o700)
            elif self.plan['phase_id']=='ic':write(work/'ics/FileList','ics/chunk.bin\n');write(work/'ics/chunk.bin',struct.pack('<qii',8,3,4)+bytes(8*7*8))
            else:payload_outputs(work)
            for i in range(self.plan['ranks']):atomic_json(Path(self.plan['handshake'])/f'exit-{i}.json',{'rank':i,'exit_code':0,'job_id':17,'step_id':self.step})
            self.ctl.state='COMPLETED'
        return 0
    def close(self,stop=False):self.stdout.close();return {'returncode':0,'inert':True,'leader_reaped':None,'local_group_absence':None}

def policy():
    return {'schema_version':1,'policy':{'schema_version':1,'actors':dict(proposer='p',executor='e',physics_critic='c',skeptical_verifier='v',physics_decider='d'),'max_redos':0,'allowed_changed_paths':[],'allowed_stages':['science'],
             'required_checks':[{'id':'custody','kind':'integrity'}],'claim_scopes':{'source_delivery':{'checks':['custody'],'actions':['delivery','reuse']}}},'correction_contract':{'input_slots':[],'task_fields':[]}}


def inert_admission(monkeypatch, base):
    """Only fake native/rank callbacks: no actual approval/launch attestation."""
    token={'synthetic_inert_parent_admission':True}
    monkeypatch.setattr(worker,'_admission',lambda rd,**kw:({'base_dir':str(base),'output_directory':'outputs/attempt-1'},token))
    return token
