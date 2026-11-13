#!/usr/bin/env python3
"""Golden explain output: tests/explain.txt holds (filter, expected `jx --explain FILTER` output: the automaton, the scopes and the program) pairs; this checks
every pair against the exe (stdin is closed: the runtime reads standard input to its end before main runs, even for --explain), so a change in the automaton or the lowering shows up as a diff to review.
Format of explain.txt: a line `### FILTER` (the filter text), then the dump lines up to the next `### `.
usage: python tests/explain.py [jx.exe]            check (exit 1 on any difference)
       python tests/explain.py [jx.exe] --update   rewrite tests/explain.txt from the exe (review the git diff)
The filters are listed in FILTERS below (they are the source of truth for which filters are covered)."""
import os, subprocess, sys

HERE = os.path.dirname(os.path.abspath(__file__))
av = [a for a in sys.argv[1:] if not a.startswith("--")]
JX = av[0] if av else os.environ.get("JX", "D:/tmp/w/jx/b/jx.exe")
PATH = os.path.join(HERE, "explain.txt")

FILTERS = [
    ".", ".a.b", ".users[0].n", ".users[]", ".users[] | .addr.city", ".users[] | select(.age >= 85) | .n", "{n: .n, c: .addr.city}", "[.users[] | .n]",
    ".users | map(.age) | add", ".users | length", "reduce .users[] as $u (0; . + $u.age)", ".users | group_by(.age) | length",
    "label $out | .users[] | if .age > 50 then break $out else .n end", "[.[] | .a?, .[0]?]", "limit(2; .users[])", "try .a catch 0",
    ".a as [$x, $y] | $x", "def f(g): g | length; f(.users)", r'"x\(.a)y"', ".a | ascii_downcase",
]

def dump(f):
    p = subprocess.run([JX, "--explain", f], capture_output=True, stdin=subprocess.DEVNULL, timeout=30)
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
    print("explain.txt filters differ from FILTERS: run --update"); bad += 1
for f, want in gold:
    got = dump(f)
    if got != want:
        bad += 1
        print("DUMP DIFF for filter:", f)
        import difflib
        for l in list(difflib.unified_diff(want.split("\n"), got.split("\n"), "expected", "got", lineterm="", n=0))[:12]: print("   ", l[:160])
print("explain: %d of %d golden outputs match" % (len(gold) - bad, len(gold)))
sys.exit(1 if bad else 0)
