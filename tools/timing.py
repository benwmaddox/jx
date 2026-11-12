#!/usr/bin/env python3
"""Times one jx build against jq and jaq and stores median milliseconds and peak working set (MB) as tools/results/DATE-LABEL-timing.json.
usage: python -I tools/timing.py --jx EXE --label stageN [--jx-repo DIR] [--rows 20000,200000] [--data DIR] [--runs N] [--quick]
The documents (generated here: 1.59 MB at 20000 rows and 16.3 MB at 200000 rows, same shape as bench/bench.py) go under --data, never into the repo.
Each run is one whole process (start, read stdin, filter, write stdout to a pipe) on Windows; the peak is the process's PeakWorkingSetSize
read from its handle (the real jq.exe is used, because the `jq` on PATH is a launcher shim that hides the memory).
The reference tools are measured again in every run on the same machine, so each stage's row is comparable on its own.
--quick: 5 runs on the 16.3 MB document only (the milestone runs). A filter whose output differs from jq's is reported as DIFF, a failing one as n/a."""
import argparse, ctypes, ctypes.wintypes as wt, datetime, json, os, statistics, subprocess, sys, time

HERE = os.path.dirname(os.path.abspath(__file__))
JQ = r"C:\ProgramData\chocolatey\lib\jq\tools\jq.exe"
STANDARD = [".users[0].n", ".users | length", ".users[] | select(.age >= 85) | .n", ".users[] | .addr.city"]
# one representative filter for every kind of work Stage 2 added
FEATURES = [".users[] | {n: .n, c: .addr.city}", ".users | map(.age) | add", "[.users[] | select(.age >= 85) | .n] | length",
            "[.users[] | try (.n | tonumber) catch 0] | length", ".users | length as $n | $n * 2", "[limit(3; .users[])] | length", ".users[] | .age + 1"]


class PMC(ctypes.Structure):
    _fields_ = [("cb", wt.DWORD), ("PageFaultCount", wt.DWORD), ("PeakWorkingSetSize", ctypes.c_size_t), ("WorkingSetSize", ctypes.c_size_t),
                ("QuotaPeakPagedPoolUsage", ctypes.c_size_t), ("QuotaPagedPoolUsage", ctypes.c_size_t), ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
                ("QuotaNonPagedPoolUsage", ctypes.c_size_t), ("PagefileUsage", ctypes.c_size_t), ("PeakPagefileUsage", ctypes.c_size_t)]


def peak_mb(handle):
    p = PMC(); p.cb = ctypes.sizeof(p)
    ctypes.windll.psapi.GetProcessMemoryInfo(wt.HANDLE(int(handle)), ctypes.byref(p), p.cb)
    return p.PeakWorkingSetSize / 1e6


def run(cmd, path):
    """(milliseconds, peak MB, returncode, stdout)"""
    with open(path, "rb") as f:
        t = time.perf_counter()
        p = subprocess.Popen(cmd, stdin=f, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        out, _ = p.communicate()
        ms = (time.perf_counter() - t) * 1000
        return ms, peak_mb(p._handle), p.returncode, out


def make(data, rows):
    path = os.path.join(data, "users%d.json" % rows)
    if not os.path.exists(path):
        body = ",".join('{"n":"user%d","age":%d,"tags":["a","b"],"addr":{"city":"c%d","zip":%d}}' % (i, i % 100, i, i * 3 % 100000) for i in range(rows))
        with open(path, "w") as f:
            f.write('{"users":[' + body + ']}\n')
    return path


def measure(tools, filters, path, runs):
    rows = []
    for filt in filters:
        _, _, _, ref = run([JQ, "-c", filt], path)
        want = ref.replace(b"\r\n", b"\n")
        ms, pk = {}, {}
        for name, cmd in tools:
            _, _, rc, out = run(cmd + [filt], path)
            if rc != 0:
                ms[name], pk[name] = "n/a", "n/a"
                continue
            if out.replace(b"\r\n", b"\n") != want:
                ms[name], pk[name] = "DIFF", "DIFF"
                continue
            res = [run(cmd + [filt], path)[:2] for _ in range(runs)]
            ms[name] = "%.0f" % statistics.median(r[0] for r in res)
            pk[name] = "%.0f" % max(r[1] for r in res)
        rows.append(dict(filter=filt, ms=ms, peak=pk))
    return rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--jx", required=True)
    ap.add_argument("--label", required=True)
    ap.add_argument("--jx-repo")
    ap.add_argument("--rows", default="20000,200000")
    ap.add_argument("--data", default=r"D:\tmp\w\jxprog-build\data")
    ap.add_argument("--runs", type=int, default=15)
    ap.add_argument("--big-runs", type=int, default=5)
    ap.add_argument("--quick", action="store_true")
    ap.add_argument("--date")
    ap.add_argument("--results", default=os.path.join(os.path.dirname(HERE), "tools", "results"))
    a = ap.parse_args()
    os.makedirs(a.data, exist_ok=True)
    tools = [("jx", [a.jx, "-c"]), ("jq", [JQ, "-c"]), ("jaq", ["jaq", "-c"])]
    sizes = [200000] if a.quick else [int(x) for x in a.rows.split(",")]
    runs = 5 if a.quick else a.runs
    out = []
    for rows in sizes:
        path = make(a.data, rows)
        size = "%.2f MB" % (os.path.getsize(path) / 1e6)
        for r in measure(tools, STANDARD + FEATURES, path, a.big_runs if rows >= 100000 and not a.quick else runs):
            out.append(dict(rows=rows, size=size, **r))
            print(rows, r["filter"], r["ms"], r["peak"], flush=True)
    commit = ""
    if a.jx_repo:
        commit = subprocess.run(["git", "-C", a.jx_repo, "rev-parse", "--short", "HEAD"], capture_output=True, text=True).stdout.strip()
    rec = dict(label=a.label, date=a.date or datetime.date.today().isoformat(), commit=commit,
               unit="median ms and peak working set MB, whole process, Windows", timing=out)
    os.makedirs(a.results, exist_ok=True)
    path = os.path.join(a.results, "%s-%s-timing.json" % (rec["date"], a.label))
    json.dump(rec, open(path, "w", encoding="utf-8", newline="\n"), indent=1)
    print("wrote", path, len(out), "rows")


main()
