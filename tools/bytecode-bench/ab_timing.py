"""A/B timing of builds: python ab_timing.py DOC RUNS EXE1,EXE2,... FILTER...   (alternating runs, median ms per exe and filter, output to NUL)"""
import subprocess, sys, time, statistics, os
doc, runs, exes, fs = sys.argv[1], int(sys.argv[2]), sys.argv[3].split(","), sys.argv[4:]
res = {(f, e): [] for f in fs for e in exes}
for r in range(runs):
    for f in fs:
        for e in exes:
            with open(doc, "rb") as fi, open(os.devnull, "wb") as fo:
                t = time.perf_counter(); p = subprocess.run([e, "-c", f], stdin=fi, stdout=fo, stderr=subprocess.PIPE); res[(f, e)].append((time.perf_counter() - t) * 1000)
            if p.returncode: print("ERR", f, p.stderr[:80])
for f in fs: print("  ".join("%7.1f" % statistics.median(res[(f, e)]) for e in exes), " ", f)
