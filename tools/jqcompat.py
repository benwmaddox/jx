#!/usr/bin/env python3
"""jq compatibility matrix: run jq's own tests/jq.test through jq and jaq.

Usage (use `python -I` when the inputs are downloaded data):
  jqcompat.py cases    --test jq.test --out DIR [--jq PATH] [--jaq PATH]   # part 1: per-case results -> DIR/cases.json
  jqcompat.py builtins --out DIR [--jq PATH] [--jaq PATH] [--manual FILE]  # part 2: builtin coverage -> DIR/builtins.json
  jqcompat.py flags    --out DIR [--jq PATH] [--jaq PATH]                  # part 2: command-line flags -> DIR/flags.json
  jqcompat.py report   --out DIR --md docs/jq-feature-matrix.md            # render the matrix document from the JSON files
Everything generated goes under --out (default D:\\tmp\\w\\jqcompat), never into the repo.
"""
import argparse, json, os, re, subprocess, sys, tempfile
from collections import Counter, defaultdict
import decimal
from decimal import Decimal

decimal.setcontext(decimal.Context(prec=5000, Emax=999999999, Emin=-999999999, traps=[decimal.InvalidOperation]))

HERE = os.path.dirname(os.path.abspath(__file__))
JQ = r"C:\ProgramData\chocolatey\lib\jq\tools\jq.exe"
JAQ = "jaq"
MODULES = None  # directory with jq 1.8.2 tests/modules (from --modules)


def run(tool, args, stdin=b"", timeout=10):
    try:
        p = subprocess.run([tool] + args, input=stdin, capture_output=True, timeout=timeout)
        return p.returncode, p.stdout.replace(b"\r\n", b"\n"), p.stderr.replace(b"\r\n", b"\n")
    except subprocess.TimeoutExpired:
        return -9, b"", b"timeout"


# ---------- parsing jq.test ----------
def parse_test(path):
    lines = open(path, "rb").read().decode("utf-8").replace("\r\n", "\n").split("\n")
    cases, i, n = [], 0, len(lines)
    while i < n:
        l = lines[i]
        if l.strip() == "" or l.startswith("#"):
            i += 1
            continue
        if l.startswith("%%FAIL"):
            directive = l.strip()
            start = i + 1
            i += 1
            prog = []
            while i < n and not lines[i].startswith("jq: error"):
                prog.append(lines[i])
                i += 1
            msg = []
            while i < n and lines[i].strip() != "":
                msg.append(lines[i])
                i += 1
            cases.append(dict(kind="fail", prog="\n".join(prog), input=None, expected=None,
                              directive=directive, msg="\n".join(msg), line=start + 1))
            continue
        start = i
        prog = l
        i += 1
        inp = lines[i] if i < n else ""
        i += 1
        exp = []
        while i < n and lines[i].strip() != "":
            if not lines[i].startswith("#"):
                exp.append(lines[i])
            i += 1
        cases.append(dict(kind="ok", prog=prog, input=inp, expected=exp, line=start + 1))
    return cases


# ---------- value normalization ----------
def jload(s):
    return json.loads(s, parse_float=Decimal, parse_int=Decimal, parse_constant=lambda c: ("const", c))


def norm(v, loose=False):
    if isinstance(v, bool):
        return ("b", v)
    if v is None or isinstance(v, str):
        return v
    if isinstance(v, Decimal):
        return ("n", float(v) if loose else v.normalize())
    if isinstance(v, tuple):
        return ("n", None)
    if isinstance(v, list):
        return ("a", [norm(x, loose) for x in v])
    if isinstance(v, dict):
        return ("o", sorted((k, norm(x, loose)) for k, x in v.items()))
    return v


def parse_out(b):
    """Parse concatenated JSON values from output bytes; None when not parseable."""
    txt = b.decode("utf-8", "replace")
    dec = json.JSONDecoder(parse_float=Decimal, parse_int=Decimal, parse_constant=lambda c: ("const", c))
    i, out = 0, []
    try:
        while True:
            while i < len(txt) and txt[i] in " \t\r\n":
                i += 1
            if i >= len(txt):
                return out
            v, i = dec.raw_decode(txt, i)
            out.append(v)
    except Exception:
        return None


def run_case(tool, c, tmpdir):
    pf = os.path.join(tmpdir, "p.jq")
    open(pf, "wb").write(c["prog"].encode("utf-8"))
    stdin = (c["input"] or "null").encode("utf-8") + b"\n"
    args = ["-c", "-f", pf]
    if MODULES:
        args = ["-L", MODULES] + args
    return run(tool, args, stdin)


def status(c, rc, out, err):
    """(status, bytes_match). Status: pass, differ, differ-number-precision, compile, runtime, timeout."""
    if rc == -9:
        return "timeout", False
    if c["kind"] == "fail":
        return ("pass" if rc == 3 else "differ"), False
    exp_b = ("\n".join(c["expected"]) + "\n").encode("utf-8")
    got = parse_out(out)
    try:
        exp = [jload(x) for x in c["expected"]]
    except Exception:
        exp = None
    if rc == 3 and not out:
        return "compile", False
    if got is not None and exp is not None and [norm(x) for x in got] == [norm(x) for x in exp]:
        return "pass", out == exp_b
    if got is not None and exp is not None and [norm(x, True) for x in got] == [norm(x, True) for x in exp]:
        return "differ-number-precision", False
    if rc != 0 and not out:
        return "runtime", False
    return "differ", False


# ---------- feature tags ----------
def load_tags():
    tags = []
    for l in open(os.path.join(HERE, "jqcompat_tags.tsv"), encoding="utf-8"):
        if l.startswith("#") or not l.strip():
            continue
        t, cls, stage, dec, reason, rx = l.rstrip("\n").split("\t")
        tags.append(dict(tag=t, cls=cls, stage=int(stage), decision=dec, reason=reason, rx=rx))
    return tags


def code_text(s):
    """Remove comments and string-literal contents; keep code inside interpolations."""
    out, n = [], len(s)

    def string(i):
        out.append('"')
        i += 1
        while i < n and s[i] != '"':
            if s[i] == "\\" and i + 1 < n:
                if s[i + 1] == "(":
                    out.append("\\(")
                    i += 2
                    depth = 1
                    while i < n and depth:
                        if s[i] == '"':
                            i = string(i)
                            continue
                        if s[i] == "(":
                            depth += 1
                        if s[i] == ")":
                            depth -= 1
                        out.append(s[i])
                        i += 1
                    continue
                i += 2
                continue
            i += 1
        out.append('"')
        return i + 1

    i = 0
    while i < n:
        ch = s[i]
        if ch == '"':
            i = string(i)
        elif ch == "#":
            while i < n and s[i] != "\n":
                i += 1
        else:
            out.append(ch)
            i += 1
    return "".join(out)


def construct(code):
    prev = ""
    for ch in code:
        if ch in "[{" and not (prev and (prev.isalnum() or prev in "_]).?\"$")):
            return True
        if not ch.isspace():
            prev = ch
    return False


def tag_program(prog, tags):
    code = code_text(prog)
    hit = []
    for t in tags:
        ok = construct(code) if t["rx"] == "@construct" else re.search(t["rx"], code, re.M) is not None
        if ok:
            hit.append(t["tag"])
    return hit


DEC_ORDER = ["Stage 2", "Stage 3", "Later", "Open", "Skip"]
CLS_ORDER = "ABCD"


def case_classes(hit, tags):
    """A case is as hard as its hardest tag; 'core' only counts when nothing else matched."""
    by = {t["tag"]: t for t in tags}
    ts = [by[h] for h in hit if h != "core"] or [by["core"]]
    cls = max((t["cls"] for t in ts), key=CLS_ORDER.index)
    stage = max(t["stage"] for t in ts)
    dec = max((t["decision"] for t in ts), key=DEC_ORDER.index)
    return cls, stage, dec


def cmd_cases(a):
    os.makedirs(a.out, exist_ok=True)
    tags = load_tags()
    cases = parse_test(a.test)
    res = []
    with tempfile.TemporaryDirectory(dir=a.out) as td:
        for k, c in enumerate(cases):
            rj = run_case(a.jq, c, td)
            ra = run_case(a.jaq, c, td)
            sj, bj = status(c, *rj)
            sa, ba = status(c, *ra)
            hit = tag_program(c["prog"], tags)
            cls, stage, dec = case_classes(hit, tags)
            res.append(dict(n=k, line=c["line"], kind=c["kind"], prog=c["prog"], input=c["input"], expected=c["expected"],
                            jq=sj, jq_bytes=bj, jq_rc=rj[0], jq_err=rj[2].decode("utf-8", "replace")[:300],
                            jq_out=rj[1].decode("utf-8", "replace")[:300],
                            jaq=sa, jaq_bytes=ba, jaq_rc=ra[0], jaq_out=ra[1].decode("utf-8", "replace")[:300],
                            jaq_err=ra[2].decode("utf-8", "replace")[:300],
                            tags=hit, cls=cls, stage=stage, decision=dec))
    json.dump(res, open(os.path.join(a.out, "cases.json"), "w"), indent=0)
    print("cases", len(res), "jq", dict(Counter(r["jq"] for r in res)), "jaq", dict(Counter(r["jaq"] for r in res)))


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["cases", "builtins", "flags", "report"])
    ap.add_argument("--test")
    ap.add_argument("--out", default=r"D:\tmp\w\jqcompat")
    ap.add_argument("--jq", default=JQ)
    ap.add_argument("--jaq", default=JAQ)
    ap.add_argument("--manual")
    ap.add_argument("--md")
    ap.add_argument("--modules", help="tests/modules directory of the jq tag, passed as -L")
    a = ap.parse_args()
    MODULES = a.modules
    globals()["cmd_" + a.cmd](a)
