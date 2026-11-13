#!/usr/bin/env python3
"""Differential tests for what the runtime gives jx: input files, -f, --slurpfile, --rawfile, -R, $ENV, input_filename, input_line_number,
debug, stderr, -h/-V, comments in filters, and the math builtins. Runs jq 1.8.2 and jx on the same command line in a scratch folder and
compares standard output (CRLF normalized), the exit code and, where a case asks for it, standard error (exactly, or with jq's `jq:`
prefix read as jx's `jx:`).
usage: python tests/runtime.py [path-to-jx-exe] [--math] [--only TEXT]
  --math    also run the math sweep (every function over many values, one process per function)"""
import os, subprocess, sys, shutil
from concurrent.futures import ThreadPoolExecutor

JQ = os.environ.get("JQ", "C:/ProgramData/chocolatey/lib/jq/tools/jq.exe")
av = [a for a in sys.argv[1:] if not a.startswith("--")]
JX = av[0] if av else os.environ.get("JX", "D:/tmp/w/jxrx-build/jx.exe")
T = os.environ.get("JX_RT_TMP", "D:/tmp/w/jxrx-t")
shutil.rmtree(T, ignore_errors=True)
os.makedirs(T)
only = sys.argv[sys.argv.index("--only") + 1] if "--only" in sys.argv else None

FILES = {
    "f.json": b'{"a":[1,2],"s":"x"}\n',
    "m.json": b'1 2 3\n',
    "one.json": b'{"n":5}',
    "empty.json": b'',
    "n1.json": b'{"a":1}', "n3.json": b'{"a":1}\n\n\n', "n2.json": b'[1,\n2,\n3]\n', "n5.json": b'5\n', "n6.json": b'5 \n',
    "n7.json": b'"s"\n\n', "n8.json": b'[\n\n]\n\n', "n9.json": b'null\ntrue\n',
    "two.json": b'{"a":1}\n{"a":2}\n',
    "bad1.json": b'[1', "bad2.json": b'{"a":}',
    "p.jq": b'.a # c\n | length\n',
    "p2.jq": b'# only a comment\n.a[0] # c \\\n more\n',
    "q.txt": b'line one\nline two\n',
    "r.txt": b'only line\n',
    "u.txt": b'tab\there "quoted" \\ back\n',
    "ws.json": b'  \n {"a" : [ 1 , 2 ] }  \n',
    "bom.json": b'\xef\xbb\xbf{"a":1}',
    "crlf.json": b'{"a":\r\n1}\r\n',
    "a.jq": b'def f: .a;\r\nf # x\r\n',
}
for k, v in FILES.items():
    with open(os.path.join(T, k), "wb") as fh: fh.write(v)

# (name, args, stdin or None, stderr mode: None | "exact" | "prefix")
C = []
def case(args, stdin=None, err=None, env=None):
    C.append((args, stdin, err, env))

# input files and -f
case(["-c", ".", "f.json"]); case(["-c", ".a", "f.json"], b"ignored stdin"); case(["-c", ".", "one.json"]); case(["-c", ".", "empty.json"])
case(["-c", ".", "nope.json"], err="prefix"); case(["-c", ".", "bad1.json"]); case(["-c", ".", "bad2.json"])
case(["-c", "-s", ".", "f.json"]); case(["-c", "-s", ".", "empty.json"]); case(["-c", "-n", "1", "nope.json"])
case(["-c", ".", "ws.json"]); case(["-c", ".", "bom.json"]); case(["-c", ".", "crlf.json"]); case(["-c", ".", "f.json", "f.json"], err="reject")
case(["-c", "-f", "p.jq", "f.json"]); case(["-c", "--from-file", "p.jq", "f.json"]); case(["-cf", "p.jq", "f.json"])
case(["-c", "-f", "p2.jq", "f.json"]); case(["-c", "-f", "a.jq", "f.json"]); case(["-n", "-c", "-f", "p.jq"], b'{"a":[1]}')
case(["-c", "-f", "nope.jq", "f.json"], err="prefix"); case(["-c", "-f"], err=None)
case(["-c", "-f", "p.jq"], b'{"a":[1,2,3]}'); case(["-c", ".", "-f", "f.json"])
case(["-c", "-f", "p.jq", "f.json", "--arg", "x", "y"]); case(["-c", "-f", "p.jq", "--args", "f.json", "x"])
case(["-c", ".a", "--args", "x", "y"], b'{"a":1}'); case(["-c", ".", "f.json", "--args", "x"])
# --slurpfile and --rawfile
case(["-n", "-c", "$x", "--slurpfile", "x", "m.json"]); case(["-n", "-c", "$x", "--slurpfile", "x", "empty.json"]); case(["-n", "-c", "$x", "--slurpfile", "x", "f.json"])
case(["-n", "-c", "$x", "--slurpfile", "x", "two.json"]); case(["-n", "-c", "$x[1:]", "--slurpfile", "x", "m.json"]); case(["-n", "-c", "$x", "--slurpfile", "x", "nope.json"], err="prefix")
case(["-n", "-c", "$x", "--slurpfile", "x", "bad1.json"], err="bad"); case(["-n", "-c", "$x", "--rawfile", "x", "nope"], err="prefix")
case(["-n", "-c", "$x", "--rawfile", "x", "q.txt"]); case(["-n", "-c", "$x", "--rawfile", "x", "u.txt"]); case(["-n", "-c", "$x", "--rawfile", "x", "empty.json"])
case(["-n", "-r", "$x", "--rawfile", "x", "q.txt"]); case(["-n", "-c", "$x|length", "--rawfile", "x", "q.txt"])
case(["-n", "-c", "$ARGS", "--arg", "a", "1", "--slurpfile", "f", "m.json", "--rawfile", "r", "f.json"])
case(["-n", "-c", "$ARGS.named", "--arg", "a", "1", "--slurpfile", "f", "m.json", "--rawfile", "r", "u.txt", "--argjson", "j", "[1]"])
case(["-c", "[., $x]", "f.json", "--slurpfile", "x", "m.json"]); case(["-c", "$x + $y", "-n", "--rawfile", "x", "r.txt", "--rawfile", "y", "r.txt"])
case(["-n", "-c", "$__named"]); case(["-n", "-c", "$__prog_args"]); case(["-n", "-c", "$ARGS", "--args", "a", "b", "--slurpfile", "s", "m.json"])
case(["-n", "-c", "[$ARGS.positional, $s]", "--slurpfile", "s", "m.json", "--args", "a"])
# $ENV, env, input_filename, input_line_number
case(["-n", "-c", "$ENV|type"]); case(["-n", "-c", "env|type"]); case(["-n", "-c", "$ENV.JXRT_A, env.JXRT_B, ($ENV|has(\"JXRT_A\"))"], env={"JXRT_A": "alpha", "JXRT_B": "be ta \"q\" \\ x"})
case(["-n", "-c", "[$ENV|keys[]|select(startswith(\"JXRT_\"))]"], env={"JXRT_Z": "1", "JXRT_A": "2", "JXRT_M": ""})
case(["-n", "-c", "$ENV.JXRT_NOPE"]); case(["-n", "-c", "env.JXRT_NOPE"]); case(["-c", ".a", "f.json", "--arg", "ENV", "x"]); case(["-n", "-c", "$ENV|length > 0"])
case(["-n", "-c", "[$ENV|keys[]]"]); case(["-n", "-c", "env"]); case(["-n", "-c", "$ENV|length"]); case(["-n", "-c", "[$ENV|to_entries[]|.key]|length"]); case(["-n", "-c", "--arg", "a", "1", "--arg", "a", "2", "[$a,$ARGS]"]); case(["-c", ".", "-"], b'{"x":1}'); case(["-n", "-c", "$a", "--slurpfile", "a", "m.json", "--arg", "a", "z"])
case(["-n", "-c", "def env: 1; env"]); case(["-n", "-c", ". as $ENV | $ENV"]); case(["-n", "-c", "$ENV.JXRT_A|length"], env={"JXRT_A": "x" * 5000})
case(["-n", "-c", "input_filename"]); case(["-c", "input_filename", "f.json"]); case(["-c", "input_filename"], b"{}"); case(["-c", "[input_filename]", "-"], b"{}")
case(["-c", "-s", "input_filename", "f.json"]); case(["-c", "[., input_filename]", "one.json"]); case(["-c", "-n", "[input_filename]", "f.json"])
for f in ("f.json", "n1.json", "n3.json", "n2.json", "n5.json", "n6.json", "n7.json", "n8.json", "n9.json", "two.json", "empty.json", "ws.json", "crlf.json"):
    ex = "reject" if f in ("n9.json", "two.json") else None
    case(["-c", "input_line_number", f], err=ex); case(["-c", "-s", "input_line_number", f], err=ex)
case(["-n", "-c", "input_line_number"]); case(["-c", "input_line_number"], b'{"a":1}\n'); case(["-c", "[., input_line_number]", "n2.json"])
long = b'{"a":"' + b"x" * 5000 + b'"}\n'; C.append((["-c", "input_line_number", "LONG"], None, None, None))
FILES["LONG"] = long; open(os.path.join(T, "LONG"), "wb").write(long)
FILES["LONG2"] = b'[' + b"1," * 3000 + b'2]\n'; open(os.path.join(T, "LONG2"), "wb").write(FILES["LONG2"]); case(["-c", "input_line_number", "LONG2"])
FILES["LONG3"] = b'[' + b"1," * 2047 + b'2]\n'; open(os.path.join(T, "LONG3"), "wb").write(FILES["LONG3"]); case(["-c", "input_line_number", "LONG3"])
FILES["LONG4"] = b'[\n' + b"1," * 2047 + b'2]\n'; open(os.path.join(T, "LONG4"), "wb").write(FILES["LONG4"]); case(["-c", "input_line_number", "LONG4"])
FILES["LONG5"] = b'{"a":1}' + b" " * 5000 + b'\n'; open(os.path.join(T, "LONG5"), "wb").write(FILES["LONG5"]); case(["-c", "input_line_number", "LONG5"])
# debug and stderr (standard error compared exactly)
for flt in ("1|debug", '"a"|debug("x")', ".a|debug", "debug", "[.a[]|debug]", ".a[]|debug|.+1", "debug(.a)", "debug(.a[])", "debug(empty)", "debug(\"m\", \"n\")",
            ".a|debug|empty", "(.a|debug)|empty", "[.a[]|debug|empty]", ".s|debug|length", "{a:.a|debug}", ".a[0] as $x|$x|debug|.+$x", "[debug(1,2), 3]",
            "debug(.s|ascii_upcase)", ".|debug(.s)|.a", "try (.a|debug|error) catch .", ".a[] | debug(\"v=\\(.)\")", "debug(\"\\(.a)\")", "[.s,.s|debug]"):
    case(["-c", flt, "f.json"], err="exact");
for flt in ('"a"|stderr', '{"a":1}|stderr', '[1,"\\u00e9"]|stderr', '"\\u00e9\\n"|stderr', "1|stderr", "null|stderr", ".a[]|stderr", "[.a[]|stderr]", '"x"|stderr|length', "stderr|.a",
            '"a\\"b"|stderr', '"\\u0000x"|stderr', '"line\\nline"|stderr'):
    case(["-c", flt, "f.json"], err="exact"); case(["-r", flt, "f.json"], err="exact")
case(["-n", "-c", "1|debug"], err="exact"); case(["-n", "-c", "[1,2]|debug|map(.+1)"], err="exact"); case(["-n", "-c", '"x"|stderr|debug'], err="exact")
case(["-c", "debug|stderr", "one.json"], err="exact"); case(["-c", ".n|debug|debug", "one.json"], err="exact")
# help and version (jx prints its own text: not compared with jq; see tests/run.py)
# comments and whitespace in filters
for flt in (".a # c\n | length", "# only\n.a[0]", ".a[0] # c \\\n more\n+1", ".a #x\r\n|length", ".a # c \\\\\n | length", ".a # c \\\\\\\n | length", ".a # c \\\r\n | length",
            ".a # c \\\r\n| length\n| length", ".a # c \\\\\r\n| length", '.a | "x#y" | length # z', ".a #", ".a # \u00e9 \u00fc\n|length", "\n\n.a\n\n", ".a # x\r| length",
            "[1, # one\n 2 # two\n]", "{a: 1, # c\n b: 2}", ".a | # c\n length # end", "def f: # c\n 1; f", "(.a # c\n)", "if # c\n true # c\n then # c\n 1 else 2 end",
            "reduce .a[] as $x (0; . + $x # add\n)", ".a | .[ # c\n 0 ]", '"\\(1 # c\n + 1)"', ".a # c\n", "#", "# a\n# b\n.a", ".a\t|\tlength", ".[\"a\"] # c\n[0]"):
    case(["-c", flt, "f.json"])
case(["-c", "# not a comment", "-n"]); case(["-n", "-c", "1 # a\n# b\n+ 2"])
# -R
case(["-R", "-c", "."], b"x\n"); case(["-R", "-c", "."], b"x"); case(["-R", "-c", "."], b"\n"); case(["-R", "-c", "."], b""); case(["-R", "-c", "length"], b"hello\n")
case(["-R", "-c", "."], b"a\nb\n", err="reject"); case(["-R", "-c", "."], b'tab\t"q" \\ \x01\n'); case(["-Rs", "-c", "."], b"a\nb\n"); case(["-Rs", "-c", "."], b""); case(["-R", "-s", "-c", "length"], b"a\nb")
case(["-Rn", "-c", "1"]); case(["-nR", "-c", "[.]"], b"zzz\n"); case(["-R", "-c", ".", "r.txt"]); case(["-Rs", "-c", ".", "q.txt"]); case(["-Rs", "-c", ".", "u.txt"])
case(["-R", "-r", "."], b"x y\n"); case(["--raw-input", "-c", "ascii_upcase"], b"abc\n"); case(["-R", "-c", "input_line_number"], b"a\n"); case(["-Rs", "-c", "input_line_number"], b"a\nb\n")
case(["-R", "-c", "tonumber"], b"12\n"); case(["-R", "-c", "fromjson"], b'{"a":1}\n'); case(["-R", "-c", "."], b"\xc3\xa9\n"); case(["-R", "-c", "split(\" \")"], b"a b c\n")
# options
case(["-c", ".", "-L", "x"], err="reject"); case(["-n", "-c", "1", "-S"], err="reject"); case(["-n", "-c", "1", "-C"], err="reject"); case(["-n", "-c", "1", "--stream"], err="reject"); case(["-n", "-c", "[1]", "--seq"])

def run(exe, args, stdin, env):
    e = dict(os.environ)
    if env: e.update(env)
    try:
        p = subprocess.run([exe] + args, input=stdin if stdin is not None else b"", capture_output=True, timeout=60, cwd=T, env=e)
    except subprocess.TimeoutExpired:
        return -9, b"", b"timeout"
    return p.returncode, p.stdout.replace(b"\r\n", b"\n"), p.stderr.replace(b"\r\n", b"\n")

def check(c):
    args, stdin, err, env = c
    q = run(JQ, args, stdin, env); g = run(JX, args, stdin, env)
    why = None
    if err == "reject":
        # what jx does not do: it says so and writes nothing
        if g[0] == 0 or not g[2] or g[1]: why = "jx should refuse"
    elif err == "bad":
        if q[0] != 2 or g[0] not in (2, 5) or g[1] or not g[2]: why = "bad input file"
    elif q[0] == 0:
        if g[0] != 0 or g[1] != q[1]: why = "stdout/exit"
        elif err == "exact" and g[2] != q[2]: why = "stderr"
    else:
        # jq failed: jx must fail too, with the same exit code when jq's is a file error (2); a filter or option jx rejects exits 1 or 2
        if g[0] == 0 or not g[2]: why = "jx should fail"
        elif g[1] != q[1]: why = "stdout"
        elif q[0] == 2 and g[0] != 2 and g[0] != 1: why = "exit code"
        elif err == "prefix" and q[2].replace(b"jq:", b"jx:", 1) != g[2]: why = "stderr text"
    return c, why, q, g

def label(c):
    return "%s%s%s" % (" ".join(repr(a) if (" " in a or "\n" in a or "\\" in a) else a for a in c[0]), "  <<< %r" % c[1] if c[1] is not None else "", "  env=%r" % (c[3],) if c[3] else "")

cases = [c for c in C if not only or only in label(c)]
bad = 0
with ThreadPoolExecutor(max_workers=6) as ex:
    for c, why, q, g in ex.map(check, cases):
        if why:
            bad += 1
            print("FAIL (%s): %s" % (why, label(c)))
            print("   jq rc=%d out=%r err=%r" % (q[0], q[1][:160], q[2][:160])); print("   jx rc=%d out=%r err=%r" % (g[0], g[1][:160], g[2][:160]))
print("runtime cases: %d, failures: %d" % (len(cases), bad))

# ---- math ----
if "--math" in sys.argv:
    VALS = ["0", "-0", "1", "-1", "0.5", "-0.5", "1.5", "2.5", "-2.5", "3", "10", "100", "0.1", "1e-5", "1e-300", "5e-324", "1e-320", "2.2250738585072014e-308", "1e10", "1e15", "1e16",
            "1e100", "1e308", "1.7976931348623157e308", "-1e308", "123.456", "-123.456", "0.99999", "1.00001", "7.5", "20", "30", "171", "172", "-3.5", "-170.5", "infinite", "-infinite", "nan",
            "3.14159", "2.718281828", "1.0000000001", "0.3333333333333333", "1e-10", "6", "-7", "0.7071067811865476", "9007199254740993", "4503599627370497.5", "-4503599627370497.5"]
    ARR = "[" + ",".join(VALS) + "]"
    UN = "acos acosh asin asinh atan atanh cbrt ceil cos cosh exp exp10 exp2 expm1 fabs floor gamma j0 j1 lgamma lgamma_r log log10 log1p log2 logb nearbyint rint round significand sin sinh sqrt tan tanh tgamma trunc y0 y1 frexp modf abs isinfinite isnan isnormal".split()
    BIN = "atan2 copysign drem fdim fmax fmin fmod hypot ldexp nextafter nexttoward pow remainder scalb scalbln".split()
    MV = ["0", "-0", "1", "-1", "2", "-2", "0.5", "-0.5", "2.5", "10", "-10", "3", "100", "-100", "1074", "-1074", "1e10", "3e9", "-3e9", "2147483647", "2147483648", "-2147483648", "-2147483649", "4294967296",
          "1e300", "-1e300", "5e-324", "1e-300", "infinite", "-infinite", "nan", "1.5", "7.25", "0.3", "-5.5", "17"]
    def mrun(exe, flt):
        p = subprocess.run([exe, "-n", "-c", flt], capture_output=True, timeout=120)
        return p.returncode, p.stdout.replace(b"\r\n", b"\n"), p.stderr
    jobs = []
    for f in UN:
        jobs.append((f, "%s | map(try (%s) catch \"E\")" % (ARR, f), None))
    for f in BIN:
        jobs.append((f, "%s as $v | $v | map(. as $a | $v | map(try (%s($a; .)) catch \"E\"))" % ("[" + ",".join(MV) + "]", f), None))
    jobs.append(("fma", "[" + ",".join(MV[:14]) + "] as $v | [$v[] as $a | $v[] as $b | $v[] as $c | try fma($a;$b;$c) catch 'E']".replace("'E'", chr(34) + "E" + chr(34)), None))
    jobs.append(("fma3", "[1,2,3,0.1,1e308,infinite,nan] as $v | [$v[] as $a | $v[] as $b | $v[] as $c | try fma($a;$b;$c) catch \"E\"]", None))
    jobs.append(("errors", '["a", null, [], {}, true] | map(. as $x | try (sin) catch "E", try ldexp($x; 1) catch "E", try ldexp(1; $x) catch "E", try frexp catch "E", try fma($x;1;1) catch "E")', None))
    def mjob(j):
        n, flt, _ = j
        q = mrun(JQ, flt); g = mrun(JX, flt)
        return n, flt, q, g
    mbad = 0
    with ThreadPoolExecutor(max_workers=6) as ex:
        for n, flt, q, g in ex.map(mjob, jobs):
            if q[0] == 0 and g[0] == 0 and q[1] == g[1]: continue
            mbad += 1
            print("MATH DIFF %s: jq rc=%d jx rc=%d" % (n, q[0], g[0]))
            if q[0] == 0 and g[0] == 0:
                qa = q[1].decode(); ga = g[1].decode()
                import json
                try:
                    qj = json.loads(qa); gj = json.loads(ga)
                    def flat(x, path=""):
                        if isinstance(x, list):
                            for i, y in enumerate(x): yield from flat(y, path + "[%d]" % i)
                        else: yield path, x
                    qf = dict(flat(qj)); gf = dict(flat(gj)); shown = 0
                    for k in qf:
                        if qf[k] != gf.get(k) and shown < 6:
                            print("   at %s: jq %r jx %r" % (k, qf[k], gf.get(k))); shown += 1
                except Exception as ex2:
                    print("   unparsed", ex2)
            else:
                print("   jq err %r jx err %r" % (q[2][:200], g[2][:200]))
    # the Windows jq.exe lacks exp10, gamma, lgamma_r, significand, drem and scalb ("not found at build time"): check jx against Python's math module
    import math, json
    BIG = 1.7976931348623157e308
    def fin(y):
        if y != y: return None
        if y == math.inf: return BIG
        if y == -math.inf: return -BIG
        return y
    def lg(x):
        if x != x: return math.nan
        if x in (math.inf, -math.inf): return math.inf
        try: return math.lgamma(x)
        except (ValueError, OverflowError): return math.inf
    def e10(x):
        if x != x: return math.nan
        try: return math.pow(10.0, x)
        except OverflowError: return math.inf
    def sig(x):
        if x == 0 or x != x or x in (math.inf, -math.inf): return x
        return math.frexp(x)[0] * 2
    def gsign(x):
        if x >= 0 or x != x or x == -math.inf: return 1
        if x == math.floor(x): return 1
        return -1 if math.floor(x) % 2 else 1
    def rem(x, y):
        try: return math.remainder(x, y)
        except ValueError: return math.nan
    def scb(x, y):
        if x != x or y != y: return math.nan
        if y in (math.inf, -math.inf):
            if x == 0: return math.nan if y > 0 else x
            return x * (math.inf if y > 0 else 0.0) if x not in (math.inf, -math.inf) else (x if y > 0 else math.nan)
        if y != math.floor(y): return math.nan
        try: return math.ldexp(x, int(max(-100000, min(100000, y))))
        except OverflowError: return math.copysign(math.inf, x)
    def num(v):
        return {"nan": math.nan, "infinite": math.inf, "-infinite": -math.inf}.get(v) if v in ("nan", "infinite", "-infinite") else float(v)
    xs = [num(v) for v in VALS]; ys = [num(v) for v in MV]
    TOL = [1e-13]
    def close(a, b):
        if a is None or b is None: return a is b
        if a == b: return True
        return abs(a - b) <= TOL[0] * max(abs(a), abs(b))
    obad = 0
    for name, fn in (("exp10", e10), ("significand", sig), ("gamma", lg), ("lgamma", lg)):
        TOL[0] = 1e-9 if "gamma" in name else 1e-13
        g = mrun(JX, "%s | map(%s)" % (ARR, name))
        got = json.loads(g[1]); exp = [fin(fn(x)) for x in xs]
        for x, a, b in zip(VALS, got, exp):
            if not close(a, b): obad += 1; print("ORACLE %s(%s): jx %r python %r" % (name, x, a, b))
    TOL[0] = 1e-9
    g = mrun(JX, "%s | map(lgamma_r)" % ARR); got = json.loads(g[1])
    for x, a, xv in zip(VALS, got, xs):
        b = [fin(lg(xv)), gsign(xv)]
        if not (close(a[0], b[0]) and a[1] == b[1]): obad += 1; print("ORACLE lgamma_r(%s): jx %r python %r" % (x, a, b))
    TOL[0] = 1e-13
    for name, fn in (("drem", rem), ("scalb", scb)):
        g = mrun(JX, "%s as $v | $v | map(. as $a | $v | map(%s($a; .)))" % ("[" + ",".join(MV) + "]", name)); got = json.loads(g[1])
        for i, xa in enumerate(ys):
            for j, yb in enumerate(ys):
                b = fin(fn(xa, yb))
                if not close(got[i][j], b): obad += 1; print("ORACLE %s(%s;%s): jx %r python %r" % (name, MV[i], MV[j], got[i][j], b))
    print("oracle (python math) differences: %d" % obad)
    mbad += obad
    print("math functions: %d, differing: %d" % (len(jobs), mbad))
    bad += mbad
sys.exit(1 if bad else 0)
