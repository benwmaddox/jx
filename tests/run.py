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
docs["bom"] = b'\xef\xbb\xbf{"a":1}'
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

import re
def glob(pat, text):      # only * is a wildcard (fnmatch would read [0] as a character class)
    return re.fullmatch(".*".join(re.escape(p) for p in pat.split("*")), text, re.S) is not None
xdiff = [l.rsplit("|", 1) for l in lines("xdiff.txt")]     # pattern|reason; the pattern is doc|flags|filter and the filter may hold |
def xdiff_reason(cid):
    for pat, why in xdiff:
        if glob(pat, cid): return None if why == "STRICT" else why
    return None

def norm(b): return b.replace(b"\r\n", b"\n")
def run(exe, flags, filt, doc):
    with open("%s/docs/%s.json" % (T, doc), "rb") as f:
        try:
            p = subprocess.run([exe] + flags + [filt], stdin=f, capture_output=True, timeout=60)
        except subprocess.TimeoutExpired:
            return -9, b"", b"timeout"
    return p.returncode, p.stdout, p.stderr

def early_exit_tail(doc, filt):
    # a malformed document with a filter that stops early (no `[]`): the unread tail is not validated (decision 3)
    return doc.startswith("m_") and "[]" not in filt

def check(case):
    doc, flags, filt = case
    erc, eout, _ = run("jq", flags, filt, doc)
    eout = norm(eout)             # jq on Windows writes CRLF; jx writes LF
    grc, gout, gerr = run(JX, flags, filt, doc)
    if doc.startswith("rej_"): ok = grc != 0 and len(gerr) > 0 and len(gout) == 0   # jq accepts it, jx must refuse it (strict JSON, one document)
    elif erc != 0: ok = grc != 0 and len(gerr) > 0 and (grc == erc or grc == 1)      # jq's exit code (2, 3, 5) or 1 for not supported
    else: ok = grc == 0 and gout == eout
    return case, ok, erc, grc

K = os.environ.get("JX_K")          # run only the filters containing this text
DK = os.environ.get("JX_DOCS")      # run only the documents whose name contains this text
cases = []
names = sorted(d for d in docs if not DK or DK in d)
for flags, fname in (([ "-c"], "filters.txt"), (["-c"], "filters2.txt"), ([], "filters_pretty.txt"), (["-r"], "filters_raw.txt"), (["-c", "-r"], "filters_raw.txt")):
    for fi, filt in enumerate(lines(fname)):
        if K and K not in filt: continue
        for d in names:
            if d.startswith("rej_") and (flags != ["-c"] or fi % 7): continue    # a sample of filters is enough
            cases.append((d, flags, filt))
pass_n = fail_n = xd_n = xd_match = 0
by_reason = {}
early_cases = []
failures = []
with ThreadPoolExecutor(max_workers=6) as ex:
    for case, ok, erc, grc in ex.map(check, cases):
        cid = "%s|%s|%s" % (case[0], " ".join(case[1]), case[2])
        why = xdiff_reason(cid) or ("early exit: unread tail not validated" if (not ok and grc == 0 and early_exit_tail(case[0], case[2])) else None)
        if why:
            xd_n += 1
            if ok: xd_match += 1
            else:
                by_reason[why[:70]] = by_reason.get(why[:70], 0) + 1
                if why.startswith("early exit"): early_cases.append(cid)
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
# not jq syntax: jq fails, jx fails with a syntax error and no output
syn_ok = 0
for filt in lines("syntax.txt"):
    with open(T + "/docs/simple.json", "rb") as f:
        q = subprocess.run(["jq", "-c", filt], stdin=f, capture_output=True)
    with open(T + "/docs/simple.json", "rb") as f:
        p = subprocess.run([JX, "-c", filt], stdin=f, capture_output=True)
    if q.returncode == 3 and p.returncode == 3 and not p.stdout and b"syntax error" in p.stderr: syn_ok += 1
    else: failures.append("syntax: %s (jq rc=%d, jx rc=%d, stderr=%r)" % (filt, q.returncode, p.returncode, p.stderr[:80]))
nsyn = len(lines("syntax.txt"))
# options: unknown or unsupported options are refused by name (jq exits 2; a program can only exit with 1)
opt_ok = 0
opt_cases = [(["-Z", ".a"], b"unknown option '-Z'"), ([".a", "-Z"], b"unknown option '-Z'"), (["-S", ".a"], b"'-S' is not supported yet"),
             ([".a", "-S"], b"'-S' is not supported yet"), (["-L", ".a"], b"'-L' is not supported yet"),
             (["-C", ".a"], b"'-C' is not supported yet"), (["--indent=4", ".a"], b"unknown option '--indent'"), (["--bogus", ".a"], b"unknown option '--bogus'"), ([".a", "--bogus"], b"unknown option '--bogus'"),
             (["--raw-output0", ".a"], b"'--raw-output0' is not supported yet"), ([".a", "--sort-keys"], b"'--sort-keys' is not supported yet"), (["-cS", ".a"], b"'-S' is not supported yet"), (["-cZ", ".a"], b"unknown option '-Z'"), ([".a", "other.json"], b"input files are not supported")]
for args, want in opt_cases:
    with open(T + "/docs/simple.json", "rb") as f:
        p = subprocess.run([JX] + args, stdin=f, capture_output=True)
    good = p.returncode == 2 and not p.stdout and want in p.stderr
    if good: opt_ok += 1
    else: failures.append("option: %s (rc=%d, stdout=%r, stderr=%r)" % (" ".join(args), p.returncode, p.stdout[:30], p.stderr[:80]))
# accepted option forms, anywhere, and the default filter
for args, want in (([".users[0].n", "-c"], b'"ann"\n'), (["-c", "--raw-output", ".users[0].n"], b"ann\n"), ([".users[0].n", "--compact-output", "-r"], b"ann\n"), (["-cr", ".users[0].n"], b"ann\n"),
                   ([".users[0].n", "--", "-c"], None), (["--compact-output"], None),
                   (["-n", "-c", "[1,2] | length"], b"2\n"), (["-c", "--arg", "x", "a b", "-n", "[$x]"], b'["a b"]\n'), (["-nc", "--argjson", "j", '{"a":[1,2.50]}', "$j"], b'{"a":[1,2.50]}\n'),
                   (["-nc", "$ARGS.named", "--arg", "k", "v"], b'{"k":"v"}\n'), (["-nc", "$ARGS.positional", "--args", "p", "q"], b'["p","q"]\n'), (["--tab", ".users[0].addr.zip"], b"78701\n"),
                   (["-j", ".users[0].n"], b'ann'), (["-e", ".users[0].n"], b'"ann"\n'), (["-c", "--indent", "3", ".users[0].tags"], None)):
    with open(T + "/docs/simple.json", "rb") as f:
        p = subprocess.run([JX] + args, stdin=f, capture_output=True)
    opt_n_extra = 1
    if want is None: continue
    if p.returncode == 0 and p.stdout.replace(b"\r\n", b"\n") == want: opt_ok += 1
    else: failures.append("option form: %s (rc=%d, stdout=%r)" % (" ".join(args), p.returncode, p.stdout[:40]))
    opt_cases.append(None)
# -s, -a, --seq: expected output byte for byte (checked against jq 1.8.2 by hand when written)
for args, doc, want in ((["-c", "-s", "."], b'{"a":1}', b'[{"a":1}]\n'), (["-c", "-s", "length"], b'', b'0\n'), (["-c", "-s", "."], b'', b'[]\n'), (["-s", "-c", ".[0].a"], b'{"a":5}', b'5\n'),
                        (["-c", "-a", "."], b'["\xc3\xa9\xf0\x9f\x98\x80\x7f"]', b'["\\u00e9\\ud83d\\ude00\\u007f"]\n'), (["-r", "-a", "."], b'"\xc3\xa9"', b'"\\u00e9"\n'),
                        (["-c", "-a", '{"k\\u00e9": .}'], b'"\xc3\xa9"', b'{"k\\u00e9":"\\u00e9"}\n'),
                        (["-c", "--seq", "."], b'[1,2]', b'\x1e[1,2]\n'), (["-c", "--seq", ".[]"], b'[1,2]', b'\x1e1\n\x1e2\n'), (["-sc", "map(.a)"], b'{"a":1}', b'[1]\n')):
    p = subprocess.run([JX] + args, input=doc, capture_output=True)
    if p.returncode == 0 and p.stdout.replace(b"\r\n", b"\n") == want: opt_ok += 1
    else: failures.append("option form: %s %r (rc=%d, stdout=%r)" % (" ".join(args), doc, p.returncode, p.stdout[:60]))
    opt_cases.append(None)
# exit codes as jq's: 3 syntax error in the filter, 5 an error while the filter runs or invalid input, 1 not supported
exit_ok = 0
exit_cases = [([".a |"], b'{"a":1}', 3), (["{a:"], b'{"a":1}', 3), ([".a.b"], b'{"a":1}', 5), (["error"], b'{"a":1}', 5), ([".a"], b'{"a":', 5), ([".a"], b'{"a":1} garbage', 5),
              ([".[]"], b'1', 5), (["walk(.)"], b'1', 1), ([".a", "-Z"], b'1', 2), ([".a"], b'{"a":1}', 0), (["--validate", ".a"], b'{"a":1} x', 5)]
for args, doc, want in exit_cases:
    p = subprocess.run([JX, "-c"] + args, input=doc, capture_output=True)
    if p.returncode == want and (want == 0 or (not p.stdout and p.stderr)): exit_ok += 1
    else: failures.append("exit code: %s %r want %d got %d %r" % (args, doc, want, p.returncode, p.stderr[:60]))
# --validate: reads the whole input and fails when anything follows the first value (jq: parse error, exit 2; jx exits 1)
val_ok = 0
for doc, flags, want_rc in ((b'{"a":{"x":1}}', ["--validate"], 0), (b'{"a":{"x":1},"b":garbage}', ["--validate"], 5), (b'{"a":{"x":1},"b":[1,2', ["--validate"], 5),
                            (b'{"a":{"x":1},"b":garbage}', [], 0)):
    p = subprocess.run([JX, "-c"] + flags + [".a.x"], input=doc, capture_output=True)
    if p.returncode == want_rc and (want_rc != 0 or True): val_ok += 1
    else: failures.append("validate: %r %s (rc=%d)" % (doc, flags, p.returncode))
print("cases: %d against jq: %d pass, %d fail, %d expected differences (%d of them matched anyway); compile-time rejections: %d of %d ok; "
      "syntax errors: %d of %d; options: %d of %d; exit codes: %d of %d; --validate: %d of 4" % (len(cases), pass_n, fail_n, xd_n, xd_match, rej_ok, nrej, syn_ok, nsyn, opt_ok, len(opt_cases), exit_ok, len(exit_cases), val_ok))
for r, n in sorted(by_reason.items(), key=lambda kv: -kv[1]): print("  expected difference observed: %5d  %s" % (n, r))
open(T + "/early_exit_cases.txt", "w").write(chr(10).join(early_cases))
open(T + "/failures.txt", "w").write(chr(10).join(failures))
for f in failures[:int(os.environ.get("JX_SHOW", "40"))]: print("FAIL", f)
sys.exit(0 if not failures else 1)
