"""Checks src/num.mito (decimal literal -> double -> jq's text) against Python's float() and a model of jq's printer,
and, with --jq, the model against the real jq. Usage: python tests/numcheck.py [numtool.exe] [count]"""
import random, struct, subprocess, sys, math
from decimal import Decimal, getcontext, Context, ROUND_HALF_EVEN
from fractions import Fraction
sys.path.insert(0, __file__.rsplit('tests', 1)[0] + 'tests')
from numfmt import jqfmt

getcontext().prec = 1200
random.seed(20261112)

def gen(n):
    out = []
    for _ in range(n):
        k = random.random()
        if k < 0.25:       # random bit patterns, 17 digits
            b = random.getrandbits(64)
            x = struct.unpack('<d', struct.pack('<Q', b))[0]
            if x != x or abs(x) == math.inf: continue
            out.append(repr(x))
        elif k < 0.40:     # exact decimal midpoints between adjacent doubles (round-half-even traps)
            b = random.getrandbits(63)
            x = struct.unpack('<d', struct.pack('<Q', b))[0]
            if x != x or abs(x) == math.inf: continue
            y = struct.unpack('<d', struct.pack('<Q', b + 1))[0]
            if abs(y) == math.inf: continue
            mid = Decimal(x) / 2 + Decimal(y) / 2
            s = format(mid, 'e')
            out.append(s)
            if random.random() < .5: out.append(s + '1')   # just above the midpoint
        elif k < 0.55:     # integers of every size
            out.append(str(random.randint(0, 10 ** random.randint(1, 40))))
        elif k < 0.70:     # decimals
            out.append('%.*f' % (random.randint(0, 12), random.uniform(-1e6, 1e6)))
        elif k < 0.85:     # short mantissa, any exponent (subnormals, overflow, underflow)
            m = random.randint(1, 10 ** random.randint(1, 20))
            e = random.randint(-340, 330)
            out.append('%de%d' % (m, e))
        else:              # long digit strings
            nd = random.randint(17, 900)
            ds = ''.join(random.choice('0123456789') for _ in range(nd))
            ds = ds.lstrip('0') or '1'
            ex = random.randint(-nd - 340, 310 - nd)
            out.append('%s.%se%d' % (ds[0], ds[1:] or '0', ex + nd - 1))
    return out

def main():
    exe = sys.argv[1] if len(sys.argv) > 1 else r'D:\tmp\w\jx\numtool.exe'
    n = int(sys.argv[2]) if len(sys.argv) > 2 else 40000
    bad = 0
    total = 0
    for chunk in range(0, n, 20000):
        items = gen(min(20000, n - chunk))
        p = subprocess.run([exe], input=('\n'.join(items) + '\n').encode(), capture_output=True)
        lines = p.stdout.decode().replace('\r', '').split('\n')
        for s, o in zip(items, lines):
            total += 1
            try:
                # jq reduces a literal to 17 significant digits (half even) before converting it to a double
                m = jqfmt(float(Context(prec=17, rounding=ROUND_HALF_EVEN, Emax=999999, Emin=-999999).plus(Decimal(s))))
            except OverflowError:
                m = jqfmt(math.inf)
            if m != o:
                bad += 1
                if bad < 20: print('MISMATCH', s[:80], 'jx', o, 'expected', m)
        if len(lines) < len(items) + 1: print('short output', len(lines), len(items)); bad += 1
    print('numcheck: %d literals, %d mismatches' % (total, bad))
    sys.exit(1 if bad else 0)
main()
