#!/usr/bin/env python3
"""Times jx against jq, jaq and the old prototype on generated documents (Windows, whole process: start, read, filter, write).
usage: python -I bench/bench.py [--rows 5,20000] [--runs 15] [--big-runs 5]
Environment: JX (new executable), OLDJX (the prototype built from Mitochondria's examples/jx), DATA (scratch directory for the documents).
Documents: {"users":[{"n":"user%d","age":N,"tags":["a","b"],"addr":{"city":"c%d","zip":N}}, ...]}
Prints a markdown table of median milliseconds; before timing it checks that every tool prints the same bytes as jq."""
import argparse, os, statistics, subprocess, sys, time

ap = argparse.ArgumentParser()
ap.add_argument("--rows", default="5,20000")
ap.add_argument("--runs", type=int, default=15)
ap.add_argument("--big-runs", type=int, default=5)
ap.add_argument("--big", type=int, default=100000, help="documents with at least this many rows count as large (fewer runs)")
a = ap.parse_args()
JX = os.environ.get("JX", "D:/tmp/w/jx/b/jx.exe")
OLD = os.environ.get("OLDJX", "D:/tmp/w/jx/b/oldjx.exe")
DATA = os.environ.get("DATA", "D:/tmp/w/jx/data")
os.makedirs(DATA, exist_ok=True)
FILTERS = [".users[0].n", ".users | length", ".users[] | select(.age >= 85) | .n", ".users[] | .addr.city"]
TOOLS = [("jx", [JX, "-c"]), ("old jx", [OLD, "-c"]), ("jq", ["jq", "-c"]), ("jaq", ["jaq", "-c"])]

def make(rows):
    path = "%s/users%d.json" % (DATA, rows)
    if not os.path.exists(path):
        body = ",".join('{"n":"user%d","age":%d,"tags":["a","b"],"addr":{"city":"c%d","zip":%d}}' % (i, i % 100, i, i * 3 % 100000) for i in range(rows))
        with open(path, "w") as f: f.write('{"users":[' + body + ']}\n')
    return path

def run(cmd, path):
    with open(path, "rb") as f:
        t = time.perf_counter()
        p = subprocess.run(cmd, stdin=f, capture_output=True)
        return (time.perf_counter() - t) * 1000, p

print("| rows | size | filter | " + " | ".join(n for n, _ in TOOLS) + " |")
print("| --- | --- | --- | " + " | ".join("---" for _ in TOOLS) + " |")
for rows in [int(x) for x in a.rows.split(",")]:
    path = make(rows)
    size = os.path.getsize(path)
    runs = a.big_runs if rows >= a.big else a.runs
    for filt in FILTERS:
        _, ref = run(["jq", "-c", filt], path)
        want = ref.stdout.replace(b"\r\n", b"\n")
        cells = []
        for name, cmd in TOOLS:
            _, p = run(cmd + [filt], path)
            if p.returncode != 0 or p.stdout.replace(b"\r\n", b"\n") != want:
                cells.append("n/a" if p.returncode != 0 else "DIFF")
                continue
            ts = [run(cmd + [filt], path)[0] for _ in range(runs)]
            cells.append("%.0f" % statistics.median(ts))
        print("| %d | %.2f MB | `%s` | %s |" % (rows, size / 1e6, filt, " | ".join(cells)))
        sys.stdout.flush()
