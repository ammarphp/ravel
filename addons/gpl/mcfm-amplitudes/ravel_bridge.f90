! SPDX-License-Identifier: GPL-3.0-or-later
! Authored RAVEL adaptation of the released MCFM 10.2.1 APIs/assembly.
! MCFM amplitudes: respective MCFM authors; gg_ZZ_all: J.M. Campbell.
! This module never supplies replacement loop amplitudes or event generation.
module ravel_four_lepton
  use types
  use, intrinsic :: ieee_arithmetic
  implicit none
  include 'mxpart.f'
  include 'mxdim.f'
  integer :: stream=0, draw=0, wanted=0, accepted=0, rejected=0, failed=0, excluded=0
  logical :: active=.false., captured=.false., export_cache=.true.
  real(dp) :: coordinates(mxdim)=0._dp, gridweight=0._dp
contains
  subroutine begin_draw(r,wgt)
    real(dp),intent(in)::r(mxdim),wgt
    if (.not.active) return
    draw=draw+1; captured=.false.;coordinates=r;gridweight=wgt
  end subroutine

  subroutine failed_draw(code)
    integer,intent(in)::code
    if (.not.active.or.captured) return
    captured=.true.;failed=failed+1
    write(stream,*) 'FAIL',draw,code
    flush(stream)
  end subroutine

  subroutine rejected_draw()
    if (.not.active.or.captured) return
    captured=.true.;rejected=rejected+1
    write(stream,*) 'REJECT',draw
    flush(stream)
  end subroutine

  subroutine dump_point(p,pswt,flux,pdf,br,x1,x2,fac,ren)
    use, intrinsic :: iso_fortran_env, only: real64
    implicit none
    real(dp),intent(in)::p(mxpart,4),pswt,flux,pdf,br,x1,x2,fac,ren
    include 'nf.f'
    include 'constants.f'
    include 'masses.f'
    include 'qcdcouple.f'
    include 'zcouple_cms.f'
    include 'interference.f'
    complex(dp)::a(2,2,2,2,6,2),prop,higgsprop
    real(dp)::swp(mxpart,4),msq(fn:nf,fn:nf),full,hpi,box,norm,ss,pttwo
    integer::i,j,k,l,ch,pair,iv
    logical::safe
    external higgsprop,pttwo
    if (.not.active.or.captured) return
    captured=.true.
    if (br==0._dp.or..not.ieee_is_finite(pswt*flux*pdf*gridweight)) then
       failed=failed+1;write(stream,*) 'FAIL',draw,3;flush(stream);return
    endif
    a=cmplx(0._dp,0._dp,dp);swp=p
    call getggZZamps(p,.true.,.true.,.true.,a(:,:,:,:,1,1),a(:,:,:,:,2,1),a(:,:,:,:,3,1),a(:,:,:,:,4,1))
    call getggHZZamps(p,a(:,:,:,:,5,1),a(:,:,:,:,6,1))
    if (interference) then
       swp(4,:)=p(6,:);swp(6,:)=p(4,:)
       call getggZZamps(swp,.true.,.true.,.true.,a(:,:,:,:,1,2),a(:,:,:,:,2,2),a(:,:,:,:,3,2),a(:,:,:,:,4,2))
       call getggHZZamps(swp,a(:,:,:,:,5,2),a(:,:,:,:,6,2))
    else
       a(:,:,:,:,:,2)=a(:,:,:,:,:,1)
    endif
    ! Independent original assembly at exactly this state, not cached math.
    call gg_ZZ_all(p,msq);full=msq(0,0)
    call gg_ZZ_Hpi(p,msq);hpi=msq(0,0)
    call gg_ZZ(p,box)
    ss=(p(1,4)+p(2,4))**2-sum((p(1,1:3)+p(2,1:3))**2)
    prop=higgsprop(ss)
    norm=avegg*V*(four*abs(zesq)*gsq/(16._dp*pisq)*abs(zesq))**2*vsymfact
    safe=pttwo(3,4,p)<0.1_dp.or.pttwo(5,6,p)<0.1_dp
    if (interference) safe=safe.or.pttwo(3,4,swp)<0.1_dp.or.pttwo(5,6,swp)<0.1_dp
    if (.not.all(ieee_is_finite(real(a,dp))).or..not.all(ieee_is_finite(aimag(a))).or. &
        .not.ieee_is_finite(full).or..not.ieee_is_finite(hpi).or..not.ieee_is_finite(box)) then
       failed=failed+1;write(stream,*) 'FAIL',draw,4;flush(stream);return
    endif
    accepted=accepted+1
    if(safe) excluded=excluded+1
    ! List-directed output is parsed with a strict finite numeric/token census.
    write(stream,*) 'POINT',draw,merge(1,0,interference),merge(1,0,bw34_56),merge(1,0,safe)
    write(stream,*) 'META',ss,hmass,hwidth,real(prop,dp),aimag(prop),norm,full,hpi,box
    write(stream,*) 'WEIGHT',gridweight,pswt,flux,pdf,br,x1,x2,fac,ren
    write(stream,*) 'COORD',coordinates(1:12)
    do iv=1,6
       write(stream,*) 'P',iv,p(iv,:)
    enddo
    do pair=1,2;do ch=1,6
       do i=1,2;do j=1,2;do k=1,2;do l=1,2
          write(stream,*) 'A',pair,ch,i,j,k,l,real(a(i,j,k,l,ch,pair),dp),aimag(a(i,j,k,l,ch,pair))
       enddo;enddo;enddo;enddo
    enddo;enddo
    write(stream,*) 'ENDPOINT',draw
    flush(stream)
  end subroutine
end module

