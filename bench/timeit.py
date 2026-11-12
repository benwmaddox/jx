# usage: python -I timeit.py RUNS INPUT_FILE CMD [ARGS...]   -> median ms of running CMD with INPUT_FILE on stdin
import subprocess, sys, time, statistics
runs = int(sys.argv[1]); inp = sys.argv[2]; cmd = sys.argv[3:]
ts = []
for _ in range(runs):
    with open(inp, 'rb') as f:
        t = time.perf_counter()
        subprocess.run(cmd, stdin=f, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        ts.append((time.perf_counter() - t) * 1000)
print("%.1f" % statistics.median(ts))
