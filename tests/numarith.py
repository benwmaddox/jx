#!/usr/bin/env python3
"""Arithmetic and printing of numbers against jq 1.8.2: pairs of number literals of every shape through + - * / %, comparisons,
unary minus, length and tostring. usage: python tests/numarith.py [jx.exe] [pairs]"""
import os, random, subprocess, sys, struct, math
JX = sys.argv[1] if len(sys.argv) > 1 else "D:/tmp/w/jx/jx3.exe"
N = int(sys.argv[2]) if len(sys.argv) > 2 else 1500
JQ = "C:/ProgramData/chocolatey/lib/jq/tools/jq.exe"
random.seed(20261113)

def lit():
    k = random.random()
    if k < 0.2: return str(random.randint(-1000, 1000))
    if k < 0.35: return str(random.randint(-10**random.randint(1, 30), 10**random.randint(1, 30)))
    if k < 0.5: return "%.*f" % (random.randint(0, 10), random.uniform(-1e4, 1e4))
    if k < 0.65:
        return "%de%d" % (random.randint(-999999, 999999), random.randint(-330, 330))
    if k < 0.75:
        b = random.getrandbits(64); x = struct.unpack('<d', struct.pack('<Q', b))[0]
        if x != x or abs(x) == math.inf: x = 0.5
        return repr(x)
    if k < 0.85: return random.choice(["0", "-0", "0.0", "1.000", "1e3", "1E-5", "5e-324", "1.7976931348623157e308", "1e400", "-1e400", "9007199254740993", "0.1", "0.2", "0.3", "100000000000000000001", "-0.0", "1e17", "1e16", "123456789012345680"])
    return "%d.%0*d" % (random.randint(0, 99), random.randint(1, 6), random.randint(0, 999999))

pairs = [(lit(), lit()) for _ in range(N)]
doc = "[" + ",".join("[%s,%s]" % p for p in pairs) + "]"
open("D:/tmp/w/jx/numarith.json", "w").write(doc)

def run(exe, f):
    with open("D:/tmp/w/jx/numarith.json", "rb") as fh:
        p = subprocess.run([exe, "-c", f], stdin=fh, capture_output=True)
    return p.returncode, p.stdout.replace(b"\r\n", b"\n"), p.stderr

bad = 0
tests = [".[] | .[0] + .[1]", ".[] | .[0] - .[1]", ".[] | .[0] * .[1]", ".[] | .[0] < .[1]", ".[] | .[0] == .[1]", ".[] | .[0] >= .[1]",
         ".[] | -.[0]", ".[] | .[0] | length", ".[] | .[0] | tostring", ".[] | [.[0], .[1]]", ".[] | {a: .[0]}", ".[] | .[0] + 0", ".[] | .[0] * 1",
         ".[] | (.[0] | floor)", ".[] | (.[0] | fabs)", ".[] | (.[0] | sqrt)"]
for f in tests:
    e = run(JQ, f); g = run(JX, f)
    if e[0] != 0:
        # jq failed (e.g. sqrt of nothing?): jx must fail too
        ok = g[0] != 0
    else: ok = g[0] == 0 and g[1] == e[1]
    if not ok:
        bad += 1
        print("DIFF", f, "jq rc", e[0], "jx rc", g[0], g[2][:120])
        if e[0] == 0 and g[0] == 0:
            a = e[1].split(b"\n"); b = g[1].split(b"\n")
            for i, (x, y) in enumerate(zip(a, b)):
                if x != y:
                    print("   first diff at pair", pairs[i], "jq", x[:80], "jx", y[:80]); break
# division and remainder: drop the pairs jq refuses (zero divisor)
for op, nm in (("/", "div"), ("%", "mod")):
    keep = []
    for p in pairs:
        r = subprocess.run([JQ, "-nc", "%s %s %s" % (p[0] if p[0][0] != "-" else "(%s)" % p[0], op, p[1] if p[1][0] != "-" else "(%s)" % p[1])], capture_output=True)
        if r.returncode == 0: keep.append(p)
        if len(keep) >= 400: break
    open("D:/tmp/w/jx/numarith.json", "w").write("[" + ",".join("[%s,%s]" % p for p in keep) + "]")
    f = ".[] | .[0] %s .[1]" % op
    e = run(JQ, f); g = run(JX, f)
    if not (e[0] == 0 and g[0] == 0 and e[1] == g[1]):
        bad += 1
        print("DIFF", f, e[0], g[0], g[2][:120])
        a = e[1].split(b"\n"); b = g[1].split(b"\n")
        for i, (x, y) in enumerate(zip(a, b)):
            if x != y:
                print("   first diff at pair", keep[i], "jq", x[:80], "jx", y[:80]); break
print("numarith: %d pairs, %d tests, %d differences" % (N, len(tests) + 2, bad))
sys.exit(1 if bad else 0)
