! SPDX-License-Identifier: GPL-3.0-or-later
program ravel_mcfm_amplitudes
  use types
  use omp_lib
  use CPUTime
  use SCET, only: doMultitaucut
  use MCFMSettings
  use MCFMStorage, only: IntegrationInfo,integrate,currentPart,currentIps
  use Integration, only: lord
  use ravel_four_lepton, only: active,draw,wanted,stream,accepted,rejected,failed,excluded, &
      captured,coordinates,gridweight,dump_point,failed_draw
  use, intrinsic :: ieee_arithmetic
  use m_config, only: cfg_get
  use m_gencuts, only: enable_reweight_user
  use parseinput, only: cfg
  use, intrinsic :: iso_fortran_env, only: int64
  implicit none
  include 'mpicommon.f'
  include 'nf.f'
  include 'constants.f'
  include 'mxpart.f'
  include 'vegas_common.f'
  include 'plabel.f'
  include 'interference.f'
  include 'masses.f'
  include 'anom_higgs.f'
  ! src/Inc/cpscheme.f has fixed-form comment lines and cannot be included in free form. Its common
  ! block is declared here; upstream-api.json pins that file's bytes.
  logical::CPscheme
  common/CPscheme/CPscheme
  include 'ipsgen.f'
  include 'taucut.f'
  include 'kpart.f'
  include 'limits.f'
  include 'cutoff.f'
  type(IntegrationInfo)::info
  integer::control,op,seed,flavour,actual_seed,nproc_,npoints,pointunit,i,j,status,gridunit,pairbranch
  integer(int64)::calls
  character(len=32)::part
  character(len=4096)::card,indir,outdir
  logical::sobol,pdfvar,scalevar,bin
  common/bin/bin
  real(dp)::p(mxpart,4),ref(fn:nf,fn:nf),start_time,end_time,dummy
  real(dp),external::lowint
  call omp_set_num_threads(1)
  world_size=1;rank=0
  call start_times()
  ! The program runs in the directory of the card named on the command line: its control, points
  ! and grid files and MCFM's own runtime files (process.DAT, br.sm1, br.sm2) are read there.
  ! Outputs go to RAVEL_OUTPUT_DIR when the execution backend sets it, otherwise to that directory.
  call get_command_argument(1,card)
  indir=card(1:index(card,'/',back=.true.))
  if(len_trim(indir)>0) then
     call chdir(trim(indir),status)
     if(status/=0) error stop 'cannot enter the card directory'
  endif
  call get_environment_variable('RAVEL_OUTPUT_DIR',outdir,status=status)
  if(status/=0.or.len_trim(outdir)==0) then
     outdir=''
  else
     outdir=trim(outdir)//'/'
  endif
  call mcfm_init()
  open(newunit=control,file='ravel-control.dat',status='old',action='read')
  read(control,*,iostat=status)op,calls,seed,flavour
  if(status/=0.or.op<0.or.op>2.or.calls<1.or.calls>10000000.or.seed<1.or.flavour<1.or.flavour>3) error stop 'invalid control'
  close(control)
  call cfg_get(cfg,'general%nproc',nproc_);call cfg_get(cfg,'general%part',part)
  call cfg_get(cfg,'integration%seed',actual_seed);call cfg_get(cfg,'integration%usesobol',sobol)
  call cfg_get(cfg,'lhapdf%dopdferrors',pdfvar);call cfg_get(cfg,'scales%doscalevar',scalevar)
  if(nproc_/=131.or.trim(part)/='lo'.or.actual_seed/=seed.or.sobol.or.pdfvar.or.scalevar) error stop 'outside native contract'
  if(CPscheme.or.anom_higgs.or.ndim/=10.or.enable_reweight_user) error stop 'ordinary BW fixed SM tensor required'
  if(pt34min/=0._dp.or.cutoff/=0._dp.or.wsqmin/=0._dp.or.bbsqmin/=0._dp.or.m3456min/=0._dp) &
      error stop 'initialized source domain has extra lower cuts'
  if(wsqmax/=(13000._dp*0.9999_dp)**2.or.bbsqmax/=(13000._dp*0.9999_dp)**2.or.m3456max/=13000._dp) &
      error stop 'initialized source mass support differs'
  if(flavour==1.and.(plabel(3)/='el'.or.plabel(5)/='ml'.or.interference)) error stop 'mixed flavour mismatch'
  if(flavour==2.and.(plabel(3)/='el'.or.plabel(5)/='el'.or..not.interference)) error stop '4e mismatch'
  if(flavour==3.and.(plabel(3)/='ml'.or.plabel(5)/='ml'.or..not.interference)) error stop '4mu mismatch'
  currentPart=lord;currentIps=1;ipsgen=1
  abovecut=.false.;usescet=.false.;kpart=klord
  doMultitaucut=.false.
  bin=.false.;wanted=int(calls);active=.true.
  open(newunit=stream,file=trim(outdir)//'amplitudes.dat',status='new',action='write')
  write(stream,*) 'RAVEL_MCFM_2',op,calls,seed,flavour
  write(stream,*) 'DOMAIN',wsqmin,wsqmax,bbsqmin,bbsqmax,m3456min,m3456max,pt34min,cutoff
  call cpu_time(start_time)
  if(op==0) then
     open(newunit=pointunit,file='ravel-points.dat',status='old',action='read')
     do i=1,int(calls)
        p=0._dp
        do j=1,6
           read(pointunit,*,iostat=status)p(j,:)
           if(status/=0) error stop 'incomplete point census'
        enddo
        draw=draw+1;captured=.false.;coordinates=0._dp;gridweight=1._dp
        ! Every point supplies its literal original pairing branch.
        read(pointunit,*,iostat=status)pairbranch
        if(status/=0.or.pairbranch<0.or.pairbranch>1) error stop 'literal pairing branch required'
        bw34_56=pairbranch==1
        call dump_point(p,1._dp,1._dp,1._dp,1._dp,0._dp,0._dp,0._dp,0._dp)
     enddo
     read(pointunit,*,iostat=status)dummy
     if(status>=0) error stop 'extra point population'
     close(pointunit)
  else
     info%si=0._dp;info%swgt=0._dp;info%schi=0._dp;info%lastIter=0
     info%doFirstCall=.false.;info%warmupComplete=.false.;info%damp=[1.5_dp,0.8_dp]
     info%useSobol=.false.;info%sobolInitialized=.false.;info%sobolSkip=1000
     info%callsPerIt=calls
     if(op==2) then
        open(newunit=gridunit,file='proposal-grid.bin',status='old',access='stream',form='unformatted',action='read')
        call info%deserialize(gridunit);close(gridunit)
        if(info%useSobol) error stop 'Sobol grid not independent native blocks'
        if(.not.allocated(info%grid)) error stop 'missing captured proposal grid'
        if(size(info%grid,2)/=ndim.or.size(info%grid,1)<2) error stop 'proposal dimensions'
        if(.not.all(ieee_is_finite(info%grid)).or.any(info%grid(1,:)<=0._dp)) error stop 'nonfinite/nonpositive grid'
        if(any(info%grid(size(info%grid,1),:)/=1._dp)) error stop 'full proposal support'
        do j=2,size(info%grid,1)
           if(any(info%grid(j,:)<=info%grid(j-1,:))) error stop 'degenerate proposal cell'
        enddo
        info%callsPerIt=calls
        call integrate(weighted,1,1,ndim,info)
     else
        call integrate(weighted,0,1,ndim,info)
        open(newunit=gridunit,file=trim(outdir)//'proposal-grid.bin',status='new',access='stream',form='unformatted',action='write')
        call info%serialize(gridunit);close(gridunit)
     endif
  endif
  call cpu_time(end_time)
  write(stream,*) 'COMPLETE',draw,accepted,rejected,failed,excluded,end_time-start_time
  close(stream)
  if(draw/=int(calls).or.draw/=accepted+rejected+failed.or.failed/=0) error stop 'incomplete block'
contains
  function weighted(r,wgt)result(value)
    real(dp),intent(in)::r(mxdim),wgt
    real(dp)::value
    value=lowint(r,wgt)
    if(.not.captured) call failed_draw(5)
    ! Positive original full-SM envelope, same original mapping and grid.
    ! Cache/model support adequacy is an explicit qualification obligation.
    if(.not.ieee_is_finite(value))then
       value=0._dp
    else
       value=abs(value)
    endif
  end function
end program
