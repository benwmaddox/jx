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


# ---------- part 2: builtins, syntax, behavior spot checks, flags ----------
def probe_pair(a, args, stdin=b"", files=None, timeout=10):
    """Run args on jq and jaq; {T} in args is a temp dir holding `files`."""
    with tempfile.TemporaryDirectory(dir=a.out) as td:
        for k, v in (files or {}).items():
            open(os.path.join(td, k), "wb").write(v)
        argv = [x.replace("{T}", td) for x in args]
        rj = run(a.jq, argv, stdin, timeout)
        ra = run(a.jaq, argv, stdin, timeout)
    return rj, ra


def classify(rj, ra):
    ea = ra[2].decode("utf-8", "replace")
    if rj[0] == ra[0] and rj[1] == ra[1]:
        return "same"
    unsup = ("undefined" in ea or "unexpected argument" in ea or "unknown" in ea.lower() or "found argument" in ea
             or "unrecognized" in ea or (ra[0] == 2 and rj[0] != 2) or (ra[0] == 3 and rj[0] != 3))
    if unsup and ra[0] != 0:
        return "unsupported"
    if rj[1] == ra[1]:
        return "same-output-different-exit-code"
    return "differs"


def short(b, n=120):
    return b.decode("utf-8", "replace").replace("\n", "\\n")[:n]


def cmd_builtins(a):
    sys.path.insert(0, HERE)
    from jqcompat_probes import SPOT, SYNTAX
    os.makedirs(a.out, exist_ok=True)
    rc, out, err = run(a.jq, ["-nc", "builtins|sort"])
    names = json.loads(out)
    rows = []
    pf = os.path.join(a.out, "probe.jq")
    for nm in names:
        base, ar = nm.rsplit("/", 1)
        ar = int(ar)
        body = base + ("(" + ";".join(["."] * ar) + ")" if ar else "")
        open(pf, "w", encoding="utf-8").write("if false then %s else 0 end" % body)  # compile-only: never executed
        rj = run(a.jq, ["-nc", "-f", pf])
        ra = run(a.jaq, ["-nc", "-f", pf])
        ea = ra[2].decode("utf-8", "replace")
        st = "defined" if ra[0] == 0 else ("missing" if "undefined filter" in ea else "other-error")
        rows.append(dict(name=nm, jq_rc=rj[0], jaq=st, jaq_err=ea[:120].replace("\n", " ")))
    manual = []
    if a.manual and os.path.exists(a.manual):
        for l in open(a.manual, encoding="utf-8"):
            m = re.match(r"^\s*-?\s*title:\s*(.*)$", l)
            if m:
                manual.append(m.group(1).strip())
    mnames = set()
    for t in manual:
        for m in re.finditer(r"`(\$?\w+)(?:\(([^)]*)\))?", t):
            mnames.add((m.group(1), (m.group(2).count(";") + 1) if m.group(2) else 0))
    have = set(names)
    manual_only = sorted("%s/%d" % x for x in mnames if "%s/%d" % x not in have)
    syntax = []
    for label, prog, inp in SYNTAX:
        rj, ra = probe_pair(a, ["-c", prog], inp.encode() + b"\n")
        syntax.append(dict(label=label, prog=prog, cls=classify(rj, ra), jq=short(rj[1] or rj[2]), jaq=short(ra[1] or ra[2])))
    spot = []
    for label, prog, inp, extra in SPOT:
        rj, ra = probe_pair(a, ["-c"] + extra + [prog], inp.encode() + b"\n")
        spot.append(dict(label=label, prog=prog, cls=classify(rj, ra), jq=short(rj[1] or rj[2]), jaq=short(ra[1] or ra[2]),
                         jq_rc=rj[0], jaq_rc=ra[0]))
    json.dump(dict(builtins=rows, manual_only=manual_only, syntax=syntax, spot=spot),
              open(os.path.join(a.out, "builtins.json"), "w"), indent=0)
    print(len(rows), Counter(r["jaq"] for r in rows), "syntax", Counter(x["cls"] for x in syntax), "spot", Counter(x["cls"] for x in spot))


def cmd_flags(a):
    sys.path.insert(0, HERE)
    from jqcompat_probes import FLAGS
    os.makedirs(a.out, exist_ok=True)
    res = []
    for label, args, stdin in FLAGS:
        rj, ra = probe_pair(a, args, stdin, files={"f.json": b'{"a":1}\n', "p.jq": b".+1"})
        res.append(dict(label=label, args=args, cls=classify(rj, ra), jq_rc=rj[0], jaq_rc=ra[0],
                        jq=short(rj[1] or rj[2], 80), jaq=short(ra[1] or ra[2], 80)))
    json.dump(res, open(os.path.join(a.out, "flags.json"), "w"), indent=0)
    print(Counter(r["cls"] for r in res))


# ---------- report ----------
def md_table(head, rows):
    esc = lambda x: str(x).replace("|", "\\|").replace("\n", " ")
    out = ["| " + " | ".join(head) + " |", "|" + "---|" * len(head)]
    out += ["| " + " | ".join(esc(c) for c in r) + " |" for r in rows]
    return "\n".join(out)


def pct(a, b):
    return "%.1f%%" % (100.0 * a / b) if b else "n/a"


def cmd_report(a):
    sys.path.insert(0, HERE)
    from jqcompat_decisions import BUILTIN_GROUPS, FLAG_DEC
    cases = json.load(open(os.path.join(a.out, "cases.json")))
    bl = json.load(open(os.path.join(a.out, "builtins.json")))
    flags = json.load(open(os.path.join(a.out, "flags.json")))
    tags = load_tags()
    N = len(cases)
    jqpass = sum(c["jq"] == "pass" for c in cases)
    nfail = sum(c["kind"] == "fail" for c in cases)
    jc = Counter(c["jaq"] for c in cases)
    jp = jc["pass"]
    jbytes = sum(c["jaq_bytes"] for c in cases if c["jaq"] == "pass")
    jqbytes = sum(c["jq_bytes"] for c in cases if c["jq"] == "pass" and c["kind"] == "ok")
    nok = N - nfail
    diff_catch = sum(1 for c in cases if c["jaq"] == "differ" and "catch" in c["prog"])
    # decision coverage (case decision = hardest tag)
    def cov(allowed):
        return sum(1 for c in cases if c["decision"] in allowed)
    s2, s23 = cov({"Stage 2"}), cov({"Stage 2", "Stage 3"})
    s23l = cov({"Stage 2", "Stage 3", "Later"})
    sall = cov({"Stage 2", "Stage 3", "Later", "Open"})
    cls = Counter(c["cls"] for c in cases)
    stg = Counter(c["stage"] for c in cases)
    miss = [r for r in bl["builtins"] if r["jaq"] == "missing"]
    grp_of = {}
    for g, k, d, why, names in BUILTIN_GROUPS:
        for n in names.split():
            grp_of[n] = (g, k, d)
    L = []
    w = L.append
    w("# jq feature matrix and jaq completeness")
    w("")
    w("Generated by `tools/jqcompat.py report` from jq 1.8.2 (`tests/jq.test` at tag jq-1.8.2) and jaq 3.1.2. All decisions below are **proposals** for the owner "
      "(columns marked Decision); the class and stage columns come from docs/design.md section 6 and 9. Case-to-feature tagging is a regex heuristic over the "
      "program text (see tools/jqcompat_tags.tsv), so per-tag counts overlap and class/decision counts are estimates, not proofs.")
    w("")
    w("## Summary")
    w("")
    w("- `jq.test` has %d runnable cases (%d are `%%%%FAIL` cases that must not compile). jq 1.8.2 itself passes %d of %d (harness check; module cases run with `-L` on the tag's tests/modules; "
      "cases whose comment says \"Runtime error\" are expected to fail at run time). Byte-for-byte match of jq output with the expected text: %d of %d ok-cases (the rest differ only in formatting such as key order or number text, which the test runner ignores)." % (N, nfail, jqpass, N, jqbytes, nok))
    w("- jaq 3.1.2 passes **%d of %d (%s)** compared as parsed JSON; %d of them are also byte-identical. Not passing: %d differ, %d fail to compile (undefined filter or syntax), "
      "%d fail at run time with no output, %d time out." % (jp, N, pct(jp, N), jbytes, jc["differ"] + jc["differ-number-precision"], jc["compile"], jc["runtime"], jc["timeout"]))
    w("- %d of jaq's %d differing cases use `catch`, so many differences are only error-message text." % (diff_catch, jc["differ"]))
    w("- jaq lacks %d of %d jq 1.8.2 builtins (name/arity): %s." % (len(miss), len(bl["builtins"]), ", ".join(r["name"] for r in miss)))
    w("- Biggest jaq gaps by tag are in the table of section 1 (sorted by cases failing); notable: `$__loc__`, `?//`, `tostream`/`fromstream`/`truncate_stream`, SQL-style (`INDEX`, `IN`, `JOIN`), "
      "`trimstr`, `input_line_number`, `have_literal_numbers`, number text (`1E+3` vs `1e3`) and error-message wording; command-line: `--stream`, `--seq`, `-a`, `--jsonargs`, `--unbuffered`, `-b`.")
    w("- jx classes by jq.test case (hardest feature in the program decides): A %d (%s), B %d (%s), C %d (%s), D %d (%s)." % tuple(
        v for k in "ABCD" for v in (cls[k], pct(cls[k], N))))
    w("- Share of jq.test that jx could pass if exactly these decision sets were built (upper bound: needs correct output for each case): "
      "**Stage 2 only %s** (%d), **Stage 2+3 %s** (%d), **+ Later %s** (%d), **everything except Skip %s** (%d). Class C features (paths, walk, tostream, assignment, dynamic keys, `..`) "
      "are what `Open`/`Skip` hold back; a subtree fallback engine would add the C share (%s)." % (
          pct(s2, N), s2, pct(s23, N), s23, pct(s23l, N), s23l, pct(sall, N), sall, pct(cls["C"], N)))
    w("")
    w("## 1. jq.test results by feature tag")
    w("")
    w("A case can carry several tags, so rows overlap. `core` matches every case. Columns jaq pass / differ / compile / runtime count cases that carry the tag.")
    w("")
    rows = []
    bytag = defaultdict(list)
    for c in cases:
        for t in c["tags"]:
            bytag[t].append(c)
    for t in tags:
        cs = bytag.get(t["tag"], [])
        cc = Counter(c["jaq"] for c in cs)
        rows.append((t["tag"], len(cs), cc["pass"], cc["differ"] + cc["differ-number-precision"], cc["compile"], cc["runtime"] + cc["timeout"],
                     t["cls"], t["stage"], t["decision"] + " (proposal)", "%s" % t["reason"]))
    rows.sort(key=lambda r: -(r[1] - r[2]))
    w(md_table(["tag", "cases", "jaq pass", "jaq differ", "jaq compile fail", "jaq runtime/timeout", "jx class", "stage", "Decision", "cost class and reason"], rows))
    w("")
    w("Representative failing programs per tag (jq expected vs jaq; first three):")
    w("")
    for t in tags:
        if t["tag"] == "core":
            continue
        bad = [c for c in bytag.get(t["tag"], []) if c["jaq"] != "pass"][:3]
        if not bad:
            continue
        w("- **%s**" % t["tag"])
        for c in bad:
            exp = " ".join(c["expected"] or ["(must not compile)" if c["kind"] == "fail" else "(runtime error)"])
            got = c["jaq_out"].replace("\n", " ").strip() or c["jaq_err"].replace("\n", " ").strip()[:80]
            w("  - `%s` on `%s`: jq %s; jaq %s [%s]" % (c["prog"].replace("\n", " ")[:90], (c["input"] or "")[:40], exp[:70].replace("`", "'"), got[:80].replace("`", "'"), c["jaq"]))
    w("")
    w("## 2. jx classes and decision sets")
    w("")
    w("Class A: extraction only. B: built values or an arena, one pass. C: whole subtree in memory. D: outside the filter engine (flags, modules, input, dates, formats). "
      "A case takes the hardest class among its tags (heuristic).")
    w("")
    w(md_table(["class", "cases", "share"], [(k, cls[k], pct(cls[k], N)) for k in "ABCD"]))
    w("")
    w(md_table(["stage (hardest tag)", "cases", "cumulative", "cumulative share"],
               [(k, stg[k], sum(stg[j] for j in stg if j <= k), pct(sum(stg[j] for j in stg if j <= k), N)) for k in sorted(stg)]))
    w("")
    w("Stage numbers follow docs/design.md section 9 (6 means rejected or out of scope there). Stage 1 is the span navigator; items of stage 1 and 2 are the planned Stage 2 scope.")
    w("")
    w("Coverage by decision set (share of all %d cases whose every tag is inside the set):" % N)
    w("")
    w(md_table(["set", "cases", "share"], [
        ("Stage 2 only", s2, pct(s2, N)), ("Stage 2 + Stage 3", s23, pct(s23, N)),
        ("Stage 2 + Stage 3 + Later", s23l, pct(s23l, N)), ("everything except Skip (adds Open)", sall, pct(sall, N)),
        ("everything (adds Skip)", N, "100.0%")]))
    w("")
    w("## 3. Builtins jq 1.8.2 has and jaq 3.1.2 lacks")
    w("")
    w("Method: each `name/arity` from `jq -nc 'builtins|sort'` is compiled as `if false then name(.;.) else 0 end` (never executed) and classified by jaq's `undefined filter` error. "
      "%d builtins checked; %d defined in jaq; %d missing; %d other errors." % (len(bl["builtins"]), sum(r["jaq"] == "defined" for r in bl["builtins"]), len(miss), sum(r["jaq"] == "other-error" for r in bl["builtins"])))
    w("")
    rows = []
    for r in miss:
        g = grp_of.get(r["name"].split("/")[0], ("misc", "?", "Open"))
        rows.append((r["name"], g[0], g[1], g[2] + " (proposal)"))
    w(md_table(["builtin", "group", "jx class", "Decision"], rows))
    w("")
    w("Manual-only names (in the v1.8 manual titles but not in `builtins`; mostly keywords, `$` variables and operators): " + ", ".join(bl["manual_only"]) +
      ". The manual parse reads arity from the backticked title, so `in/0`, `inside/0`, `and/0`, `or/0` here are artifacts of that parse, not builtins. Probed as syntax below.")
    w("")
    w("### Builtin groups (all %d builtins)" % len(bl["builtins"]))
    w("")
    rows = []
    seen = set()
    for g, k, d, why, names in BUILTIN_GROUPS:
        ns = names.split()
        mem = [r for r in bl["builtins"] if r["name"].split("/")[0] in ns]
        seen.update(r["name"] for r in mem)
        m = [r["name"] for r in mem if r["jaq"] == "missing"]
        rows.append((g, len(mem), len(m), k, d + " (proposal)", why))
    rest = [r for r in bl["builtins"] if r["name"] not in seen]
    if rest:
        rows.append(("ungrouped: " + ", ".join(r["name"] for r in rest), len(rest), sum(r["jaq"] == "missing" for r in rest), "?", "Open (proposal)", "not assigned a group"))
    w(md_table(["group", "builtins (name/arity)", "jaq lacks", "jx class", "Decision", "cost class and reason"], rows))
    w("")
    w("### Syntax, keywords, operators and variables (run on both tools)")
    w("")
    sy = bl["syntax"]
    bad = [x for x in sy if x["cls"] != "same"]
    w("Same output on both: %d of %d (%s). Differences:" % (len(sy) - len(bad), len(sy), ", ".join(x["label"] for x in sy if x["cls"] == "same")))
    w("")
    w(md_table(["feature", "result", "jq", "jaq"], [(x["label"], x["cls"], x["jq"][:60], x["jaq"][:60]) for x in bad]))
    w("")
    w("### Behavior spot checks on builtins both tools define")
    w("")
    sp = bl["spot"]
    bad = [x for x in sp if x["cls"] != "same"]
    w("%d probes; identical output and exit code on %d. Differences:" % (len(sp), len(sp) - len(bad)))
    w("")
    w(md_table(["probe", "program", "result", "jq", "jaq"], [(x["label"], x["prog"][:70], x["cls"], x["jq"][:70], x["jaq"][:70]) for x in bad]))
    w("")
    w("Probes that matched: " + ", ".join(x["label"] for x in sp if x["cls"] == "same") + ".")
    w("")
    w("## 4. Command-line flags and input handling")
    w("")
    w("`same` = same stdout and exit code; `differs` = both accept it but output differs; `unsupported` = jaq rejects it.")
    w("")
    rows = []
    for x in flags:
        d = FLAG_DEC.get(x["label"], ("D", "Open", "not classified"))
        rows.append((x["label"], x["cls"], "%s/%s" % (x["jq_rc"], x["jaq_rc"]), d[0], d[1] + " (proposal)", d[2]))
    w(md_table(["flag or input case", "jaq vs jq", "exit jq/jaq", "jx class", "Decision", "cost class and reason"], rows))
    w("")
    # checklist
    w("## 5. Decision checklist (edit the proposals here)")
    w("")
    w("Numbers are jq.test cases that carry the tag; `unlocks` counts cases whose hardest tags are all Stage 2, Stage 3, Later or this Open tag (so enabling only this one tag would make them possible).")
    w("")
    byd = defaultdict(list)
    for t in tags:
        byd[t["decision"]].append(t)
    for d in ["Stage 2", "Stage 3", "Later", "Open", "Skip"]:
        w("### %s" % d)
        w("")
        for t in byd[d]:
            n = len(bytag.get(t["tag"], [])) if t["tag"] != "core" else N
            if d == "Open":
                unl = sum(1 for c in cases if t["tag"] in c["tags"] and all(
                    x == t["tag"] or next(y for y in tags if y["tag"] == x)["decision"] in ("Stage 2", "Stage 3", "Later") for x in c["tags"]))
                w("- [ ] `%s` (class %s): %d cases carry it, %d unlocked on their own. Cheapest way: %s" % (t["tag"], t["cls"], n, unl, t["reason"]))
            else:
                w("- `%s` (class %s): %d cases. %s" % (t["tag"], t["cls"], n, t["reason"]))
        for g, k, dd, why, names in BUILTIN_GROUPS:
            if dd == d:
                w("- builtin group `%s` (class %s): %s" % (g, k, why))
        w("- flags: " + (", ".join("`%s`" % k for k, v in FLAG_DEC.items() if v[1] == d) or "none"))
        w("")
    w("Coverage if exactly the decision sets are built: Stage 2 only %s, Stage 2+3 %s, + Later %s, all except Skip %s (see section 2)." % (pct(s2, N), pct(s23, N), pct(s23l, N), pct(sall, N)))
    w("")
    w("## 6. How to rerun")
    w("")
    w("```")
    w("# scratch directory outside the repo; downloaded files are data, run Python with -I")
    w("mkdir D:\\tmp\\w\\jqcompat")
    w("curl -sSfLo D:\\tmp\\w\\jqcompat\\jq.test https://raw.githubusercontent.com/jqlang/jq/jq-1.8.2/tests/jq.test")
    w("# module test fixtures: the files under tests/modules at the tag, saved to D:\\tmp\\w\\jqcompat\\mods")
    w("curl -sSfLo D:\\tmp\\w\\jqcompat\\manual18.yml https://raw.githubusercontent.com/jqlang/jq/jq-1.8.2/docs/content/manual/v1.8/manual.yml")
    w("python -I tools/jqcompat.py cases    --test D:\\tmp\\w\\jqcompat\\jq.test --modules D:\\tmp\\w\\jqcompat\\mods --out D:\\tmp\\w\\jqcompat\\o")
    w("python -I tools/jqcompat.py builtins --manual D:\\tmp\\w\\jqcompat\\manual18.yml --out D:\\tmp\\w\\jqcompat\\o")
    w("python -I tools/jqcompat.py flags    --out D:\\tmp\\w\\jqcompat\\o")
    w("python -X utf8 -I tools/jqcompat.py report --out D:\\tmp\\w\\jqcompat\\o --md docs/jq-feature-matrix.md")
    w("```")
    w("")
    w("`--jq` and `--jaq` choose the binaries (defaults: the real jq.exe under chocolatey, `jaq` on PATH). The `cases` run takes about a minute. "
      "Tags and proposed decisions live in tools/jqcompat_tags.tsv and tools/jqcompat_decisions.py; edit them and rerun `report` only (no reruns of the tools needed).")
    w("")
    w("## 7. What was not verified")
    w("")
    w("- Tagging is heuristic: a case with several features is assigned the hardest class and decision among its tags; some tags (`arith`, `comma-alt`, `try-catch` via `?`) over-match, so coverage numbers are rough.")
    w("- Class/decision coverage is the share of cases *within* the scope, not a promise that jx output would match: jx also needs jq's error text only if the owner decides so (design 10.2).")
    w("- Only jq.test was used; tests/man.test, tests/onig.test and tests/optional.test were not run. Real jq.test also has a few directives not exercised by this runner (`%%FAIL IGNORE MSG` is treated as a must-fail case; error text is never compared).")
    w("- jaq failing to compile counts only the process exit code 3; jaq's own error classes were not split further. Spot checks and flag probes are one input each, on Windows; Linux behavior may differ.")
    open(a.md, "w", encoding="utf-8", newline="\n").write("\n".join(L) + "\n")
    print("wrote", a.md, len(L), "lines")


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
