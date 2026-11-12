#!/usr/bin/env python3
"""Runs the corpus: every filter in tests/filters.txt over every document (tests/docs.txt, tests/bad.txt and the generated ones),
through jq (1.8.2) and through jx, and compares stdout byte for byte (CRLF normalized).
A case jq answers with an error passes when jx also fails with a message on stderr (the exit codes differ: jq 2/3/5, jx 1, and jx
writes no partial output). Cases matching a line of tests/xdiff.txt are expected differences (README.md, "Differences from jq"):
counted apart, never a failure.
usage: python tests/run.py [path-to-jx-exe]   (JX_TMP: scratch directory, default D:/tmp/w/jx/t)"""
import fnmatch, os, subprocess, sys
from concurrent.futures import ThreadPoolExecutor

HERE = os.path.dirname(os.path.abspath(__file__))
JX = sys.argv[1] if len(sys.argv) > 1 else os.environ.get("JX", "D:/tmp/w/jx/b/jx.exe")
T = os.environ.get("JX_TMP", "D:/tmp/w/jx/t")
os.makedirs(T + "/docs", exist_ok=True)

def split_docs(path):
    name, buf = None, []
    docs = {}
    for line in open(path, encoding="utf-8").read().split("\n"):
        if line.startswith("### "):
            if name: docs[name] = "\n".join(buf) + "\n"
            name, buf = line[4:], []
        elif name is not None:
            buf.append(line)
    if name: docs[name] = "\n".join(buf).rstrip("\n") + "\n"
    return docs

docs = {}
for f in ("docs.txt", "bad.txt"):
    for k, v in split_docs(os.path.join(HERE, f)).items(): docs[k] = v.encode("utf-8")
docs["crlf"] = b'{"users":[{"n":"a","age":90},\r\n{"n":"b","age":10}],\r\n"k":1}\r\n'
docs["nonl"] = b'{"users":[{"n":"a","age":90},{"n":"b","age":10}],"k":1}'
docs["empty_input"] = b''
docs["blank_input"] = b'  \n\t \n'
docs["m_raw_tab"] = b'{"a":"x\ty"}'
docs["jqok_invalid_utf8"] = b'{"a":"x\xffy","users":[{"n":"b\xc3","age":1}]}'
docs["jqok_bom"] = b'\xef\xbb\xbf{"a":1}'
docs["deep9999"] = b"[" * 9999 + b"1" + b"]" * 9999 + b"\n"
docs["m_deep10001"] = b"[" * 10001 + b"1" + b"]" * 10001 + b"\n"
rows = ",".join('{"n":"user%d","age":%d,"tags":["a","b"],"addr":{"city":"c%d","zip":%d}}' % (i, i % 100, i, i * 7) for i in range(300))
docs["many"] = ('{"users":[%s],"k":1}\n' % rows).encode()
# early exit: the unread tail is not validated (decision 3); an outer repeat after the exit point is not seen (decision 2)
docs["jqok_tail_truncated"] = b'{"users":[{"n":"a","age":90},{"n":"b"'
docs["jqok_outer_dup"] = b'{"users":[{"n":"a"}],"users":[{"n":"b"}]}'
docs["jqok_tail_garbage"] = b'{"users":[{"n":"a"}],"x":}'
for k, v in docs.items():
    with open("%s/docs/%s.json" % (T, k), "wb") as f: f.write(v)

def lines(name):
    return [l for l in open(os.path.join(HERE, name), encoding="utf-8").read().split("\n") if l and not l.startswith("#")]

xdiff = [l.split("|", 3) for l in lines("xdiff.txt")]
def xdiff_reason(cid):
    for d, fl, fi, why in xdiff:
        if fnmatch.fnmatchcase(cid, "%s|%s|%s" % (d, fl, fi)): return None if why == "STRICT" else why
    return None

def norm(b): return b.replace(b"\r\n", b"\n")
def run(exe, flags, filt, doc):
    with open("%s/docs/%s.json" % (T, doc), "rb") as f:
        p = subprocess.run([exe] + flags + [filt], stdin=f, capture_output=True)
    return p.returncode, p.stdout, p.stderr

def early_exit_tail(doc, filt):
    # a malformed document with a filter that stops early (no `[]`): the unread tail is not validated (decision 3)
    return doc.startswith("m_") and "[]" not in filt

def check(case):
    doc, flags, filt = case
    erc, eout, _ = run("jq", flags, filt, doc)
    eout = norm(eout)             # jq on Windows writes CRLF; jx writes LF
    grc, gout, gerr = run(JX, flags, filt, doc)
    if erc != 0: ok = grc != 0 and len(gerr) > 0
    else: ok = grc == 0 and gout == eout
    return case, ok, erc, grc

K = os.environ.get("JX_K")          # run only the filters containing this text
DK = os.environ.get("JX_DOCS")      # run only the documents whose name contains this text
cases = []
names = sorted(d for d in docs if not DK or DK in d)
for flags, fname in (([ "-c"], "filters.txt"), ([], "filters_pretty.txt"), (["-r"], "filters_raw.txt"), (["-c", "-r"], "filters_raw.txt")):
    for filt in lines(fname):
        if K and K not in filt: continue
        for d in names: cases.append((d, flags, filt))
pass_n = fail_n = xd_n = xd_match = 0
by_reason = {}
failures = []
with ThreadPoolExecutor(max_workers=6) as ex:
    for case, ok, erc, grc in ex.map(check, cases):
        cid = "%s|%s|%s" % (case[0], " ".join(case[1]), case[2])
        why = xdiff_reason(cid) or ("early exit: unread tail not validated" if (not ok and grc == 0 and early_exit_tail(case[0], case[2])) else None)
        if why:
            xd_n += 1
            if ok: xd_match += 1
            else: by_reason[why[:70]] = by_reason.get(why[:70], 0) + 1
        elif ok: pass_n += 1
        else:
            fail_n += 1
            failures.append("%s  (jq rc=%d, jx rc=%d)" % (cid, erc, grc))
# rejected at compile time: exit code 1, "not supported" on stderr, nothing on stdout
rej_ok = 0
for filt in lines("reject.txt"):
    with open(T + "/docs/simple.json", "rb") as f:
        p = subprocess.run([JX, "-c", filt], stdin=f, capture_output=True)
    if p.returncode == 1 and not p.stdout and b"not supported" in p.stderr: rej_ok += 1
    else: failures.append("reject: %s (rc=%d, stderr=%r)" % (filt, p.returncode, p.stderr[:80]))
nrej = len(lines("reject.txt"))
print("cases: %d against jq: %d pass, %d fail, %d expected differences (%d of them matched anyway); compile-time rejections: %d of %d ok"
      % (len(cases), pass_n, fail_n, xd_n, xd_match, rej_ok, nrej))
for r, n in sorted(by_reason.items(), key=lambda kv: -kv[1]): print("  expected difference observed: %5d  %s" % (n, r))
open(T + "/failures.txt", "w").write(chr(10).join(failures))
for f in failures[:int(os.environ.get("JX_SHOW", "40"))]: print("FAIL", f)
sys.exit(0 if not failures else 1)
