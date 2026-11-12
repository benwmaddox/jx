import subprocess,sys,time,statistics,os
doc=sys.argv[1]; runs=int(sys.argv[2]); cmds=[c.split("|") for c in sys.argv[3:]]
res=[[] for _ in cmds]
for r in range(runs):
    for i,c in enumerate(cmds):
        with open(doc,"rb") as fi:
            t=time.perf_counter(); subprocess.run(c,stdin=fi,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL); res[i].append((time.perf_counter()-t)*1000)
for i,c in enumerate(cmds): print("%7.1f  %s"%(statistics.median(res[i]),"|".join(c)))
