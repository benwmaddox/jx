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
import sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='backslashreplace')
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
    if k < 0.88:
        return "(try %s catch %s)" % (gen_scalar_expr(r, depth - 1), gen_scalar_expr(r, depth - 1))
    if k < 0.90:
        return "(%s as $v | %s)" % (gen_scalar_expr(r, depth - 1), r.choice(["$v", "[$v, .]", "($v | type)", "$v"]))
    if k < 0.92:
        return "(%s | .[%s:%s])" % (gen_scalar_expr(r, depth - 1), r.choice(["", "1", "-1", "0"]), r.choice(["", "2", "-2", "1"]))
    if k < 0.93:
        return "(%s | %s)" % (gen_scalar_expr(r, depth - 1), r.choice(["length", "type", "not", "keys", "tostring", "tonumber", "-(.)", "add", 'has("a")', "has(0)", "first", ".a", ".[0]", "toboolean", "arrays", "values"]))
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
    if k < 0.92:
        return "%s | map(%s) | add" % (gen_path(r), gen_scalar_expr(r, depth - 1))
    if k < 0.94:
        return r.choice(["limit(2; %s)", "first(%s)", "[range(3)] | map(. + 1)", "%s | try error catch .", "[%s] | .[1:]", "(%s) as $x | [$x, $x]", "isempty(%s)", "[.[]?]", "[%s | numbers]"]).replace("%s", gen_path(r))
    return "%s | length" % gen_path(r)


S3_MATH = ["floor", "ceil", "round", "sqrt", "fabs", "trunc", "abs", "exp2", "log2", "cbrt"]
S3_STR = ["ascii_downcase", "ascii_upcase", "tojson", "utf8bytelength", "trim", "ltrim", "rtrim", 'ltrimstr("a")', 'rtrimstr("b")', 'startswith("a")',
          'endswith("b")', 'split(",")', 'explode', 'explode | implode', 'tojson | fromjson', 'indices("a")', 'index("a")', 'rindex("a")', 'indices(1)', 'indices([1])', 'indices([1,2])', 'indices(null)', 'tostring | fromjson?', '@text', '@json', '@html', '@uri', '@sh', '@base64', '@csv', '@tsv', '(@base64 | @base64d)', '"<\\(.)>"', '@json "v=\\(.)"', '@html "<\\(.)>"', '@sh "echo \\(.)"', '@uri "?q=\\(.)"',  'split("a")', 'trimstr("a")', "tostring", "length"]
S3_COLL = ["sort", "unique", "reverse", "min", "max", "add", "flatten", "any", "all", "to_entries", "keys_unsorted", "transpose", "join(\",\")", "join(1)",
           "group_by(.)", "sort_by(.a)", "group_by(.a)", "unique_by(.a)", "min_by(.a)", "max_by(.a)", 'contains(["a"])', 'inside([1,"a"])', 'IN(1,"a")',
           "flatten(1)", "map_values(.)", "map_values(length?)", "map_values(select(. != null))", "map({key: tostring, value: .}) | from_entries", "to_entries | from_entries", "with_entries(select(.value != null))", "map({k: tostring, value: .}) | from_entries?", "map({name: tostring, Value: .}) | from_entries", "map({Key: (.|tostring), v: .}) | from_entries", "from_entries", "with_entries(.)", "first", "last", "length"]
S3_PAT = ["$x", "[$x, $y]", "{a: $x}", "{$a}", "[$x]", "{a: $x, b: $y}", "[$x, [$y]]", "{a: [$x]}"]


def gen_s3(r, depth):
    """Stage 3 grammar: reduce/foreach/def/patterns/collectors/math/strings"""
    k = r.random()
    p, q = gen_path(r), gen_path(r)
    if depth <= 0 or k < 0.1:
        return r.choice([p, "[.[]?]", "[" + p + "]", gen_lit(r)])
    if k < 0.22:
        return "reduce %s as $x (%s; %s)" % (p, r.choice(["0", "null", "[]", "{}", '""']), r.choice([". + $x", "[., $x]", ". + 1", "$x", ". // $x", ". + [$x]", "if $x then . else $x end"]))
    if k < 0.32:
        ex = r.choice(["foreach %s as $x (0; . + 1; .)", "foreach %s as $x (null; $x; .)", "foreach %s as $x (0; . + 1; [., $x])", "foreach %s as $x ([]; . + [$x]; length)", "foreach %s as $x (0; . + 1)"])
        return ex % p
    if k < 0.42:
        return "%s as %s | %s" % (r.choice([p, "[" + p + "]", "{a:1,b:[2]}", "[1,[2]]"]), r.choice(S3_PAT), r.choice(["[$x, $y]", "$x", "[.]", "{$x}", "[$a]", "[$x, $a, $b]"]))
    if k < 0.46:
        pats = r.sample(S3_PAT, r.randint(2, 3))
        return "%s as %s | %s" % (r.choice([p, "[" + p + "]", ".[]?", "[.[]?][]"]), " ?// ".join(pats), r.choice(["[$x, $y]", "$x", "[$a, $b]", "[$x, $a]", "if $x then $y else error(\"e\") end", "[$x, $y, $a, $b]", "($x | length)"]))
    if k < 0.52:
        return r.choice(["def f: %s; f", "def f(g): g | length; f(%s)", "def f($a): [$a, .]; f(%s)", "def f(g): [g]; f(%s)", "def f: def g: %s; g; f"]) % r.choice([p, q, "length"])
    if k < 0.66:
        return "%s | %s" % (r.choice([p, q, "[.[]?]", ".[]?"]), r.choice(S3_COLL))
    if k < 0.74:
        return "%s | %s" % (r.choice([p, q, "[.[]?]"]), r.choice(S3_MATH + ["pow(.; 2)", "log10", "sin", "tostring | tonumber?", "infinite", "isnan", "isinfinite", "isnormal", "nan | isnan"]))
    if k < 0.86:
        return "%s | %s" % (r.choice([p, q, "[.[]?]", ".[]?", gen_lit(r)]), r.choice(S3_STR))
    if k < 0.92:
        return "[%s | %s]" % (gen_s3(r, depth - 1), r.choice(["tojson", "type", "length", "tostring"]))
    return "%s | %s" % (gen_s3(r, depth - 1), gen_s3(r, depth - 1))


GRAMMAR = os.environ.get('JXFUZZ_GRAMMAR', 'base')


def make_case(seed, i):
    r = random.Random(seed * 1000003 + i)
    if GRAMMAR == 's3': return gen_doc(r), gen_s3(r, r.randint(1, 3))
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
    ap.add_argument("--grammar", choices=["base", "s3"], default="base", help="s3: the Stage 3 grammar (reduce/foreach/def/patterns/collectors/math/strings)")
    ap.add_argument("--only", type=int, default=None)
    ap.add_argument("--show", type=int, default=12)
    a = ap.parse_args()
    global GRAMMAR
    GRAMMAR = a.grammar
    seeds = [int(s) for s in a.seeds.split(",")]
    tmp = tempfile.mkdtemp(prefix="jxfuzz_", dir=os.environ.get("JX_TMP", "D:/tmp/w/jx"))
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


if __name__ == "__main__":
    main()
