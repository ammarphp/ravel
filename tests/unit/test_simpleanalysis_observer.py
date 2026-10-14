"""Pure adversarial ELF association controls, not actual native qualification."""
import pytest

from ravel.physics.simpleanalysis_observer import verify_native_image


def fixture(tmp_path):
    binary=tmp_path/'simpleAnalysis'
    # Explicit artificial ELF header used only to exercise receipt validation.
    raw=bytearray(96);raw[:6]=b'\x7fELF\x02\x01';raw[18:20]=(62).to_bytes(2,'little')
    binary.write_bytes(raw);observer=tmp_path/'probe';observer.mkdir()
    path='/tmp/ravel-work/build/test-platform/bin/simpleAnalysis'
    (observer/'process.txt').write_text('pid\t42\nppid\t41\nrequested_binary\t'+path+'\nresolved_binary\t'+path+'\nproc_self_exe\t/emulator\nsegment\t[main]\t400000\t400060\t0\nmain_header_address\t400000\n')
    (observer/'requested-binary.bytes').write_bytes(raw)
    (observer/'main-elf-memory-header.bytes').write_bytes(raw[:64])
    (observer/'maps.raw').write_text('00400000-00401000 r-xp 00000000 08:01 42 '+path+'\n')
    (observer/'cmdline.raw').write_bytes(path.encode()+b'\0-l\0')
    (observer/'environment.raw').write_bytes(b'RAVEL_NATIVE_BINARY='+path.encode()+b'\0LC_ALL=C\0LC_CTYPE=C\0OMP_NUM_THREADS=1\0OPENBLAS_NUM_THREADS=1\0MKL_NUM_THREADS=1\0')
    (observer/'proc-self-exe.bytes').write_bytes(b'\x7fELFexplicit-protocol-emulator-standin')
    qualification={'native_process_observation':{'scope':'artificial association control'},'emulation_observation':{'scope':'artificial association control'}}
    return binary,observer,path,qualification


def test_memory_and_main_map_are_required_even_with_exact_named_binary(tmp_path):
    binary,observer,path,qualification=fixture(tmp_path)
    proof=verify_native_image(observer,binary,path,qualification)
    assert proof['status']=='passed' and proof['pid']==42
    assert proof['proc_self_exe']['role']=='distinct-image-under-qualified-emulation'
    assert proof['physics_validated'] is False


@pytest.mark.parametrize('defect',['file','memory','map','offset','argv','environment','qualification','main','architecture'])
def test_named_binary_or_listing_cannot_replace_actual_main_image_association(tmp_path,defect):
    binary,observer,path,qualification=fixture(tmp_path)
    if defect=='file':(observer/'requested-binary.bytes').write_bytes(b'other program')
    elif defect=='memory':(observer/'main-elf-memory-header.bytes').write_bytes(b'other memory')
    elif defect=='map':(observer/'maps.raw').write_text('00400000-00401000 r-xp 00000000 08:01 42 /other/program\n')
    elif defect=='offset':(observer/'maps.raw').write_text('00400000-00401000 r-xp 00001000 08:01 42 '+path+'\n')
    elif defect=='argv':(observer/'cmdline.raw').write_bytes(b'/other/program\0-l\0')
    elif defect=='environment':(observer/'environment.raw').write_bytes(b'RAVEL_NATIVE_BINARY=/other/program\0')
    elif defect=='qualification':qualification['emulation_observation']={}
    elif defect=='main':(observer/'process.txt').write_text((observer/'process.txt').read_text().replace('segment\t[main]','segment\tother'))
    elif defect=='architecture':
        raw=bytearray(binary.read_bytes());raw[18:20]=(183).to_bytes(2,'little');binary.write_bytes(raw)
    with pytest.raises(ValueError):verify_native_image(observer,binary,path,qualification)
