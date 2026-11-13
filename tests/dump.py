#!/usr/bin/env python3
"""Golden dumps of the compiled program: tests/dump.txt holds (filter, expected `jx --dump-program FILTER` output) pairs; this checks
every pair against the exe, so a change in the lowering shows up as a diff to review.
Format of dump.txt: a line `### FILTER` (the filter text), then the dump lines up to the next `### `.
usage: python tests/dump.py [jx.exe]            check (exit 1 on any difference)
       python tests/dump.py [jx.exe] --update   rewrite tests/dump.txt from the exe (review the git diff)
The filters are listed in FILTERS below (they are the source of truth for which filters are covered)."""
import os, subprocess, sys

HERE = os.path.dirname(os.path.abspath(__file__))
av = [a for a in sys.argv[1:] if not a.startswith("--")]
JX = av[0] if av else os.environ.get("JX", "D:/tmp/w/jx/b/jx.exe")
PATH = os.path.join(HERE, "dump.txt")

FILTERS = [
    ".", ".a", ".a.b.c", ".users[0].n", ".users[]", ".users[] | .addr.city", ".[2:5]", ".users[1:] | length",
    ".users[] | select(.age >= 85) | .n", ".a == 1", ".a < .b", ".age + 1", ".a * 2 - .b", "-.a",
    "{n: .n, c: .addr.city}", "[.users[] | .n]", "{a: 1, b: [.x, .y]}", ".a, .b", ".a // 0",
    "if .a then 1 elif .b then 2 else 3 end", "if .a > 1 then .b else empty end", "try .a catch 0", "try error(\"x\") catch .",
    ".a as $x | $x + 1", ".users[] as $u | $u.age", "limit(3; .users[])", "first(.users[])", "until(. > 100; . * 2)",
    "[range(0; 10)] | length", ".users | map(.age) | add", ".users | length", "[.users[] | select(.age >= 85) | .n] | length",
    ".users | map(.n) | length", ".a | tostring | length", "not", ".users[] | .n | tostring",
]

def dump(f):
    p = subprocess.run([JX, "--dump-program", f], capture_output=True, stdin=subprocess.DEVNULL, timeout=30)
    return (p.stdout.decode("utf-8", "replace").replace("\r\n", "\n") + p.stderr.decode("utf-8", "replace").replace("\r\n", "\n")).rstrip("\n")

def load():
    out, name, buf = [], None, []
    for line in open(PATH, encoding="utf-8").read().split("\n"):
        if line.startswith("### "):
            if name is not None: out.append((name, "\n".join(buf).rstrip("\n")))
            name, buf = line[4:], []
        elif name is not None: buf.append(line)
    if name is not None: out.append((name, "\n".join(buf).rstrip("\n")))
    return out

if "--update" in sys.argv:
    with open(PATH, "w", encoding="utf-8", newline="\n") as fh:
        for f in FILTERS: fh.write("### " + f + "\n" + dump(f) + "\n")
    print("wrote", len(FILTERS), "dumps to", PATH); sys.exit(0)

gold = load()
bad = 0
if [g[0] for g in gold] != FILTERS:
    print("dump.txt filters differ from FILTERS: run --update"); bad += 1
for f, want in gold:
    got = dump(f)
    if got != want:
        bad += 1
        print("DUMP DIFF for filter:", f)
        import difflib
        for l in list(difflib.unified_diff(want.split("\n"), got.split("\n"), "expected", "got", lineterm="", n=0))[:12]: print("   ", l[:160])
print("dump: %d of %d golden dumps match" % (len(gold) - bad, len(gold)))
sys.exit(1 if bad else 0)
