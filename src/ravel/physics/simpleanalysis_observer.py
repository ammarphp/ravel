"""Prospective native ELF observer and strict read-only image association.

Qualification of actual emulator/procfs behavior precedes any native admission.
The observer runs as a constructor in the actual selected process. It preserves
raw link-map, memory header and procfs facts rather than inferring execution from
an executable name or a successful listing alone.
"""
import hashlib
from pathlib import Path
import re

NATIVE_LOADER_OBSERVER = r'''#define _GNU_SOURCE
#include <link.h>
#include <elf.h>
#include <errno.h>
#include <fcntl.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/types.h>
#include <unistd.h>
static const char *directory;
static int copy_file(const char *from, const char *name) {
 char output[8192];snprintf(output,sizeof(output),"%s/%s",directory,name);
 int source=open(from,O_RDONLY),dest=open(output,O_WRONLY|O_CREAT|O_EXCL,0600);
 if(source<0 || dest<0)return -1;
 char buffer[65536];ssize_t size;
 while((size=read(source,buffer,sizeof(buffer)))>0) {
  ssize_t offset=0;while(offset<size){ssize_t n=write(dest,buffer+offset,size-offset);if(n<=0)return -1;offset+=n;}
 }
 close(source);close(dest);return size<0?-1:0;
}
static int loaded_image(struct dl_phdr_info *info,size_t size,void *data) {
 FILE *stream=(FILE *)data;const char *name=info->dlpi_name;uintptr_t header=0;
 for(int i=0;i<info->dlpi_phnum;i++) {
  const ElfW(Phdr) *ph=info->dlpi_phdr+i;
  if(ph->p_type!=PT_LOAD)continue;
  uintptr_t begin=info->dlpi_addr+ph->p_vaddr;
  fprintf(stream,"segment\t%s\t%lx\t%lx\t%lx\n",name&&*name?name:"[main]",(unsigned long)begin,(unsigned long)(begin+ph->p_memsz),(unsigned long)ph->p_offset);
  if(ph->p_offset==0)header=begin;
 }
 if(!name || !*name) {
  fprintf(stream,"main_header_address\t%lx\n",(unsigned long)header);
  if(!header)return -1;
  char output[8192];snprintf(output,sizeof(output),"%s/main-elf-memory-header.bytes",directory);
  int fd=open(output,O_WRONLY|O_CREAT|O_EXCL,0600);
  if(fd<0 || write(fd,(void *)header,sizeof(ElfW(Ehdr)))!=sizeof(ElfW(Ehdr)))return -1;
  close(fd);
 }
 return 0;
}
__attribute__((constructor)) static void observe(void) {
 directory=getenv("RAVEL_NATIVE_OBSERVER_DIRECTORY");const char *requested=getenv("RAVEL_NATIVE_BINARY");
 if(!directory || !requested || directory[0]!='/' || requested[0]!='/')_exit(121);
 char output[8192],resolved[8192],exe[8192];
 snprintf(output,sizeof(output),"%s/process.txt",directory);FILE *stream=fopen(output,"wx");
 if(!stream)_exit(122);
 ssize_t size=readlink("/proc/self/exe",exe,sizeof(exe)-1);if(size<0)_exit(123);exe[size]=0;
 if(!realpath(requested,resolved))_exit(124);
 fprintf(stream,"pid\t%ld\nppid\t%ld\nrequested_binary\t%s\nresolved_binary\t%s\nproc_self_exe\t%s\n",(long)getpid(),(long)getppid(),requested,resolved,exe);
 if(copy_file(requested,"requested-binary.bytes") || copy_file("/proc/self/exe","proc-self-exe.bytes") || copy_file("/proc/self/maps","maps.raw") || copy_file("/proc/self/cmdline","cmdline.raw") || copy_file("/proc/self/environ","environment.raw") || copy_file("/proc/self/status","status.raw"))_exit(125);
 if(dl_iterate_phdr(loaded_image,stream))_exit(126);
 fflush(stream);fsync(fileno(stream));fclose(stream);
}
'''


def verify_native_image(directory, binary, expected_guest_binary, qualification):
    """Require source-built ELF bytes associated with actual main link-map/mmap.

    A translated process may expose an emulator in proc/self/exe. That alone
    neither passes nor fails native main-image custody. Main PT_LOAD/memory and
    file mapping must independently identify the exact requested source binary.
    """
    directory,binary=Path(directory),Path(binary)
    if not qualification.get('native_process_observation') or not qualification.get('emulation_observation'):
        raise ValueError('actual native/emulator qualification must precede ELF admission')
    raw=binary.read_bytes()
    if not raw.startswith(b'\x7fELF') or len(raw)<64 or raw[4:6]!=b'\x02\x01' or int.from_bytes(raw[18:20],'little')!=62:
        raise ValueError('source-built ELF64 little-endian x86_64 required')
    lines=(directory/'process.txt').read_text().splitlines();facts={};segments=[]
    for line in lines:
        fields=line.split('\t')
        if fields[0]=='segment':
            if len(fields)!=5:raise ValueError('invalid raw native program-header segment')
            segments.append({'name':fields[1],'start':int(fields[2],16),'end':int(fields[3],16),'offset':int(fields[4],16)})
        else:
            if len(fields)!=2 or fields[0] in facts:raise ValueError('duplicate/invalid same-process native fact')
            facts[fields[0]]=fields[1]
    if set(facts)!={'pid','ppid','requested_binary','resolved_binary','proc_self_exe','main_header_address'} or not facts['pid'].isdigit() or int(facts['pid'])<=0 or not facts['ppid'].isdigit() or facts['requested_binary']!=expected_guest_binary or facts['resolved_binary']!=expected_guest_binary:
        raise ValueError('exact same-process PID and selected guest binary required')
    if (directory/'requested-binary.bytes').read_bytes()!=raw or (directory/'main-elf-memory-header.bytes').read_bytes()!=raw[:64]:
        raise ValueError('actual native memory/file bytes differ from source-built ELF')
    argv=(directory/'cmdline.raw').read_bytes().split(b'\0')
    if not argv or argv[0].decode()!=expected_guest_binary:
        raise ValueError('observed native argv does not select source-built binary')
    address=int(facts['main_header_address'],16)
    main=[segment for segment in segments if segment['name']=='[main]' and segment['offset']==0 and segment['start']==address and segment['end']>address]
    if len(main)!=1:raise ValueError('one actual native main ELF load segment required')
    mappings=[]
    for line in (directory/'maps.raw').read_text().splitlines():
        fields=line.split(None,5)
        if len(fields)!=6:continue
        begin,end=[int(v,16) for v in fields[0].split('-')]
        if begin<=address<end:
            mappings.append({'path':fields[5],'offset':int(fields[2],16),'start':begin,'end':end})
    if len(mappings)!=1 or mappings[0]['path']!=expected_guest_binary or mappings[0]['offset']!=0:
        raise ValueError('OS mapping does not associate native main image with source-built ELF')
    environment={}
    for entry in (directory/'environment.raw').read_bytes().split(b'\0'):
        if not entry:continue
        name,value=entry.decode().split('=',1)
        if name in environment:raise ValueError('duplicate native environment key')
        environment[name]=value
    if environment.get('RAVEL_NATIVE_BINARY')!=expected_guest_binary or any(environment.get(key)!='1' for key in ('OMP_NUM_THREADS','OPENBLAS_NUM_THREADS','MKL_NUM_THREADS')) or environment.get('LC_ALL')!='C' or environment.get('LC_CTYPE')!='C':
        raise ValueError('native selected binary/one-worker/locale environment differs')
    proc=(directory/'proc-self-exe.bytes').read_bytes()
    if not proc.startswith(b'\x7fELF'):raise ValueError('retained actual proc-self-exe ELF required')
    return {'status':'passed','pid':int(facts['pid']),'ppid':int(facts['ppid']),
        'binary_sha256':hashlib.sha256(raw).hexdigest(),'mapped_main_image':mappings[0],
        'proc_self_exe':{'path':facts['proc_self_exe'],'sha256':hashlib.sha256(proc).hexdigest(),
                         'role':'native-main-elf' if proc==raw else 'distinct-image-under-qualified-emulation'},
        'environment':environment,'physics_validated':False,
        'scope':'Same-process before-main native main-image association; not detector/event/model calibration or process attestation'}
