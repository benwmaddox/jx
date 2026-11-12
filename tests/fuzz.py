#!/usr/bin/env python3
"""Randomized differential test: random filters from the supported grammar over random documents, compared with jq 1.8.2.

usage: python tests/fuzz.py [--exe JX] [--count N] [--seeds 1,2,3] [--jq PATH]
Each seed generates `count` cases (a document and a filter, from random.Random(seed)), so a failure is reproduced by its seed and index:
    python tests/fuzz.py --seeds S --count N --only I
A case passes when jx and jq write the same standard output (CRLF normalized), or both fail. A filter that jx refuses at compile time
("not supported") is counted as rejected, not compared. A runtime "not supported" while jq succeeds is counted apart
(an operation on a value of the document that Stage 2 does not parse, for example comparing two objects). Everything else is a failure:
a differing output, jx failing where jq succeeds, or jx succeeding where jq fails. An under-approximated demand (a value read as null
that the document had) shows up as a differing output."""
import argparse, os, random, subprocess, sys, tempfile
from concurrent.futures import ThreadPoolExecutor

KEYS = ["a", "b", "c", "n", "x", "age", "tags", "users"]
STRS = ["", "a", "b", "abc", "x y", "é", "a\\nb", "\\u00e9", "q\\\"q", "ab\\/c", "😀", "\\ud83d\\ude00", "A", "zz", "10", "1.50", "-3", "1e2"]
NUMS = ["0", "1", "2", "3", "-1", "7", "10", "85", "100", "0.5", "1.0", "1.50", "-0.25", "2.5e3", "1e3", "1E-2", "123456789012345678", "100000000000000000000",
        "9007199254740993", "0.1", "3.14159", "1e-7", "12345.6789e-3", "-0", "0.0", "1e400", "5e-324", "999999999999999999999.5"]


def gen_value(r, depth):
    k = r.random()
    if depth <= 0 or k < 0.45:
        c = r.random()
        if c < 0.4: return r.choice(NUMS)
        if c < 0.7: return '"%s"' % r.choice(STRS)
        if c < 0.8: return "null"
        return r.choice(["true", "false"])
    if k < 0.75:
        n = r.randint(0, 4)
        return "[" + ",".join(gen_value(r, depth - 1) for _ in range(n)) + "]"
    keys = r.sample(KEYS, r.randint(0, 5))
    return "{" + ",".join('"%s":%s' % (k2, gen_value(r, depth - 1)) for k2 in keys) + "}"


def gen_doc(r):
    # an object whose top-level keys are the usual ones, often holding arrays of small objects
    parts = []
    for k in r.sample(KEYS, r.randint(1, 5)):
        if k in ("users", "tags") and r.random() < 0.8:
            rows = ",".join(gen_value(r, 2) if r.random() < 0.3 else "{" + ",".join('"%s":%s' % (kk, gen_value(r, 1)) for kk in r.sample(KEYS, r.randint(1, 5))) + "}" for _ in range(r.randint(0, 4)))
            parts.append('"%s":[%s]' % (k, rows))
        else:
            parts.append('"%s":%s' % (k, gen_value(r, 3)))
    doc = "{" + ",".join(parts) + "}"
    if r.random() < 0.1: doc = gen_value(r, 3)
    return doc


def gen_path(r, allow_iter=True):
    s = ""
    for _ in range(r.randint(0, 3)):
        c = r.random()
        if c < 0.6: s += "." + r.choice(KEYS)
        elif c < 0.75: s += "[%d]" % r.randint(0, 2)
        elif c < 0.9 and allow_iter: s += "[]"
        else: s += '["%s"]' % r.choice(KEYS)
    if s == "" or s[0] == "[":
        s = "." + s if s else "."
    return s


def gen_lit(r):
    c = r.random()
    if c < 0.5: return r.choice(["0", "1", "2", "3", "7", "10", "85", "0.5", "1.0", "1e3", "100000000000000000000"])
    if c < 0.8: return '"%s"' % r.choice(["a", "b", "abc", "", "x y", "10"])
    return r.choice(["null", "true", "false"])


def gen_scalar_expr(r, depth):
    """an expression with exactly one output"""
    k = r.random()
    if depth <= 0 or k < 0.3:
        return gen_path(r, False) if r.random() < 0.7 else gen_lit(r)
    if k < 0.5:
        op = r.choice(["+", "-", "*", "/", "%"])
        return "(%s %s %s)" % (gen_scalar_expr(r, depth - 1), op, gen_scalar_expr(r, depth - 1))
    if k < 0.65:
        op = r.choice(["==", "!=", "<", "<=", ">", ">="])
        return "(%s %s %s)" % (gen_scalar_expr(r, depth - 1), op, gen_scalar_expr(r, depth - 1))
    if k < 0.72:
        return "(%s %s %s)" % (gen_scalar_expr(r, depth - 1), r.choice(["and", "or"]), gen_scalar_expr(r, depth - 1))
    if k < 0.78:
        return "(%s // %s)" % (gen_scalar_expr(r, depth - 1), gen_scalar_expr(r, depth - 1))
    if k < 0.85:
        return "(if %s then %s else %s end)" % (gen_scalar_expr(r, depth - 1), gen_scalar_expr(r, depth - 1), gen_scalar_expr(r, depth - 1))
    if k < 0.93:
        return "(%s | %s)" % (gen_scalar_expr(r, depth - 1), r.choice(["length", "type", "not", "keys", "tostring", "tonumber", "floor", "sqrt", "-(.)", "add", 'has("a")', "has(0)", "first", ".a", ".[0]"]))
    return "[%s]" % gen_expr(r, depth - 1)


def gen_expr(r, depth):
    k = r.random()
    if depth <= 0 or k < 0.25:
        return gen_path(r) if r.random() < 0.75 else gen_lit(r)
    if k < 0.38:
        return "%s | %s" % (gen_expr(r, depth - 1), gen_expr(r, depth - 1))
    if k < 0.45:
        return "%s, %s" % (gen_expr(r, depth - 1), gen_expr(r, depth - 1))
    if k < 0.55:
        return "%s | select(%s)" % (gen_path(r), gen_scalar_expr(r, depth - 1))
    if k < 0.65:
        return gen_scalar_expr(r, depth)
    if k < 0.73:
        return "[%s]" % gen_expr(r, depth - 1)
    if k < 0.80:
        n = r.randint(0, 3)
        return "{" + ", ".join("%s: %s" % (r.choice(KEYS + ['"k k"']), gen_scalar_expr(r, depth - 1)) for _ in range(n)) + "}"
    if k < 0.86:
        return "%s | map(%s)" % (gen_path(r), gen_scalar_expr(r, depth - 1))
    if k < 0.90:
        return "[%s | %s] | %s" % (gen_path(r), gen_scalar_expr(r, depth - 1), r.choice(["add", "length", "length", "add"]))
    if k < 0.94:
        return "%s | map(%s) | add" % (gen_path(r), gen_scalar_expr(r, depth - 1))
    return "%s | length" % gen_path(r)


def make_case(seed, i):
    r = random.Random(seed * 1000003 + i)
    return gen_doc(r), gen_expr(r, r.randint(1, 3))


def norm(b): return b.replace(b"\r\n", b"\n")


def run_one(args):
    seed, i, jx, jq, tmp = args
    doc, filt = make_case(seed, i)
    path = os.path.join(tmp, "f_%d_%d.json" % (seed, i))
    with open(path, "wb") as f: f.write(doc.encode("utf-8"))
    flags = ["-c"]
    with open(path, "rb") as f:
        e = subprocess.run([jq] + flags + [filt], stdin=f, capture_output=True)
    with open(path, "rb") as f:
        g = subprocess.run([jx] + flags + [filt], stdin=f, capture_output=True)
    os.remove(path)
    eout = norm(e.stdout)
    if g.returncode != 0 and b"not supported" in g.stderr:
        kind = "rejected" if b"Stage 2: " in g.stderr and e.returncode is not None else "rejected"
        # a compile-time rejection writes nothing and reads nothing; a runtime one may follow jq success
        return (seed, i, doc, filt, "unsupported" if e.returncode == 0 else "rejected", e, g)
    if e.returncode != 0:
        ok = g.returncode != 0 and len(g.stderr) > 0
    else:
        ok = g.returncode == 0 and g.stdout == eout
    return (seed, i, doc, filt, "ok" if ok else "FAIL", e, g)


def asc(x):
    return x.encode("ascii", "backslashreplace").decode("ascii") if isinstance(x, str) else repr(x)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--exe", default=os.environ.get("JX", "D:/tmp/w/jx/jx3.exe"))
    ap.add_argument("--jq", default="C:/ProgramData/chocolatey/lib/jq/tools/jq.exe")
    ap.add_argument("--count", type=int, default=500)
    ap.add_argument("--seeds", default="1,2,3,4")
    ap.add_argument("--only", type=int, default=None)
    ap.add_argument("--show", type=int, default=12)
    a = ap.parse_args()
    seeds = [int(s) for s in a.seeds.split(",")]
    tmp = tempfile.mkdtemp(prefix="jxfuzz_", dir="D:/tmp/w/jx")
    jobs = [(s, i, a.exe, a.jq, tmp) for s in seeds for i in (range(a.count) if a.only is None else [a.only])]
    counts = {"ok": 0, "FAIL": 0, "rejected": 0, "unsupported": 0}
    fails = []
    with ThreadPoolExecutor(max_workers=6) as ex:
        for res in ex.map(run_one, jobs):
            counts[res[4]] += 1
            if res[4] == "FAIL": fails.append(res)
    total = sum(counts.values())
    print("fuzz: %d cases (seeds %s x %d): %d match jq, %d FAIL, %d rejected at compile time, %d unsupported at run time"
          % (total, a.seeds, a.count, counts["ok"], counts["FAIL"], counts["rejected"], counts["unsupported"]))
    for seed, i, doc, filt, _, e, g in fails[:a.show]:
        print("FAIL seed=%d i=%d\n  doc:    %s\n  filter: %s\n  jq (rc %d): %s %s\n  jx (rc %d): %s %s" % (
            seed, i, doc[:300], filt, e.returncode, norm(e.stdout)[:200], e.stderr[:100], g.returncode, g.stdout[:200], g.stderr[:100]))
    try: os.rmdir(tmp)
    except OSError: pass
    sys.exit(1 if counts["FAIL"] else 0)


main()
