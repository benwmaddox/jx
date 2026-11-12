# jx bytecode engine: measurements and design

Status: design and measurement only (2026-11-12). Nothing in `src/` changed. Decision taken by the owner: a **bytecode interpreter replaces the tree
walker** (`run`, `evs`, `run_unit`, `terminal` in `src/eval.mito`) and the end state has **one engine**, with full parity. A native-code backend
(TinyCC or clang) is an optional later project (section 8). Every claim not measured here is marked **(unverified)**.

Machine and method: Windows 11, 22 logical cores, other users' processes were running (medians of 25 alternating runs; the noise between
two identical runs was about 1-2 ms, in two cases a stray 100 ms run was seen before a re-run, so single runs are not trusted). jx built from
`origin/main` at 56fa3d7 with `./build.sh` (clang -O3). Document: 190,000 rows from the generator of `bench/bench.py`, 15,506,573 bytes (the 16.3 MB of the README text is the same row format; sizes differ slightly). Scripts: `tools/bytecode-bench/`. Scratch builds of jx (smaller arrays, counters) lived under
`D:\tmp\w\jxbc-build` and are not in the repo.

## 1. Where the time goes

### 1.1 Method

The scanner reads the whole input before any result is written (`Out.text` is flushed once), so writing to NUL and to a file cost the same (identical
medians, section 1.4). To split the evaluator from the output without touching `src/`, each filter has an `| empty` twin that runs the same body and
prints nothing:

- scan = `.users | length` (no slots, no element body) minus startup;
- evaluator per element = (`F | empty`) minus (`.users | length`), divided by 190,000. This includes the scanner storing the spans the body asked for
  (slot fills), which cannot be separated without instrumenting the scanner, so it overstates the pure evaluator slightly;
- output = F minus (`F | empty`).
- startup = a tiny document (0.1 KB) with the same executable.

### 1.2 The table (15.5 MB, 190,000 rows, whole process, median ms)

| filter | total | startup | scan | evaluator (ns / element) | output | startup share | scan share | evaluator share | output share |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| `.users \| length` | 57.7 | 27.6 | 30.1 | 0 | 0 | 48% | 52% | 0% | 0% |
| `.users[] \| .age` | 76.6 | 27.6 | 30.1 | 10.2 (54) | 8.9 | 36% | 39% | 13% | 12% |
| `.users[] \| .n` | 77.6 | 27.6 | 30.1 | 9.9 (52) | 10.2 | 36% | 39% | 13% | 13% |
| `.users[] \| select(.age >= 85) \| .n` | 72.9 | 27.6 | 30.1 | 12.8 (67) | 2.4 | 38% | 41% | 18% | 3% |
| `.users[] \| .age + 1` | 111.0 | 27.6 | 30.1 | 15.8 (83) | 37.8 | 25% | 27% | 14% | 34% |
| `[.users[] \| .age] \| add` | 69.5 | 27.6 | 30.1 | 11.8 (62) | 0 | 40% | 43% | 17% | 0% |
| `.users[] \| if .age > 50 then .n else .addr.city end` | 88.4 | 27.6 | 30.1 | 30.7 (162) incl. output | (in evaluator) | 31% | 34% | 35% | (incl.) |
| `.users[] \| {n: .n, c: .addr.city}` | 145.4 | 27.6 | 30.1 | 33.1 (174) | 54.8 | 19% | 21% | 23% | 38% |
| `.users[0].n` (early exit) | 33.9 | 27.6 | 6.3 (rest, not split) | - | - | 81% | 19% (scan + rest) | - | - |

The `select` row: with a condition that is never true (`>= 1000`) the body costs 70.5 ms; with one that is always true (`>= 0`) 83.2 ms, so the
12.7 ms for 190,000 printed names is the output cost (67 ns each; `.n` prints 2.36 MB). Output bytes: `.age` 0.55 MB, `.n` 2.36 MB, `{n, c}` 6.05 MB,
`.age + 1` 0.55 MB. The `.age + 1` output is dominated by printing a double (200 ns each, against 47 ns for printing a span-valued number).

Instrumentation counters (scratch build, calls per run): `run` is called once per element for every scope body (190,001 in all the filters above),
`evs` 1 per element for `.age`, 2.2 for `select`, 5 for `{n, c}`, 3 for `.age + 1`, 2 for `if`; `node_val` (turning a slot into an arena entry) 1 per
element, 2 for `{n, c}`. So a body is **1 to 5 evaluator calls**, and the evaluator costs about 35 ns per `evs` call. That is not the cost of tree
walking (section 3.2 measures dispatch at 2-10 ns for a whole body); it is the work in the calls: allocating an arena entry per loaded slot, building
objects in the arena before printing them, formatting doubles.

### 1.3 Scan, and the 529 MB document (6.5 million rows, one run each of 3, medians)

Scan rate: `.users | length` takes 1052 ms for 529 MB, 1024 ms over startup, **516 MB/s**; the 15.5 MB document gives 30.1 ms, **515 MB/s**: the rate
is constant, the scanner is a single pass at about 1.9 ns per byte (0.52 bytes per ns).

| filter | total ms | scan ms | evaluator ms (ns/element) | output ms (ns/element) | share evaluator + output |
| --- | --- | --- | --- | --- | --- |
| `.users \| length` | 1053 | 1025 | 0 | 0 | 0% |
| `.users[] \| .age \| empty` | 1427 | 1025 | 374 (58) | 0 | 26% |
| `.users[] \| .n \| empty` | 1387 | 1025 | 334 (51) | 0 | 24% |
| `.users[] \| .n` | 1804 | 1025 | 334 (51) | 417 (64) | 42% |
| `.users[] \| select(.age >= 85) \| .n` | 1534 | 1025 | about 480 incl. 15% output (74) | - | 33% |
| `.users[] \| {n: .n, c: .addr.city} \| empty` | 2297 | 1025 | 1244 (191) | 0 | 54% |
| `.users[] \| {n: .n, c: .addr.city}` | 5239 | 1025 | 1244 (191) | 2942 (453) | 80% |

Two things differ from the small document: the evaluator per element is the same (51-58 ns, 191 ns), so it scales linearly; the output of `{n, c}`
is 453 ns per row against 288 ns on the small document. The output is a 192 MB buffer that is touched page by page for the first time (page faults;
**unverified** as the cause, but `.n` at 64 ns per row against 47-67 on the small document shows no such effect for a smaller 2 MB output per 16 MB
input), so the output cost of large results grows beyond linear. This is the 5.4 s of the README.

### 1.4 Output sink

| filter | to NUL | to a file |
| --- | --- | --- |
| `.users \| length` | 57.7 | 57.4 |
| `.users[] \| {n: .n, c: .addr.city}` | 146.0 | 147.4 |
| `.users[] \| .age + 1` | 111.8 | 111.3 |

The write system call is not visible (6 MB written once); output cost is formatting and the page faults of the buffer, not the sink.

### 1.5 Startup (tiny document, 40 alternating runs, median ms)

| build | ms | what changed |
| --- | --- | --- |
| Mitochondria hello world (same `args` and 4 GiB stdin reservation, no state) | 11.9 | process creation floor of a Mitochondria executable |
| jx as built | 27.3 | |
| Val arrays 4.2 M entries instead of 19.9 M (`REG0` 1 M) | 22.4 | -4.9 ms: 15.7 M fewer entries (38 bytes each) = **0.31 ms per million entries** (about 0.008 ms per MB) |
| `Out.text` 64 MiB instead of 1 GiB | 21.9 | -5.4 ms: **5.6 ms per GiB** (the README says 10; this machine now measures 5.6) |
| both | 13.7 | -13.6 ms |
| both, plus `Ev.scr` and `ptx` 1 MiB instead of 16 MiB | 13.5 | -0.2 ms |
| jaq 3.1.2 / jq 1.8.2 (real exe) | 13.2 / 9.6 | |

So of jx's 27.3 ms: 11.9 ms is the process floor, **13.6 ms is committing arrays that a tiny document never touches**, and 1.8 ms is everything
else (compile of the filter, the scan, the output). Reserving instead of committing would bring jx to about 13.5 ms (jaq's level) without touching
the evaluator at all. At 15.5 MB the same 13.6 ms is 9-23% of the total; at 529 MB it is nothing.

### 1.6 Conclusion of the profile

- The scanner is the floor: 30 ms of 57-145 ms at 15.5 MB, 1.0 s of 1.05-5.2 s at 529 MB. A different evaluator cannot go below it.
- Startup is 13.6 ms of waste out of 27.6, entirely arena commit; it is independent of the evaluator and is the cheapest 14 ms available.
- The evaluator (the part bytecode replaces) is 10-33 ms at 15.5 MB, **13-23% of the total**, and 25-55% of the *time after the scan*. If it were
  infinitely fast, `.n` would go from 77.6 to 67.7 ms (-13%), `select` from 72.9 to 60.1 (-18%), `{n, c}` from 145.4 to 112.3 (-23%).
- Output is as large as the evaluator for numbers computed from doubles (38 ms) and larger for constructed objects (55 ms, 453 ns per row at
  529 MB). It is only partly an evaluator cost: part of it is the arena round trip (build the object, then print it), which a bytecode design can
  remove by emitting while evaluating (section 4.7); formatting a double cannot be removed.
- **Honest summary:** a bytecode interpreter as a faster *dispatcher* gains little (tens of ms at 16 MB, a few percent at 529 MB). The gains that
  exist are in what the bytecode makes possible: no arena entry per loaded slot (spans in registers), objects written straight to the output, no
  per-element terminal setup, and a startup that does not commit memory. Those are worth doing; they are worth doing in the order of section 9.

## 2. Native-code ingredients (option B measurements)

Measured in WSL (Ubuntu 22.04, clang 18.1.3, TinyCC 0.9.27 from `~/tcc`, libtcc linked statically, no stdlib headers: the generated C declares what it
uses). The Windows `libtcc.dll` that Mitochondria embeds was not run here; the numbers should be similar **(unverified)**.

### 2.1 Compile time

| C size | libtcc in memory (warm, best of 50) | libtcc cold (first compile in the process) | `tcc -c` process | `clang -O1 -c` process | `clang -O3 -c` process |
| --- | --- | --- | --- | --- | --- |
| 62 lines | 0.09 ms | - | 2.4 ms | 21.6 ms | 24.4 ms |
| 305 lines | 0.31 ms | 0.61 ms | 3.1 ms | 26.4 ms | 28.6 ms |
| 1007 lines | 1.08 ms | - | 4.2 ms | 26.2 ms | 23.5 ms |

(The clang numbers are dominated by starting the compiler; they say "tens of ms per filter", not that 1000 lines compile faster than 300. Linking a
loadable module or an executable would add more, not measured. A clang cache keyed by filter hash would pay this once per distinct filter.)

### 2.2 TinyCC memory

| C size | malloc calls | realloc | free | allocated in total | peak live | process max RSS |
| --- | --- | --- | --- | --- | --- | --- |
| 62 lines | 127 | 66 | 61 | 1.9 MB | 1.8 MB | 2.3 MB |
| 305 lines | 237 | 132 | 169 | 2.0 MB | 1.9 MB | 2.6 MB |
| 1007 lines | 552 | 298 | 481 | 2.4 MB | 2.1 MB | 3.2 MB |

About 1.8 MB is a fixed cost of `tcc_new` (its symbol and section tables), then roughly 0.5 KB per generated line. Not all blocks are freed until
`tcc_delete` (live memory is released then; the code stays valid until the state is deleted). jx's runtime rule is "no allocation after startup":
libtcc breaks it by design (hundreds of malloc/realloc calls), so it would have to run before the arenas are declared fixed, or inside the host's
allocator **(unverified how the Mitochondria `tcc.rs` embedding handles this for `--tcc` builds; read it before choosing)**.

### 2.3 Per element run speed of a small body (ns per element, best of 30 passes over 190,000 elements, in-cache arrays)

The body is the part after the scanner: load `age` and name spans from per-element arrays, compare, copy bytes to an output buffer with `memcpy`.
Native = a function `int body(Ctx*, i64 i)` called once per element through a pointer. Interpreter = 5-8 instructions of `{op, a, k}`.

| body | clang -O3 | clang -O1 | TinyCC | interpreter, switch | interpreter, computed goto |
| --- | --- | --- | --- | --- | --- |
| `select(.age >= 85) \| .n` (15% hit) | 2.0 | 2.0 | 1.9 | 3.5 | 2.8 |
| `if .age > 50 then .n else .city` | 3.4 | 3.4 | 4.8 | 6.2 | 5.4 |
| `{n: .n, c: .city}` (text built from 3 pieces) | 4.6 | 5.1 | 12.7 | 14.4 | 9.9 |

(A first version using byte-by-byte copy loops in the generated C made TinyCC 3-4 times slower than the interpreter, 44 ns against 15; with
`memcpy` calls as above the numbers are those shown. Generated code that inlines loops is where TinyCC's missing optimizer shows.)

### 2.4 What the numbers say

- A whole body costs **2-14 ns per element in every variant, against 50-190 ns per element measured in jx**. The difference is not instruction
  dispatch; it is the arena entries, the generic comparison and printing code, and the slot machinery around the body. A compiled body that still
  calls those helpers would save the 1-5 ns of dispatch of a body and nothing else.
- TinyCC code is **not faster than a computed-goto interpreter** for these bodies: equal on the simplest, 12% faster on `if` only because the
  interpreter pays two extra dispatches, 28% slower on construction. clang -O3 is 1.4-2x faster than the interpreter on all three: 1-5 ns per element,
  i.e. 0.2-1 ms over 190,000 elements; its compile cost is about 25 ms per distinct filter, so the break-even is 5-25 million elements (about
  2-10 GB of input at 400 bytes per element) **(estimated from these measurements, not run end to end)**.
- The numbers are a best case (data in cache, no scanner, no arena); the real interpreter will be slower than the micro-benchmark per instruction.

## 3. Starting point: what Stage 2 is

(From the source; line counts of 56fa3d7.) `compile.mito` (1556 lines) parses the filter into the expression tree `ak/aa/ab/ac/ad/nx/at` (up to 1023
nodes) and analyzes it: it builds the path automaton (256 nodes), decides which values need a slot (`want`), finds the iterations whose element
ends run a body (a *scope*: `s_iter, s_par, s_body, s_term, s_reg, s_depth, s_own, s_next, s_play`, up to 32), and the registers (collected lists,
add and count folds, `r_kind/r_depth/r_own`, up to 64). `scan.mito` (366) calls `run_unit` at the end of each element of a scope's iteration and
`run_root` at the end of the document or at an early exit. `eval.mito` (2148 lines) is values and helpers (about 1550 lines: arithmetic, comparison,
numbers, builtins, `materialize`, `copy_deep`, `tojson_of`, errors) and the walker `run`/`evs`/`terminal`/`run_unit`/`run_root`/`emit_outer` (about 600
lines). The walker is continuation-passing: each node has `nx`, the node that takes its outputs, `-1` meaning the terminal of the enclosing scope body;
`run(e, v)` recurses on generators (`COMMA`, `ALT`, `RANGE`, `LIMIT`, `UNTIL`, `REDUCE`, `TRY`) and loops for straight-line forms; `evs(e, v)` is the
single-output evaluator for operands; terminals are a dynamic stack `tk/ta/tc/th/tn` (1 print, 2 register, 3 add, 4 count, 6 alternative, ...);
errors are `jj.ev.err` (1 a jq error, 2 not supported) with `stopto` for `limit`.

What must stay: the scanner and its slots, the arena (`Val`) and the value helpers, `out.mito`, `num.mito`. What goes: the walker and the terminal
stack.

## 4. The bytecode engine (option A)

### 4.1 Principles

1. **Replace the walker, keep the values.** Registers hold the same arena handles (`i64` entries of `Val`) the helpers already take. Every arithmetic,
   comparison, builtin, construction and printing helper is reused unchanged by the instructions, so the numbers (jq-exact literals, decimal compare,
   shortest round trip printing), the error texts and UTF-8 replacement stay bit-identical by construction. Only control flow changes.
2. **Static everything.** What the walker decides dynamically (the terminal kind, which register a result goes to, which continuation runs) is fixed at
   lowering time, so an instruction knows where its result goes. No terminal stack.
3. **Straight-line where the walker's `evs` is, loops where its `run` recurses.** An expression that yields exactly one value (path, literal,
   arithmetic of such, comparison, `if` of such...) lowers to a straight run of instructions into a register. A generator lowers to a loop or to a
   subroutine call per output (section 4.4).
4. **Fixed arrays, no allocation, no recursion** (Mitochondria allows 64 nested calls; the interpreter loop is one function with an explicit return
   stack). The current "expressions nested too deeply" limit (60, from `tp`) becomes the size of the explicit stacks.
5. **No hybrid.** The product has one engine. During the migration the tree walker is kept as a *build-time* choice (section 9), never as a run-time
   fallback.

### 4.2 Program layout (all fixed arrays in `Filt`, struct-of-arrays like the tree)

| array | size | content |
| --- | --- | --- |
| `iop: u8[]`, `ia, ib, ic: i32[]` | 8192 instructions | opcode and three operands (register numbers, constant ids, jump targets (absolute instruction index), node ids) |
| `ipos: i32[]` | 8192 | filter text position of the instruction, for error messages and for the disassembler's source column |
| `entry: i32[32]` | one per scope | first instruction of the scope's body; `root_entry` for the end-of-document program |
| `kval: i64[]`, `kcount` | 1024 | constant pool: handles of entries (literals, type names, empty array, `null`, `true`, `false`) built once by the lowering in the arena's permanent region (depth 0), so `CONST r, k` is a copy of an `i64` |
| `ktab: i32[]` | 64 | try handler table, see 4.6 |
| `nreg` per scope, `nreg_total` | 256 registers | register file: `rv: i64[256]` handles; scope bodies and the root share one numbering (variables of the document level stay visible inside bodies) |

Instructions are 8-byte-class records, not variable length: decoding is three array loads at one index, jumps are an index, and the disassembler
and the lowering both stay trivial. Estimated size of a large filter: 1023 tree nodes lower to about 3-4 thousand instructions **(unverified)**; 8192
leaves room.

### 4.3 Instruction set

`r` is a register, `k` a constant id, `n` an automaton node, `L` an instruction index, `f` a function or operator id. Families are numbered in
blocks of 16 opcodes so a new family never renumbers (section 4.9).

| family | instructions | semantics |
| --- | --- | --- |
| **0 control** | `NOP`, `HALT`, `JMP L`, `JT r, L`, `JF r, L` (truthiness: null and false are false), `JNIL r, L` | `HALT` ends the body (the scanner continues); an error raised or an early exit leaves via the unwind path |
| **1 data** | `MOV r, s`, `CONST r, k`, `LOADN r, n` (slot of automaton node n, with the deferred navigation check), `LOADROOT r` (`.` of a body = the element, or the document) | `LOADN` = `node_val(n)`: it raises the stored navigation error (4.8) only here, when executed |
| **2 operators** | `ADD, SUB, MUL, DIV, MOD r, a, b` (`ARITH f, a, b, r` in one opcode with `f` in operand if the table is tight), `NEG r, a`, `NOT r, a`, `CMP f, a, b, r` (six comparisons, result a boolean handle), `JCMP f, a, b, L` (fused compare-and-branch: the `select` and `if` hot path), `JCMPK f, a, k, L` (against a constant), `TRUTHY r, a` | all call the existing `arith`, `compare`, `eq` helpers, so number semantics are unchanged; `JCMPK` against a number literal uses the pre-parsed constant (decimal compare kept exact) |
| **3 navigation of built values** | `FIELD r, a, k` (`.a` on a value that is not a slot), `FIELDV r, a, b` reserved for computed keys, `INDEX r, a, k`, `SLICE r, a, lo, hi` | on spans of the document these reuse today's lazy re-scan helpers; on built values they index the arena chains |
| **4 builtins** | `FN f, a, r` (`length, type, keys, has, not, tostring, tonumber, toboolean`, the type selectors as `TYPEMASK`), `FN2 f, a, b, r` (`has`) | one dispatch into the existing builtin functions; types selectors `arrays objects ...` are a `JTYPE mask, a, L` instruction so `select`-like use does not build a boolean |
| **5 construction** | `ARRB r`, `ARRP r, a` (push), `ARRE r`; `OBJB r`, `OBJP r, k, a` (constant key), `OBJPK r, a, b` (computed key), `OBJE r` | build in the arena exactly as `materialize` does today; `{$x}`, `{a}`, `{"b c": ...}` lower to `OBJP` with the key constant; duplicate constant keys are resolved at lowering (last wins); computed keys use the existing replace-or-append |
| **6 generators** | `GOSUB L`, `RET`, `YIELD`-style gosub (4.4), `FORB r, a` (open an iteration over a built array/object/string-range source), `FORN r, L_end` (next element into r or jump), `RANGE`-forms `RNG r, a, b` (`range(n)` and two-argument), `STOPCHK L` | see 4.4 |
| **7 outputs** | `EMITP a` (print), `EMITR rg, a` (append to collector register rg), `EMITA rg, a` (add fold), `EMITC rg` (count fold), `EMITH rg, a` (hold, for `first`/`last`/`isempty`) | the terminal is chosen by the lowering: no dynamic terminal stack; `EMITP` is the only instruction that touches `Out` |
| **8 alternation, limits** | `ALTB c`, `ALTE c, L`, `LIMB c, n`, `LIMT c, L` (count an output, set `stop` when the limit is reached), `LIME c` | counters live in registers `c`; `first(f)` is `limit(1; f)`, `nth`, `skip`, `isempty`, `until` use the same family plus `JMP` loops |
| **9 errors** | `ERR a` (`error(v)`), `ERRN` (error from a failed helper: the helpers set `jj.ev.err`, the interpreter loop checks it after a helper call and goes to the unwind), `TRYB h`, `TRYE h`, `TRYOFF h`, `TRYON h` | see 4.6 |
| **10 variables** | none needed: `as $x` is `MOV` into the variable's register; `$x` is a read of that register. `LOADV` is reserved for variables defined outside (section 4.9) | |
| **11 scope/frame** | `SCOPEB s` / `SCOPEE`, `RESETD d`, `PLAY rg` (play a collector register back at its place, the `s_play` tree node) | `RESETD` rewinds the arena at depth d (`jj.v.top[d] = base[d]`), which `run_unit` does at the end of each element today; it is the last instruction of a body |
| **12 specializations** | superinstructions chosen after profiling (section 9, stage 7): `LOADN+JCMPK`, `LOADN+EMITP`, `LOADN+LOADN+OBJ` | optional, never needed for correctness |
| **13-15 reserved** | Stage 3 families (4.9) | |

### 4.4 Generators: loops with explicit resume points, no backtracking machine

The tree gives every node a continuation `nx` (the node that consumes its outputs). The lowering keeps exactly that structure, but a continuation
becomes a **local subroutine**:

- A node that yields at most one value (the walker's `evs` domain, plus `select`, `empty`) is straight-line code that falls through to its continuation
  code.
- A node that can yield several values (`,`, `.[]` on built values, `range`, `//` with a generator, `limit`, `until`, `reduce` bodies, an operand that
  is a generator, `if` with a generator condition) emits its continuation once, as a subroutine ending in `RET`, and each place that yields does
  `GOSUB Lcont` with the value in the continuation's input register, followed by `STOPCHK Lstop` (jump to the unwind when `stop` is set).
  `(a, b) | c` is `a-code; GOSUB c; STOPCHK; b-code; GOSUB c; STOPCHK; ... RET`; `c` appears once, not once per output. `.[] | c` on a built array is
  `FORB; Lloop: FORN Lend; GOSUB c; STOPCHK; JMP Lloop`.
- The return stack is an explicit array of 64 entries (`rsp`, `rpc`, saved `try` depth and arena marks): a recursion limit by construction, not by
  the host stack. A depth overflow is the named error "expressions nested too deeply" as today.
- Cartesian orders of jq (`(1,2) + (10,20)`: the right operand is the outer loop) are produced by lowering the operands in the same order the walker
  evaluates them (`BIN` with generator operands); the corpus has these cases (`tests/filters*.txt`) and the exit test compares the output order.

Resume points are the loop labels and the instruction after a `GOSUB`; nothing else needs saving, since registers live in the one register file and
the generator's own state (the `FORN` cursor, the `range` counter, the `limit` count) is in registers. This is why a general backtracking machine is
not needed: every generator in the supported language is a loop over a bounded source, as design.md 5.5 already said.

### 4.5 Scopes, registers and early exit

- The scanner stays as it is: at the end of each element of a scope's iteration it calls `exec(entry[s])` instead of `run_unit`. `exec` loads the
  element into the scope's input register (`LOADROOT`), runs to `HALT`, then `RESETD`. The `s_term` values 1-4 become the instruction at the end of the
  body (`EMITP`, `EMITR`, `EMITA`, `EMITC`); register playback (the scope is not at the head: `[.users[] | .age] | ...`, `.a[] as $x | ...`) is the
  collector register plus a `PLAY` in the root program at the place `s_play` marks today.
- Collector registers keep their depth (`r_depth`) and owner (`r_own`) and the generation stamps `rg`, deferred errors `rerr/rerrv` of the scope body
  (jq runs the body when its result is consumed, so an error of a body whose result is never read must not fire): unchanged, they are what
  `reg_touch` does today.
- `exec` runs the body to completion or to an error; `rc` conventions as `run_unit` today (0 continue, 1 error, 2 exit).
- Early exit (`first(.users[]|...)`, `.users[0].n`, `limit`) stays the scanner's mechanism (`exit_depth`, `nwant`: all slots filled). The compiler
  additionally marks a scope with `stop_after = n` when a `limit` or `first` sits directly over its iteration; the instruction `SCANSTOP` at that
  point sets `Scan.exit_depth` so the scanner stops reading. Nothing new in the scanner.

### 4.6 `try`/`catch`, `?`, errors

An error is raised by `ERR`, or by any helper that sets `jj.ev.err = 1` (the existing `error value`, `emsg`, `rawmsg`, `errv` fields keep their meaning
and the messages stay byte for byte). The interpreter loop, after an instruction that can fail, takes the **unwind path** when `err != 0`:

- `TRYB h` pushes a handler frame {handler table row `h`, return-stack depth, arena top at the depth, `Out.text` length (for the `?` after a partial
  construction, though jx never prints partial results when the run fails), `active = 1`}. `TRYE h` pops it on normal completion.
- Unwind: pop frames from the top; the first frame with `active = 1` receives the error: the return stack and arena are cut back to the frame's marks
  and control jumps to `ktab[h].handler` (the `catch` body with the error value in a register, or `NOP` for `?`).
- **jq's `try` does not catch errors raised by what consumes its outputs** (the walker has `errfrom` for it). Every `GOSUB` out of a `try` body is
  wrapped `TRYOFF h; GOSUB c; TRYON h`, so while the continuation runs the frame is inactive and the error passes through to an outer handler.
  `ktab[h]` records the handler address; `break`-style special errors do not exist in the supported subset.
- `error(null)` and "break out of a try on `error` with a catch": follow the walker; the corpus (`tests/filters*.txt`, jq.test) covers them
  **(the exact lowering of every case is for the implementation to confirm against the corpus)**.
- A run that ends with an unhandled error leaves with exit code 5 and the stored message, exactly as today (`main` is not touched).

### 4.7 Spans as the fast path and writing without the arena

Stage 2 turns every loaded slot into an arena entry (`node_val`, one per slot per element) and builds every constructed object in the arena before
`out.mito` prints it. The profile (1.2) puts 35 ns per `evs` and 288-453 ns per constructed row there. The design allows both savings, **after**
parity, as additive instructions (section 9, stage 7), because they do not change semantics:

- **Span registers.** A register may hold either a handle or an unmaterialized slot reference ("slot n of generation g"). `EMITP` of a slot reference
  prints from the slot's span with no arena entry; a comparison with a constant reads the slot directly (`JCMPK` on `LOADN`). Any other consumer
  materializes on first use. Whether the register file needs a tag byte per register (`rt: u8[256]`) or the instruction variants encode it
  statically is a lowering decision; the static version is preferred (no tag test in the loop).
- **Streaming construction.** When an object/array constructor's only consumer is `EMITP` and all keys are constants, lower to
  `OUTB`, `OUTK k`, `OUTV a`, `OUTE` writing to `Out.text` (compact or indented; the indentation state is `Out`'s) and skip the arena build.
  Constant duplicate keys are resolved at lowering; computed keys or a constructor feeding `//`, a comparison or `try` keep the arena build. A
  failing value in the middle leaves a partial output that is discarded because jx writes nothing when a run fails; under `try` the `TRYB` frame's
  saved `Out.text` length truncates it.

Expected effect **(unverified, estimated from section 1)**: spans save most of the 10-20 ns of `node_val`; streaming construction could remove
the 33 ms evaluator and part of the 55 ms output of `{n, c}` at 15.5 MB (the object build and re-read), bringing it from 145 ms to about
100-115 ms. The scan (30 ms) and startup (after stage 0, 14 ms) remain.

### 4.8 Deferred navigation errors and last-key-wins

- The scanner records, per automaton node, the tag of a value that could not be navigated below it (`serr`, `serrg`, `serri`), exactly as now. It
  never raises. `LOADN` (and `FIELD`/`INDEX` on slots) checks `Scan.anyerr` and then `nav_check(n)`; the error is raised when and only when the
  instruction executes, so `select(false) | .a.b`, `.a? // 1`, `try .a.b` and `[.a.b?]` keep their results. The lowering must not move a `LOADN`
  across a branch, a `TRYB` or a generator boundary (it may drop one whose value is dead only if the load cannot fail, which it cannot prove
  in general: keep it).
- **Last key wins** stays in two places: the scanner (a later fill of a slot overwrites, `sgen`) for duplicate keys in the document, and constructors
  (`OBJP` with a repeated constant key resolved at lowering; computed keys with the existing replace-or-append helper).
- `--validate`, UTF-8 replacement and number printing are properties of the scanner and `out.mito` and do not change.

### 4.9 Reserved families: how the Stage 3 items fit (no redesign)

| Stage 3 item | what is added | where it fits |
| --- | --- | --- |
| `reduce f as $x (init; update)` | already supported today as `K.REDUCE`: `init` into the accumulator register, the source generator as a `GOSUB` loop whose continuation is `MOV $x; update-code; MOV acc`; `foreach` adds `EMIT` per iteration | family 6 (generators), registers; no new instruction. `foreach` with 3 arguments the same |
| `def f(a): body;` with inlining | the lowering inlines the body at each call site with parameters bound to registers (closure parameters become `GOSUB` subroutine entries: a parameter is a filter evaluated at its use, i.e. a local subroutine called with the caller's input register); recursion becomes `CALL L` / `RET` with the return stack (family 6 already has `GOSUB`; `CALL` adds a frame with its own register window: `FRAME n` / `UNFRAME`), a bounded depth | families 6 and 10; `LOADV` for variables of the enclosing definition |
| destructuring `. as [$a, {b: $c}]`, `?//` | a pattern lowers to `INDEX`/`FIELD` loads into variable registers; the error rules of `?//` are `TRYB` frames | families 3, 10, 9 |
| `sort`, `sort_by`, `group_by`, `unique`, `min/max` | collector registers already exist (`EMITR`); the new instructions `SORT rg`, `SORTBY rg, key_reg`, `GROUP rg`, `UNIQ rg`, `MINMAX f, rg, r` operate on a collector's arena chain with jq's order (helpers exist: `compare`) | new block 13 (collectors); `sort_by(f)` evaluates `f` per element into a key collector in lockstep |
| math (`floor sqrt pow log ...`) | `FN` with more function ids; a `MATH f, a, r` opcode if the table of ids outgrows the switch | family 4 |
| string functions, `@format`s, interpolation, regular expressions | `FN2/FN3` families; `STRB/STRP/STRE` string builder like `ARRB`; regexes a new block 14 | family 4, new block 14 |
| `path()`, `paths`, `getpath`, `setpath`, `del`, assignment `=`, `|=` | `PATHB`: a path-tracking mode where `FIELD/INDEX/FORN` also push onto a path stack register; `GETP/SETP/DELP r, a, p` | new block 15; needs the scanner to keep path information (a Stage 3 design question, not a bytecode one) |
| `label`/`break` | a handler-table row type: `BREAK id` unwinds like an error to the row with that id | family 9 |
| `limit` with non-constant counts, `input`, `$ENV`, `import` | registers and `FN` ids; `input` needs the scanner (out of scope here) | |
| `--explain` | the disassembler (4.10) | |
| `getpath`/`..` (recursive descent) | `RECB r, a` / `RECN` a generator over a built value's descendants with a bounded explicit stack | family 6 |

The two rules that keep these additive: **(1)** every value is an arena handle in a register; **(2)** every multi-output construct is a loop or
subroutine over registers; so a new filter is a new lowering rule plus, at most, a new helper call behind a new opcode in a reserved block.

### 4.10 Disassembler and `--explain` format

`jx --explain FILTER` prints the program and exits before reading input (Stage 3 flag, `option '--explain' is not supported yet` until then). The
format is stable text, one instruction per line, so it can be diffed and tested as a golden file:

```
filter .users[] | select(.age >= 85) | .n
automaton
  n0 document
  n1 .users            scope 0 iterates
  n2 .users[]          want: element
  n3 .users[].age      slot
  n4 .users[].n        slot
scope 0 body  iter n2  term print  regs 2          ; runs at the end of each element of .users[]
  0000  LOADN    r0, n3                      ; .age            col 21
  0001  JCMPK    lt r0, k0, 0004             ; >= 85           col 26   (k0 = 85)
  0002  LOADN    r1, n4                      ; .n              col 36
  0003  EMITP    r1
  0004  RESETD   1
  0005  HALT
root          regs 0
  0006  HALT
constants  k0 = 85
```

Columns: instruction index, mnemonic padded to 8, operands, `;` comment with the source text of the filter at `ipos` and the column, loop and
subroutine labels as `Lnnnn:` lines. Any `kval` constant prints as JSON. The disassembler is also the debugging tool of the stages (a `JX_DUMP`-like
flag during development, becoming `--explain` in Stage 3), and the golden files of `tests/` pin the lowering of the 60 reject-free forms.

### 4.11 Lowering from the tree (not from the parse)

The lowering is a pass **after** `compile.mito`'s analysis, over `ak/aa/ab/ac/nx` and the scope tables. Reasons: the analysis already decided slots, scopes,
registers, depths and the `nx` continuation structure, which is what the walker walks; a lowering from the parse would have to redo that analysis
and would risk divergence from the scanner's automaton (which must agree with the instruction `LOADN n` on node ids). The cost is that the tree
stays in memory (1024 nodes, kilobytes) and the lowering depends on the tree's invariants; fine. Algorithm: one recursive-free pass per scope body
with an explicit stack of (node, continuation label), emitting code for the node, and for a continuation that is reachable from several yield points
a subroutine (4.4). Constants are interned into `kval` as built once at startup. Every instruction gets the `at[node]` position for `ipos`. A
verifier pass checks that every jump target is in range, every register is written before read on every path, stacks cannot overflow statically
beyond the explicit limits, and every scope ends in `HALT` (cheap, runs once, finds lowering bugs before data does).

## 5. Startup plan (independent of bytecode)

Measured in 1.5: 13.6 ms of the 27.3 ms of a tiny run is array commit. Options, in order of preference; the first two are decisions for the owner
because the mechanism lives in the Mitochondria runtime:

1. **Reserve without commit.** If Mitochondria can declare arrays that are reserved and committed by page fault (on Windows `VirtualAlloc(MEM_RESERVE)`
   then commit in chunks as `top` grows, or just `MEM_COMMIT` without touching: the measured cost of 0.31 ms per million entries suggests the runtime
   does more than reserve, e.g. it zeroes or touches pages **(unverified: read the runtime's start code)**). Expected: jx at about 13.5 ms.
2. **Segmented arenas.** `Val` as a first segment (1 M entries) plus further segments allocated when a depth runs out: every access gets a
   segment lookup; rejected because it taxes every access.
3. **Smaller declared sizes** (measured: `REG0 = 1 M`, `Out.text` 64 MiB: 13.7 ms). It trades capacity: a collected list of more than 1 M entries
   and an output over 64 MiB become the named capacity errors. Only acceptable if a bigger build or the runtime option exists, because the 529 MB
   runs of the README (192 MB of output) need the capacity.

Stage 0 of section 9 takes whichever is possible and measures it. It needs no bytecode.

## 6. Tests as the regression suite

The acceptance bar of the whole effort: **every output, every exit code and every error message identical to Stage 2**, with timings recorded.

| suite | what it checks | how it is used |
| --- | --- | --- |
| `tests/run.py` | the corpus (`filters.txt`, `filters2.txt`, `filters_pretty.txt`, `filters_raw.txt`, `docs.txt`, `bad.txt`, `syntax.txt`, `reject.txt`, `xdiff.txt`) against jq's expected output | must stay identical after every stage; run before each commit |
| `tests/fuzz.py` | random filters and documents against jq | must stay at its current clean result; run with the same seeds before and after, and with new seeds |
| `tests/jqtest.py` | jq's own `jq.test`: **196 pass, 1 differ, 0 error of 531** (`docs/progress.md`) | must not lose a single pass: the milestone row is recorded |
| `tests/numcheck.py`, `numarith.py`, `numfmt.py` | number parsing, 1000 random pairs through every operator, formats | identical; they exercise the helpers the interpreter reuses, so they catch accidental changes to the arithmetic path |
| differential run (new, `tests/bcdiff.py`) | runs every corpus and fuzz filter through two builds (tree and bytecode, see section 9) and compares stdout, stderr and exit code | the strongest tool during migration: it runs without jq and covers all 60 reject cases (both must reject at the same position) |
| golden disassembly (new) | `--explain`/dump of each corpus filter | pins the lowering; a change is a reviewed diff |
| `tools/timing.py` / `tools/progress.py` | time and peak memory of the milestones (`docs/progress.md` sections 5-7) | every stage appends its row (label `bytecode-sN`) |

Nothing in this plan changes an expected output file. A stage that needs to change one is wrong.

## 7. Size and time

| piece | new lines (estimate **(unverified)**) | removed |
| --- | --- | --- |
| `prog.mito` (program arrays, constant pool, handler table) | 120 | |
| `lower.mito` (lowering and verifier) | 900-1300 | |
| `exec.mito` (the interpreter loop: dispatch, unwind, GOSUB stack, try frames) | 600-800 | |
| `dis.mito` (disassembler) | 200-250 | |
| `compile.mito` changes (expose the scope tables to the lowering, constants, `stop_after`) | 100 | |
| scanner hook (`exec` instead of `run_unit`) | 30 | |
| tests (`bcdiff.py`, golden, new corpus cases) | 400 | |
| deleted at the end: `run`, `evs`, `terminal`, `run_unit`, `run_root`, `emit_outer`, terminal stack fields | | about 600-700 |

Net about +1700 lines of code over the removed 650. Time: five to eight working days of agent time for stages 1-6, one to two more for stage 7, plus
review rounds **(unverified: judged from the size of the walker, which took the Stage 2 tags `stage2-core` to `stage2` to build)**.

## 8. Option B: native code, optional and later

Kept short because the measurements decide it. Facts: a body is 2-14 ns per element in every form (2.3), the jx per-element cost is 50-190 ns and is
in helpers a compiled body would still call, so native code saves at most about 1-5 ns per element (1-5% of the evaluator share, so below 1% of
a run). TinyCC is not faster than a computed-goto interpreter for these bodies. clang is faster but costs about 25 ms per filter (5-25 million
elements to break even). The only case with a real win would be filters whose per-element work is arithmetic-heavy and not helper-bound, none of
which exists in the supported subset today.

If it is ever built: a C emitter from the bytecode (one C function per scope body, instructions as statements, registers as locals, helpers as
calls), compiled ahead of time by clang into a cache keyed by (filter hash, jx build id), or in memory with TinyCC. It needs from Mitochondria:
loading generated code (`dlopen`/`LoadLibrary`, or the embedded libtcc path of `src/tcc.rs`), a stable C ABI to the runtime helpers
and the arena arrays (the generated code must index the same `Val` arrays), a way to let libtcc allocate (it makes 130-550 malloc/realloc calls),
and a decision about executing generated code (a cache directory writable by others is a code-injection path: verify a hash and permissions,
or compile only in memory). Startup per run: 0.3-1.1 ms with libtcc (2.1), a few ms to load a cached module, 25 ms plus to compile. Expected gain:
below the measurement noise at 16 MB, **unverified** beyond that. Recommendation: do not start it until stage 7 is measured and a profile of the
bytecode engine shows the dispatch loop, not the helpers, as the top cost.

## 9. Recommendation and staged plan

**Recommendation: build the bytecode engine as decided, but do startup first and design for the two things that save time (spans, streaming
construction), because dispatch alone saves little.** The evidence: the evaluator is 13-23% of a 15.5 MB run (1.6), startup waste is 13.6 ms (about 10-18%
of a 15.5 MB run, about half of a tiny run), and the whole native-code question moves 1-5 ns of 50-190 (2.4). Expected end result **(unverified,
from section 1)**: tiny document 27 -> about 14 ms; 15.5 MB `.n` 78 -> about 55-60 ms; `select` 73 -> about 50-55 ms; `{n, c}` 145 -> about 85-110 ms;
529 MB `{n, c}` 5.2 s -> about 2.5-3.5 s if streaming construction removes most of the 2.9 s of output; plain scanning unchanged at 516 MB/s.

**Migration without a hybrid.** The walker stays during stages 1-5 only as a *build-time* choice (`const Lim.ENGINE`: 0 tree, 1 bytecode), so the
same sources build two executables and the differential harness compares them. In the bytecode build, a filter form whose lowering does not exist
yet is an **error naming the form at lowering time** (`jx: bytecode: not lowered yet: FOLD`), never a silent switch to the walker. `main` ships the
tree engine (`ENGINE = 0`) until stage 5; stage 6 flips the default and deletes the walker and the constant. The old walker therefore lives for the
duration of the migration, with an end date: the merge of stage 6.

Every stage: all suites of section 6 pass in the tree build; the bytecode build passes every test that uses only the stage's forms and the
differential run shows no difference on them; the stage's timing row is appended to `docs/progress.md`.

| stage | adds (instruction families, filter forms migrated) | exit tests | benchmark |
| --- | --- | --- | --- |
| **0 startup** (parallel, Mitochondria side) | reserve-not-commit or smaller declared arrays (section 5) | `tests/run.py`, `jqtest.py` 196/531 unchanged; the 529 MB `{n, c}` run completes | tiny document ms, 15.5 MB, the six filters of 1.2 |
| **1 skeleton and scopes** | `prog.mito`, `exec.mito`, the loop and `RESETD`/`HALT`/`EMITP` terminals, `dis.mito`; families 0, 1, 7; forms: `.`, paths of slots (`.a.b`, `.[]` heads, slices of slots), literals, pipe, `select` with truthy conditions, `empty`, scope terminals 1-4 | differential run on the subset (hundreds of corpus filters: every filter whose tree uses only these kinds); golden dumps | `.users[] \| .n`, `select`, `.addr.city` vs tree: parity or better |
| **2 operators and conditionals** | family 2 (arithmetic, comparison, `JCMP/JCMPK`, `not`, `and`/`or`, negation), `if/elif/else`, `//` without a generator on the left; number tests | `numarith.py` and `numcheck.py` through the bytecode build, differential on the operator corpus | `.age + 1`, `if` filter |
| **3 construction and builtins** | families 4, 5 (`FN`, `ARRB..`, `OBJB..`), `map`, `add`, `length`, `type`, `keys`, `has`, `tostring`, `tonumber`, `toboolean`, type selectors, slices of built values, family 3; folds `FOLD` and register playback (`PLAY`) for scopes not at the head | differential, `docs.txt`, the `{n, c}` and `[.users[] \| .age] \| add` filters, `--validate`, UTF-8 and number printing tests | `{n, c}`, `add`, 529 MB `.users \| map(.age) \| add` |
| **4 generators** | family 6 (`GOSUB`/`RET`, `FORB/FORN`, `RNG`, `STOPCHK`), `,`, `//` with a generator, generators in operands (cartesian order), `range`, `until`, `.[]` on built values, operands that yield several values | differential, cartesian-order cases of `filters*.txt`, deep nesting limit test (the named error stays) | none specific; checks no regression |
| **5 control, errors and variables** | families 8, 9, 10: `limit/first/last/nth/skip/isempty`, `try/catch/?`, `error`, `as $x` including generator sources, deferred errors, `reduce`, early exit `SCANSTOP` | differential, `tests/jqtest.py` 196/531 identical, `fuzz.py` identical on the same seeds and 3 new seeds, `reject.txt`/`syntax.txt` same positions and codes | `.users[0].n`, `first(.users[]\|...)` early exit |
| **6 parity, switch and delete** | every form of the README feature table runs in bytecode; the tree build must show zero differences on the whole corpus, fuzz (at least 20 seeds) and `jq.test`; then `ENGINE` defaults to bytecode, then the walker, `terminal` stack, `ENGINE` and the differential harness's tree side are removed | all suites of section 6 identical; the milestone row; `git grep "fn evs\|fn run(\|fn terminal"` finds nothing | full table 1.2 and 1.3 (15.5 MB and 529 MB), peak memory |
| **7 speed** | span registers, streaming construction, superinstructions (4.7, family 12), constants pre-parsed; each one change at a time, kept only if it wins a benchmark | all suites after each change | the 1.2 and 1.3 tables; a change that does not win by more than the noise (2 ms at 15.5 MB) is reverted |

**First-stage task list (stage 1, for one implementation agent; no changes to the walker's behavior):**
1. Add `Lim.ENGINE` and `--dump-program` (hidden development flag) in `jx.mito`; build both engines from one source tree.
2. `prog.mito`: the arrays of 4.2 in `Filt`, `emit(op, a, b, c, pos)`, `intern_const(handle)`, the constant pool built in the permanent arena region.
3. `exec.mito`: `exec(entry, ...)` with `iop` dispatch for families 0, 1, 7; registers `rv: i64[256]`; `rc` convention of `run_unit`; wire the scanner's
   scope end (`scan.mito` line 173) and `run_root` to it when `ENGINE = 1`.
4. `lower.mito`: scope bodies and the root for the subset of 4.11 (ID, LIT, NODE, FIELD/IDX of slots, PIPE, SELECT, EMPTY, scope terminals 1-4); an
   unsupported kind returns "jx: bytecode: not lowered yet: <kind>" (exit 1).
5. `dis.mito`: the format of 4.10.
6. `tests/bcdiff.py`: for each corpus filter that lowers, compare stdout, stderr and exit code of the two builds; for a filter that does not lower,
   check the named error and skip. Report counts.
7. Run all suites of section 6 on the tree build (must be unchanged), the differential on the subset (0 differences), and append the stage 1 timing
   row to `docs/progress.md` (15.5 MB: the six filters of 1.2; tiny; peak memory).
8. Review point before stage 2: report the dispatch cost per element measured in the real engine against the 2-10 ns of section 2.3.

## 10. Risks and decisions

Risks:
1. **The gain from bytecode alone is small** (13-23% of a 15.5 MB run is evaluator; section 1.6). The effort pays through spans and streaming
   construction and through a cleaner base for Stage 3; if the owner expects 2x faster runs, the scanner floor (516 MB/s) forbids it. The scanner,
   not the evaluator, is the next thing to measure for further speed **(unverified idea: the scan rate of 0.52 bytes/ns may leave room)**.
2. **Parity is large:** `run`, `evs` and `terminal` encode many corner cases (generator order, `try` not catching its consumer, deferred errors,
   `limit` unwinding, register generations). The differential harness is the mitigation; a stage that merges with an unexplained difference is the
   failure mode. Subtle: error *order* and which of two errors is reported first in operands with generators.
3. **Startup depends on the Mitochondria runtime**: if arrays cannot be reserved without commit, the 13.6 ms stays unless capacity is cut; the
   bytecode engine does not help this at all. Related: the 5.6 ms per GiB of `Out.text` is a cost on every run for a capacity few runs use.

Other risks: the 8192-instruction and 256-register limits turn some large filters into "too big" errors (a limit to state in the README); the
explicit return stack changes where the "nested too deeply" error triggers; the micro-benchmarks of section 2 are best-case and will overstate
the interpreter's speed.

Decisions for the owner:
- Startup: smaller default arrays (and what capacity errors mean), a Mitochondria runtime change (reserve-only arrays), or accepting 27 ms.
- Whether stage 7 (spans, streaming construction) is in the commitment now; they are where the speedup is.
- The migration build flag (`Lim.ENGINE`) for stages 1-5: accepted, or develop on a branch and merge only at parity (no flag in `main`).
- Whether the output buffer stays "write everything at the end" (the profile shows output formatting as a quarter to a third of the time and a
  page-fault cost for large results); streaming output to stdout would change the error behavior (jq prints results before an error; jx prints
  nothing), a user-visible decision.
- Native code (section 8): deferred; confirm.
- `--explain` text format (4.10) as a stable, tested interface, or an unstable debugging aid.
