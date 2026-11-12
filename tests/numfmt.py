import math, struct, random, subprocess
JQ=r'C:\ProgramData\chocolatey\lib\jq\tools\jq.exe'
def digits_exp(x):
    # shortest digits via repr
    r=repr(abs(x))
    if 'e' in r:
        m,e=r.split('e'); e=int(e)
    else:
        m,e=r,0
    if '.' in m:
        ip,fp=m.split('.')
    else:
        ip,fp=m,''
    ds=(ip+fp)
    pt=len(ip)+e
    # strip leading zeros
    k=0
    while k<len(ds)-1 and ds[k]=='0': k+=1; pt-=1
    ds=ds[k:].rstrip('0') or '0'
    return ds,pt
def jqfmt(x):
    if x!=x: return 'null'
    if x==math.inf: x=1.7976931348623157e308
    if x==-math.inf: x=-1.7976931348623157e308
    if x==0: return '-0' if math.copysign(1,x)<0 else '0'
    ds,decpt=digits_exp(x)
    sign='-' if x<0 else ''
    n=len(ds)
    if decpt<=-4 or decpt>n+15:
        s=ds[0]+('.'+ds[1:] if n>1 else '')
        e=decpt-1
        s+='e'+('-' if e<0 else '+')+('%02d'%abs(e))
    elif decpt<=0:
        s='0.'+'0'*(-decpt)+ds
    elif decpt>=n:
        s=ds+'0'*(decpt-n)
    else:
        s=ds[:decpt]+'.'+ds[decpt:]
    return sign+s
def jqbatch(prog, items):
    p=subprocess.run([JQ,'-c',prog],input=('['+','.join(items)+']').encode(),capture_output=True)
    return p.stdout.decode().replace(chr(13),'').split('\n'), p.stderr.decode()
if __name__=='__main__':
    random.seed(5)
    items=[]
    for i in range(60000):
        k=random.random()
        if k<0.5:
            b=random.getrandbits(64); x=struct.unpack('<d',struct.pack('<Q',b))[0]
            if x!=x or abs(x)==math.inf: continue
        elif k<0.7:
            x=random.randint(1,10**random.randint(1,25))*random.choice([1,-1])*1.0
        elif k<0.85:
            x=round(random.uniform(-1000,1000),random.randint(0,8))
        else:
            x=random.random()*10**random.randint(-30,30)
        items.append(repr(x))
    out,err=jqbatch('.[]|.+0',items)
    bad=0
    for s,o in zip(items,out):
        m=jqfmt(float(s))
        if m!=o:
            bad+=1
            if bad<15: print('MISMATCH',s,o,m)
    print(len(items),'bad',bad, err[:100])
