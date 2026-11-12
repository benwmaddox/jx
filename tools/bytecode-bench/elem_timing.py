import subprocess,sys,time,statistics,os
exe=sys.argv[1]; doc=sys.argv[2]; runs=int(sys.argv[3]); sink=sys.argv[4]; fs=sys.argv[5:]
res={f:[] for f in fs}
for r in range(runs):
    for f in fs:
        with open(doc,"rb") as fi, open(os.devnull if sink=="nul" else "out.tmp","wb") as fo:
            t=time.perf_counter(); p=subprocess.run([exe,"-c",f],stdin=fi,stdout=fo,stderr=subprocess.PIPE); res[f].append((time.perf_counter()-t)*1000)
        if p.returncode: print("ERR",f,p.stderr[:80])
for f in fs: print("%8.1f  %s"%(statistics.median(res[f]),f))
