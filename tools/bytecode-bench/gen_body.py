import sys
# generate C: a hot body plus filler functions, N lines total approx
n=int(sys.argv[1])
print('''typedef long long i64; void *memcpy(void*,const void*,unsigned long); typedef struct { const char *doc; const i64 *age,*na,*nb,*ca,*cb; char *out; i64 outn; double sum; } Ctx;
static inline void emit(Ctx*c,const char*s,i64 n){ memcpy(c->out+c->outn,s,n); c->outn+=n; }
static inline void emitspan(Ctx*c,i64 a,i64 b){ i64 n=b-a; memcpy(c->out+c->outn,c->doc+a,n); c->outn+=n; c->out[c->outn++]='\n'; }
static inline void emitspan0(Ctx*c,i64 a,i64 b){ memcpy(c->out+c->outn,c->doc+a,b-a); c->outn+=b-a; }
int body1(Ctx*c,i64 i){ if(c->age[i]>=85){ emitspan(c,c->na[i],c->nb[i]); } return 0; }
int body2(Ctx*c,i64 i){ if(c->age[i]>50){ emitspan(c,c->na[i],c->nb[i]); } else { emitspan(c,c->ca[i],c->cb[i]); } return 0; }
int body3(Ctx*c,i64 i){ emit(c,"{\\"n\\":",5); emitspan0(c,c->na[i],c->nb[i]); emit(c,",\\"c\\":",6); emitspan0(c,c->ca[i],c->cb[i]); c->out[c->outn++]='}'; c->out[c->outn++]='\n'; return 0; }''')
lines=8
k=0
while lines<n:
    print('''int filler%d(Ctx*c,i64 i){
  i64 x=c->age[i]; i64 y=c->na[i];
  if(x>%d){ y+=x*%d; } else if(x<%d){ y-=x; } else { y^=%d; }
  switch(x&3){ case 0: y+=1; break; case 1: y+=c->cb[i]-c->ca[i]; break; case 2: y<<=1; break; default: y=-y; }
  for(i64 j=0;j<4;j++){ y+=c->doc[c->na[i]+j]; if(y>%d) y-=%d; }
  c->sum+=(double)y*0.5;
  if(y&1){ emitspan(c,c->na[i],c->nb[i]); }
  return (int)y;
}'''%(k,k%90,k+2,k%7,k,1000+k,500+k)); lines+=9; k+=1
