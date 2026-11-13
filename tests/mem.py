#!/usr/bin/env python3
"""Memory behavior of loops (README, "Limits"): a loop over a long input or a long range must not keep a value per round.
Each case has the expected output or the expected error text; the run takes a few seconds and writes one 36 MB scratch document.
Before the loops released their rounds, the first group of cases ended with "out of value memory": a reduce or foreach over a document
iteration collected every element (two entries each) in the 16 million entry document arena, and a loop in an iteration body kept two
entries per round in the 1 million entry arena of its depth.
usage: python tests/mem.py [jx.exe]      (JX_TMP: scratch directory, default D:/tmp/w/jx/t)"""
import os, subprocess, sys

HERE = os.path.dirname(os.path.abspath(__file__))
JX = sys.argv[1] if len(sys.argv) > 1 else os.environ.get("JX", "D:/tmp/w/jx/b/jx.exe")
T = os.environ.get("JX_TMP", "D:/tmp/w/jx/t")
os.makedirs(T, exist_ok=True)
N = 9_000_000
DOC = os.path.join(T, "mem9m.json")
if not os.path.exists(DOC) or os.path.getsize(DOC) < 2 * N:
    with open(DOC, "w") as f:
        f.write('{"a":[' + ",".join(str(1 + i % 3) for i in range(N)) + ']}')
ONE = os.path.join(T, "mem1.json")
open(ONE, "w").write("[1]")
SUM = sum(1 + i % 3 for i in range(N))

def run(args, doc):
    stdin = open(doc, "rb") if doc else subprocess.DEVNULL
    p = subprocess.run([JX] + args, stdin=stdin, capture_output=True, timeout=600)
    return p.returncode, p.stdout.decode().replace("\r", "").strip(), p.stderr.decode().strip()

CASES = [
    # (name, document, args, expected stdout, expected stderr substring)
    ("reduce over a document iteration", DOC, ["reduce .a[] as $x (0; . + $x)"], str(SUM), ""),
    ("reduce with a body", DOC, ["reduce (.a[] | select(. > 1)) as $x (0; . + $x)"], str(sum(v for v in (1 + i % 3 for i in range(N)) if v > 1)), ""),
    ("reduce with a counter", DOC, ["reduce .a[] as $x (0; . + 1)"], str(N), ""),
    ("foreach over a document iteration", DOC, ["foreach .a[] as $x (0; . + 1; select(. % 3000000 == 0))"], "3000000\n6000000\n9000000", ""),
    ("reduce, then more", DOC, ["(reduce .a[] as $x (0; . + 1)) * 2"], str(2 * N), ""),
    ("add fold", DOC, ["[.a[]] | add"], str(SUM), ""),
    ("count fold", DOC, ["[.a[] | . + 1] | length"], str(N), ""),
    ("a collected list too big for the arena is a named error", DOC, ["[.a[]] | map(. + 1) | length"], "", "out of value memory"),
    ("range at the document level", None, ["-n", "reduce range(0; 2000000) as $i (0; . + $i)"], "1999999000000", ""),
    ("range in an iteration body (1 million entry arena)", ONE, [".[] | reduce range(0; 1500000) as $i (0; . + $i)"], "1124999250000", ""),
    ("range with text built each round", None, ["-n", "reduce range(0; 3000000) as $i (0; . + ($i | tostring | length))"], str(sum(len(str(i)) for i in range(3000000))), ""),
    ("two loops in a row", None, ["-n", "reduce range(0; 1500000) as $i (0; . + 1) | reduce range(0; 1500000) as $i (.; . + 1)"], "3000000", ""),
]

bad = 0
for name, doc, args, want, errpart in CASES:
    rc, out, err = run(args, doc)
    ok = (out == want and rc == 0) if not errpart else (rc != 0 and errpart in err)
    if name.startswith("a collected list"):
        ok = rc != 0 and errpart in err
    if not ok:
        bad += 1
        print("FAIL %s: rc=%d out=%r err=%r (wanted %r %r)" % (name, rc, out[:60], err[:100], want[:40], errpart))
print("mem: %d of %d cases pass" % (len(CASES) - bad, len(CASES)))
sys.exit(1 if bad else 0)
