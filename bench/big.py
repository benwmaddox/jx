#!/usr/bin/env python3
"""One run of each tool on a very large document (default D:\tmp\w\big500.json, 529 MB, 6.5 million rows; never regenerated here): seconds and peak working set.
usage: python -I bench/big.py JX.exe [--doc FILE]    (jq is the real jq.exe: the `jq` on PATH is a launcher shim that hides the memory)"""
import argparse, os, sys, subprocess, time
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "tools"))
ap = argparse.ArgumentParser()
ap.add_argument("jx"); ap.add_argument("--doc", default=r"D:\tmp\w\big500.json")
a = ap.parse_args()
import ctypes, ctypes.wintypes as wt
class PMC(ctypes.Structure):
    _fields_ = [("cb", wt.DWORD), ("PageFaultCount", wt.DWORD), ("PeakWorkingSetSize", ctypes.c_size_t), ("WorkingSetSize", ctypes.c_size_t),
                ("QuotaPeakPagedPoolUsage", ctypes.c_size_t), ("QuotaPagedPoolUsage", ctypes.c_size_t), ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
                ("QuotaNonPagedPoolUsage", ctypes.c_size_t), ("PagefileUsage", ctypes.c_size_t), ("PeakPagefileUsage", ctypes.c_size_t)]
def peak(h):
    p = PMC(); p.cb = ctypes.sizeof(p); ctypes.windll.psapi.GetProcessMemoryInfo(wt.HANDLE(int(h)), ctypes.byref(p), p.cb); return p.PeakWorkingSetSize / 1e6
JQ = r"C:\ProgramData\chocolatey\lib\jq\tools\jq.exe"
FILTERS = [".users[0].n", ".users | length", ".users[] | select(.age >= 85) | .n", ".users[] | .addr.city", ".users[] | {n: .n, c: .addr.city}",
           ".users | map(.age) | add", "[.users[] | select(.age >= 85) | .n] | length"]
print("| filter | jx s / MB | jq s / MB | jaq s / MB | output bytes (jx) |\n|---|---|---|---|---|")
for f in FILTERS:
    cells, size = [], ""
    for name, cmd in (("jx", [a.jx, "-c"]), ("jq", [JQ, "-c"]), ("jaq", ["jaq", "-c"])):
        out = os.path.join(os.environ.get("TEMP", "."), "big_%s.out" % name)
        t = time.perf_counter()
        with open(a.doc, "rb") as fi, open(out, "wb") as fo:
            p = subprocess.Popen(cmd + [f], stdin=fi, stdout=fo, stderr=subprocess.PIPE)
            _, err = p.communicate(timeout=1800)
            dt = time.perf_counter() - t
            pk = peak(p._handle)
        if name == "jx": size = os.path.getsize(out)
        cells.append("%.1f / %.0f" % (dt, pk) if p.returncode == 0 else "failed rc=%d %s" % (p.returncode, err[:50].decode(errors="replace")))
        os.remove(out)
    print("| `%s` | %s | %d |" % (f, " | ".join(cells), size), flush=True)
