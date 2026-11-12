// compile-time and memory of libtcc in-process
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>
#include <sys/resource.h>
#include "libtcc.h"
static size_t nmal,nfree,nreal,bytes,live,peak;
void *__real_malloc(size_t); void *__real_calloc(size_t,size_t); void *__real_realloc(void*,size_t); void __real_free(void*);
// header-less tracking: store size before block
void *__wrap_malloc(size_t n){ size_t*p=__real_malloc(n+16); if(!p) return 0; p[0]=n; nmal++; bytes+=n; live+=n; if(live>peak)peak=live; return p+2; }
void *__wrap_calloc(size_t a,size_t b){ size_t n=a*b; size_t*p=__real_calloc(1,n+16); if(!p) return 0; p[0]=n; nmal++; bytes+=n; live+=n; if(live>peak)peak=live; return p+2; }
void *__wrap_realloc(void*q,size_t n){ if(!q) return __wrap_malloc(n); size_t*o=(size_t*)q-2; size_t on=o[0]; size_t*p=__real_realloc(o,n+16); if(!p) return 0; p[0]=n; nreal++; live+=n-on; bytes+=n; if(live>peak)peak=live; return p+2; }
void __wrap_free(void*q){ if(!q) return; size_t*o=(size_t*)q-2; live-=o[0]; nfree++; __real_free(o); }
static double now(){ struct timespec t; clock_gettime(CLOCK_MONOTONIC,&t); return t.tv_sec*1e3+t.tv_nsec/1e6; }
int main(int argc,char**argv){
  FILE*f=fopen(argv[1],"rb"); fseek(f,0,SEEK_END); long n=ftell(f); fseek(f,0,SEEK_SET); char*src=malloc(n+1); fread(src,1,n,f); src[n]=0;
  int reps=argc>2?atoi(argv[2]):20; double best=1e9, tot=0;
  for(int r=0;r<reps;r++){
    size_t m0=nmal,f0=nfree,r0=nreal,b0=bytes; live=0; peak=0;
    double t0=now();
    TCCState*s=tcc_new(); tcc_set_lib_path(s,"/home/ben/tcc/lib/tcc"); tcc_set_output_type(s,TCC_OUTPUT_MEMORY);
    if(tcc_compile_string(s,src)<0){ puts("compile error"); return 1; }
    double t1=now();
    if(tcc_relocate(s,TCC_RELOCATE_AUTO)<0){ puts("reloc error"); return 1; }
    double t2=now();
    void*b1=tcc_get_symbol(s,"body1"); if(!b1) return 2;
    if(r==reps-1) printf("src %ld bytes; malloc %zu realloc %zu free %zu; allocated total %zu KB; peak live %zu KB\n",n,nmal-m0,nreal-r0,nfree-f0,(bytes-b0)/1024,peak/1024);
    tcc_delete(s);
    double t3=now(); if(t3-t0<best) best=t3-t0; tot+=t3-t0;
    if(r==reps-1) printf("compile %.2f ms, relocate %.2f ms, total with new+delete best %.2f ms mean %.2f\n",t1-t0,t2-t1,best,tot/reps);
  }
  struct rusage ru; getrusage(RUSAGE_SELF,&ru); printf("maxrss %ld KB\n",ru.ru_maxrss);
}
