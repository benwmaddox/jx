#!/usr/bin/env python3
"""The jq.test driver: runs the cases of jq 1.8.2's tests/jq.test through jx (using tools/jqcompat.py's parser and classifier) and
reports them by class and by tag. The test file is data: fetch it to a scratch folder (D:/tmp/w/jqtest/jq.test, not in the repo) and never run it.
usage: python -I tests/jqtest.py [--exe jx.exe] [--test jq.test] [--tag TAG] [--show N] [--line N] [--reasons]
  differ and error cases are listed (they must be zero except for documented differences); --reasons groups the rejected ones."""
import argparse, importlib.util, os, sys
from collections import Counter
from concurrent.futures import ThreadPoolExecutor

HERE = os.path.dirname(os.path.abspath(__file__))
spec = importlib.util.spec_from_file_location("jqcompat", os.path.join(HERE, "..", "tools", "jqcompat.py"))
jc = importlib.util.module_from_spec(spec); spec.loader.exec_module(jc)

ap = argparse.ArgumentParser()
ap.add_argument("--exe", default="D:/tmp/w/jx/jx3.exe")
ap.add_argument("--test", default="D:/tmp/w/jqcompat/jq.test")
ap.add_argument("--tag"); ap.add_argument("--show", type=int, default=30); ap.add_argument("--line", type=int)
ap.add_argument("--reasons", action="store_true"); ap.add_argument("--rejected", action="store_true")
a = ap.parse_args()
tags = jc.load_tags()
cases = jc.parse_test(a.test)
sel = [c for c in cases if (a.line is None or c["line"] == a.line) and (not a.tag or (c["kind"] == "ok" and a.tag in jc.tag_program(c["prog"], tags)))]

def one(c):
    import decimal
    decimal.setcontext(decimal.Context(prec=5000, Emax=999999999, Emin=-999999999, traps=[decimal.InvalidOperation]))
    rc, out, err = jc.run_jx_case(a.exe, c)
    cl, by, note = jc.classify_record(c, "jx", rc, out, err)
    return c, cl, note, out, err
res = list(ThreadPoolExecutor(max_workers=8).map(one, sel))
cnt = Counter(cl for _, cl, _, _, _ in res)
print("cases %d: pass %d, differ %d, rejected %d, error %d  (%.1f%% of the 531 runnable)" % (len(res), cnt["pass"], cnt["differ"], cnt["rejected"], cnt["error"], 100.0 * cnt["pass"] / 531))
shown = 0
for c, cl, note, out, err in res:
    if cl in ("differ", "error") or (a.rejected and cl == "rejected"):
        if shown < a.show:
            shown += 1
            print("%s line %d: %s\n   input %s\n   expected %s\n   got %s %s" % (cl.upper(), c["line"], c["prog"].replace("\n", " ")[:150], (c["input"] or "")[:80], c["expected"][:3], out[:100], (err or b"")[:120]))
if a.reasons:
    import re
    r = Counter()
    for c, cl, note, out, err in res:
        if cl == "rejected":
            m = re.search(rb"Stage \d: (.{0,50})", err)
            r[(m.group(1).decode("utf-8", "replace") if m else err[:50].decode("utf-8", "replace"))] += 1
    for k, v in r.most_common(60): print("%5d  %s" % (v, k))
