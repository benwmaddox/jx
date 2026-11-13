#!/usr/bin/env python3
"""Differential run of the two engines (docs/bytecode-design.md, section 6): the same corpus and fuzz cases through a tree build and a
bytecode build of jx (Lim.ENGINE 0 and 1 of one source tree), comparing standard output, standard error and exit code. No jq needed.
A case the bytecode build refuses with "bytecode: not lowered yet" is counted apart (and must be a case the tree build runs); every
other difference is a failure.
usage: python tests/bcdiff.py TREE_EXE BYTECODE_EXE [--fuzz-seeds 1,2 --fuzz-count 500] [--workers N] [--only corpus|fuzz|rej]
(JX_TMP: scratch directory, default D:/tmp/w/jxbc2/t; JX_K / JX_DOCS as tests/run.py)"""
import os, subprocess, sys, re, random
from concurrent.futures import ThreadPoolExecutor

HERE = os.path.dirname(os.path.abspath(__file__))
args = [a for a in sys.argv[1:] if not a.startswith("--")]
opts = {}
av = sys.argv[1:]
for i, a in enumerate(av):
    if a.startswith("--") and i + 1 < len(av): opts[a] = av[i + 1]
TREE, BC = args[0], args[1]
T = os.environ.get("JX_TMP", "D:/tmp/w/jxbc2/t")
WORKERS = int(opts.get("--workers", "10"))
ONLY = opts.get("--only", "")
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
docs["jqok_tail_truncated"] = b'{"users":[{"n":"a","age":90},{"n":"b"'
docs["jqok_outer_dup"] = b'{"users":[{"n":"a"}],"users":[{"n":"b"}]}'
docs["jqok_tail_garbage"] = b'{"users":[{"n":"a"}],"x":}'
for k, v in docs.items():
    with open("%s/docs/%s.json" % (T, k), "wb") as f: f.write(v)


def lines(name):
    return [l for l in open(os.path.join(HERE, name), encoding="utf-8").read().split("\n") if l and not l.startswith("#")]


def run(exe, flags, filt, path):
    with open(path, "rb") as f:
        try:
            p = subprocess.run([exe] + flags + [filt], stdin=f, capture_output=True, timeout=60)
        except subprocess.TimeoutExpired:
            return -9, b"", b"timeout"
    return p.returncode, p.stdout, p.stderr


def norm_err(b):
    return re.sub(rb'"line":\d+', b'"line":N', b)    # a runtime error of the Mitochondria runtime names a source line


def compare(case):
    label, flags, filt, path = case
    a = run(TREE, flags, filt, path)
    b = run(BC, flags, filt, path)
    if b[0] == 1 and b"bytecode: not lowered yet" in b[2]:
        return label, "nl", a, b, flags, filt, path
    same = a[0] == b[0] and a[1] == b[1] and norm_err(a[2]) == norm_err(b[2])
    return label, "same" if same else "DIFF", a, b, flags, filt, path


cases = []
if ONLY in ("", "corpus"):
    K = os.environ.get("JX_K")
    DK = os.environ.get("JX_DOCS")
    names = sorted(d for d in docs if not DK or DK in d)
    for flags, fname in ((["-c"], "filters.txt"), (["-c"], "filters2.txt"), ([], "filters_pretty.txt"), (["-r"], "filters_raw.txt"), (["-c", "-r"], "filters_raw.txt")):
        for fi, filt in enumerate(lines(fname)):
            if K and K not in filt: continue
            for d in names:
                if d.startswith("rej_") and (flags != ["-c"] or fi % 7): continue
                cases.append(("corpus", flags, filt, "%s/docs/%s.json" % (T, d)))
if ONLY in ("", "rej"):
    for fname in ("reject.txt", "syntax.txt"):
        for filt in lines(fname):
            cases.append((fname, ["-c"], filt, T + "/docs/simple.json"))
    for flags, filt in ((["--validate"], ".a.x"), ([], ".users[0].n"), (["-cr"], ".users[0].n"), (["-S"], ".a"), (["--bogus"], ".a"), ([], ".a |"), ([], "{a:")):
        cases.append(("options", flags, filt, T + "/docs/simple.json"))
if ONLY in ("", "fuzz") and "--fuzz-seeds" in opts:
    sys.path.insert(0, HERE)
    import fuzz
    for seed in [int(s) for s in opts["--fuzz-seeds"].split(",")]:
        for i in range(int(opts.get("--fuzz-count", "500"))):
            doc, filt = fuzz.make_case(seed, i)
            path = "%s/docs/fz_%d_%d.json" % (T, seed, i)
            with open(path, "wb") as f: f.write(doc.encode("utf-8") if isinstance(doc, str) else doc)
            cases.append(("fuzz", ["-c"], filt, path))

counts = {}
diffs = []
nl = {}
with ThreadPoolExecutor(max_workers=WORKERS) as ex:
    for label, res, a, b, flags, filt, path in ex.map(compare, cases):
        counts[(label, res)] = counts.get((label, res), 0) + 1
        if res == "DIFF": diffs.append((label, flags, filt, path, a, b))
        if res == "nl":
            m = re.search(rb"not lowered yet: ([^ (]*)", b[2])
            key = m.group(1).decode() if m else "?"
            nl[key] = nl.get(key, 0) + 1
tot = {}
for (label, res), n in counts.items():
    tot.setdefault(label, {})[res] = n
for label, d in sorted(tot.items()):
    print("%-12s compared %6d: %6d identical, %d DIFFERENT, %d not lowered yet" % (label, sum(d.values()), d.get("same", 0), d.get("DIFF", 0), d.get("nl", 0)))
for k, n in sorted(nl.items(), key=lambda kv: -kv[1])[:20]: print("  not lowered: %-30s %d cases" % (k, n))
open(T + "/bcdiff_failures.txt", "w").write("\n".join("%s|%s|%s|%s" % (d[0], " ".join(d[1]), d[2], d[3]) for d in diffs))
for label, flags, filt, path, a, b in diffs[:int(os.environ.get("JX_SHOW", "15"))]:
    print("DIFF [%s] %s %s  doc=%s\n  tree: rc=%d out=%r err=%r\n  bc:   rc=%d out=%r err=%r" % (label, " ".join(flags), filt, os.path.basename(path), a[0], a[1][:120], a[2][:120], b[0], b[1][:120], b[2][:120]))
sys.exit(1 if diffs else 0)
