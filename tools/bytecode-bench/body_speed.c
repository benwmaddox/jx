// per-element run speed: native body (clang -O3 / tcc, loaded by libtcc or compiled in) vs bytecode interpreter
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>
#include <stdint.h>
#include "libtcc.h"
typedef long long i64;
typedef struct { const char *doc; const i64 *age,*na,*nb,*ca,*cb; char *out; i64 outn; double sum; } Ctx;
typedef int (*Body)(Ctx*,i64);
#define N 190000
static double now(){ struct timespec t; clock_gettime(CLOCK_MONOTONIC,&t); return t.tv_sec*1e9+t.tv_nsec; }
// ---- interpreter
enum { LOADI, JLTK, JLEK, SPAN, LIT, HALT, JMP, SPANSEP, NL };
typedef struct { int op; int a; i64 k; } Ins;
// registers: r0 age ; spans from slots
#define SLOTN 0 // n spans
#define SLOTC 1
typedef struct { Ins *prog; } Prog;
static int run_switch(Ctx*c,const Ins*p,i64 i){
  i64 r0=0; const Ins*pc=p;
  for(;;){
    switch(pc->op){
    case LOADI: r0=c->age[i]; pc++; break;
    case JLTK: if(r0<pc->k){ pc=p+pc->a; } else pc++; break;         // jump if r0 < k
    case JLEK: if(r0<=pc->k){ pc=p+pc->a; } else pc++; break;
    case SPAN: { i64 a,b; if(pc->a==0){a=c->na[i];b=c->nb[i];} else {a=c->ca[i];b=c->cb[i];}
                 memcpy(c->out+c->outn,c->doc+a,b-a); c->outn+=b-a; pc++; break; }
    case NL: c->out[c->outn++]='\n'; pc++; break;
    case LIT: memcpy(c->out+c->outn,(const char*)pc->k,pc->a); c->outn+=pc->a; pc++; break;
    case JMP: pc=p+pc->a; break;
    case HALT: return 0;
    }
  }
}
static int run_goto(Ctx*c,const Ins*p,i64 i){
  static void *tab[]={&&L_LOADI,&&L_JLTK,&&L_JLEK,&&L_SPAN,&&L_LIT,&&L_HALT,&&L_JMP,0,&&L_NL};
  i64 r0=0; const Ins*pc=p;
#define NEXT goto *tab[pc->op]
  NEXT;
  L_LOADI: r0=c->age[i]; pc++; NEXT;
  L_JLTK: if(r0<pc->k){ pc=p+pc->a; } else pc++; NEXT;
  L_JLEK: if(r0<=pc->k){ pc=p+pc->a; } else pc++; NEXT;
  L_SPAN: { i64 a,b; if(pc->a==0){a=c->na[i];b=c->nb[i];} else {a=c->ca[i];b=c->cb[i];}
            memcpy(c->out+c->outn,c->doc+a,b-a); c->outn+=b-a; pc++; NEXT; }
  L_NL: c->out[c->outn++]='\n'; pc++; NEXT;
  L_LIT: memcpy(c->out+c->outn,(const char*)pc->k,pc->a); c->outn+=pc->a; pc++; NEXT;
  L_JMP: pc=p+pc->a; NEXT;
  L_HALT: return 0;
}
// programs
static Ins P1[]={ {LOADI,0,0},{JLTK,4,85},{SPAN,0,0},{NL,0,0},{HALT,0,0} };                        // select(.age>=85)|.n
static Ins P2[]={ {LOADI,0,0},{JLEK,5,50},{SPAN,0,0},{NL,0,0},{HALT,0,0},{SPAN,1,0},{NL,0,0},{HALT,0,0} }; // if .age>50 then .n else .city
static Ins P3[]={ {LIT,5,(i64)"{\"n\":"},{SPAN,0,0},{LIT,6,(i64)",\"c\":"},{SPAN,1,0},{LIT,1,(i64)"}"},{NL,0,0},{HALT,0,0} };  // {n:.n,c:.city}
static Ins *PP[]={P1,P2,P3};
// native (compiled with clang here, same source as the tcc one)
#define emit(c,s,n) do{ memcpy((c)->out+(c)->outn,(s),(n)); (c)->outn+=(n);}while(0)
static inline void emitspan0(Ctx*c,i64 a,i64 b){ memcpy(c->out+c->outn,c->doc+a,b-a); c->outn+=b-a; }
static inline void emitspan(Ctx*c,i64 a,i64 b){ i64 n=b-a; memcpy(c->out+c->outn,c->doc+a,n); c->outn+=n; c->out[c->outn++]='\n'; }
__attribute__((noinline)) int nb1(Ctx*c,i64 i){ if(c->age[i]>=85){ emitspan(c,c->na[i],c->nb[i]); } return 0; }
__attribute__((noinline)) int nb2(Ctx*c,i64 i){ if(c->age[i]>50){ emitspan(c,c->na[i],c->nb[i]); } else { emitspan(c,c->ca[i],c->cb[i]); } return 0; }
__attribute__((noinline)) int nb3(Ctx*c,i64 i){ emit(c,"{\"n\":",5); emitspan0(c,c->na[i],c->nb[i]); emit(c,",\"c\":",6); emitspan0(c,c->ca[i],c->cb[i]); c->out[c->outn++]='}'; c->out[c->outn++]='\n'; return 0; }
static Body NB[]={nb1,nb2,nb3};
static double bench_native(Ctx*c,Body f,int reps){ double best=1e18; for(int r=0;r<reps;r++){ c->outn=0; double t=now(); for(i64 i=0;i<N;i++) f(c,i); t=now()-t; if(t<best)best=t; } return best/N; }
static double bench_int(Ctx*c,Ins*p,int g,int reps){ double best=1e18; for(int r=0;r<reps;r++){ c->outn=0; double t=now(); if(g) for(i64 i=0;i<N;i++) run_goto(c,p,i); else for(i64 i=0;i<N;i++) run_switch(c,p,i); t=now()-t; if(t<best)best=t; } return best/N; }
int main(int argc,char**argv){
  static i64 age[N],na[N],nb[N],ca[N],cb[N]; char*doc=malloc(N*40); i64 pos=0;
  for(i64 i=0;i<N;i++){ age[i]=(i*37)%100; na[i]=pos; pos+=sprintf(doc+pos,"user%lld",i); nb[i]=pos; ca[i]=pos; pos+=sprintf(doc+pos,"c%lld",i); cb[i]=pos; }
  Ctx c={doc,age,na,nb,ca,cb,malloc(N*64),0,0};
  FILE*f=fopen(argv[1],"rb"); fseek(f,0,SEEK_END); long n=ftell(f); fseek(f,0,SEEK_SET); char*src=malloc(n+1); fread(src,1,n,f); src[n]=0;
  TCCState*s=tcc_new(); tcc_set_lib_path(s,"/home/ben/tcc/lib/tcc"); tcc_set_output_type(s,TCC_OUTPUT_MEMORY); tcc_compile_string(s,src); tcc_relocate(s,TCC_RELOCATE_AUTO);
  Body tb[3]={(Body)tcc_get_symbol(s,"body1"),(Body)tcc_get_symbol(s,"body2"),(Body)tcc_get_symbol(s,"body3")};
  const char*nm[3]={"select(.age>=85)|.n","if .age>50 then .n else .city","{n:.n,c:.city}"};
  const char*tag=argc>2?argv[2]:"";
  printf("ns/element %s (hit rates: P1 15%%, P2 all)\n",tag);
  for(int k=0;k<3;k++){
    double cl=bench_native(&c,NB[k],30); i64 o1=c.outn;
    double tc=bench_native(&c,tb[k],30); i64 o2=c.outn;
    double sw=bench_int(&c,PP[k],0,30); i64 o3=c.outn;
    double gt=bench_int(&c,PP[k],1,30); i64 o4=c.outn;
    printf("%-30s clang-native %5.1f  tcc-native %5.1f  interp-switch %5.1f  interp-goto %5.1f   (out bytes %lld %lld %lld %lld)\n",nm[k],cl,tc,sw,gt,o1,o2,o3,o4);
  }
}
