# jx scanner: a jq-compatible extractor that makes one forward pass

Status: design only. Nothing here is implemented. Written 2026-11-12.
Starting point: `examples/jx/` in the Mitochondria repository (benwmaddox/mitochondria). The branch `jx-large-input` there
(4 GiB input, reserved-not-committed memory) is assumed to exist.

## 1. Goals, non-goals, and what "touch each byte once" means

### 1.1 Goals

1. Run jq filters over a large JSON document without building a tree of it. The input is read once, front to back.
2. Compile the filter before reading the input. The compile step yields (a) a **demand set** (which paths the filter may read and
   in what form), (b) a **path automaton** the scanner follows, and (c) a **slot program** (bytecode) that runs when a unit of
   input is complete.
3. Copy nothing except extracted values, into a small structure sized by the compiled filter.
4. Constant memory for streaming filters (`.users[] | ...`): memory does not grow with the input size.
5. Output identical to jq 1.8.x for the supported subset (checked as in section 9).
6. Follow the Mitochondria principles: compile-time work first, explicit over implicit, fixed declared sizes, no allocation at run time.

### 1.2 Non-goals

- Full jq. Features that need the whole document as a value (`walk`, `..`, `paths`, `setpath`) get all-children demand or are
  rejected with a clear error (section 6). No silent fallback to a different engine.
- Beating simdjson's skipping speed. The first scanner is scalar byte code; SIMD is a later question.
- Streaming output before the input ends for filters that need all input (`sort`, `group_by`, `add`). Those hold extracted keys, not the document.
- Editing documents (`|=`, `del`, `setpath`) in the first versions.

### 1.3 What "touch each byte once" means

A byte is **touched** when the scanner reads it to make a decision (class lookup, comparison, digit accumulation, copy). The goal:
every input byte is read by one scanner loop, which classifies it and does what the demand says at the same moment.

| Case | Touches | Why |
| --- | --- | --- |
| Skipped value (not demanded) | 1 | The skipping loop reads each byte to find the end and to validate structure (7.2). |
| Demanded number, kind Number | 1 | Digits accumulate into a value as they pass. |
| Demanded string, kind String | 1 | Compared or unescaped inline as the bytes pass. |
| Demanded value, kind Span | 1 for the scan, plus 1 when written to output | The output copy is a `memcpy`, not a decision, and is the unavoidable cost of output. |
| Span of a number later used in arithmetic | 2 | Kind was chosen too weak, so the bytes are parsed later. The analysis should pick Number whenever arithmetic or comparison uses the value. |
| Key bytes | 1 | Looked up in the automaton as they are read. A key with an escape is unescaped inline, then compared. |
| Early exit | less than 1 | When every slot is filled and nothing more is needed, the rest of the input is never read (`.users[0].n`, `first`, `limit`). |
| Dynamic key (`.[$k]`) | about 2 for the enclosing node | The node is kept as a span and re-scanned once the key is known (section 6). |
| Indented output | 1 more over output bytes | The formatter re-reads span bytes to re-indent. |

"Once" is a goal for the input scan, not a count that includes the output copy.

## 2. Contrast with prior art and with current jx

### 2.1 Current jx

Read from `examples/jx/`: a value is a position in the input text (`-1` for null). The filter is not compiled: `eval` in
`filter.mito` walks the filter text with a position. `field_pos` and `index_pos` in `json.mito` find a field by skipping value by
value from the start of the object, so each lookup re-scans its object. `length` and `type` make new values and must be the last
step. There is no arithmetic, construction, `map`, `keys`, `,` or variables. Input and output are each capped at 32 MB. The whole
input is validated first (`skip_value` over the document), then the filter navigates and re-scans parts, so bytes are touched at
least twice, more for repeated lookups.

The scanner keeps jx's best idea (values are positions; results are copied from the input) and changes two things: the filter is
compiled to tables before the input is read, and validation happens during the single pass.

### 2.2 Other tools (from memory; everything here is unverified unless stated)

- **simdjson On Demand**: forward-only, in-order access through a cursor; values are parsed lazily when asked for. Out-of-order
  access rules in the current version: unverified. It is a library API, not a filter language.
- **Mison, Pison, JSONSki**: research systems for projection pushdown: given wanted paths (JSONPath-like), find those values without
  parsing the rest. Mison uses SIMD structural indexes and speculation; JSONSki does bit-parallel streaming with fast-forward over
  unwanted parts (details of each: unverified).
- **jq `--stream`**: turns input into `[path, leaf]` events so a filter can run without the whole document in memory. It still
  tokenizes everything and filters must be written in event form (further details unverified).
- **jaq**: a jq clone in Rust; believed to parse the whole input into a value tree and interpret the compiled filter (unverified).

What this design adds: the full jq filter language is the surface, and the compiler derives the projection from it. The cost is
that features that cannot be projected statically get conservative demand or are rejected (section 6).

## 3. Value model and memory model

### 3.1 Value kinds in the slot program

| Kind | Representation | Where it comes from |
| --- | --- | --- |
| Span | `(start, end)` byte offsets into the input, i64 each | A demanded value of kind Span, or a copy-through such as `{name: .n}` |
| Num | i64, f64, or "literal span" (7.3) | Kind Number slots, arithmetic results |
| Str | span into input if it has no escapes, else `(offset, len)` into the **string scratch** | Kind String slots, `tostring`, `ascii_downcase` |
| Bool, Null | tag only | Kind Bool/Null slots, comparisons |
| List | `(start, len)` into the **value arena** | `[...]`, `map`, collectors |
| Object | `(key, value)` pairs in the value arena, key a Span or Str | Construction `{a: .x}` |

A tagged value is 16 bytes: tag and flags in one word, payload words for span ends or number bits. Fixed size means slot and arena
tables are plain arrays.

### 3.2 Memory regions, all declared and reserved up front

| Region | Size is set by | Lifetime |
| --- | --- | --- |
| Input window | the `jx-large-input` rules: up to 4 GiB, reserved, committed as read | whole run |
| Slot table | compiled filter: slot count x 16 bytes | whole run, logically reset per unit |
| Automaton tables | compiled filter | whole run, read only |
| Value arena | declared cap (default 16 MB, flag to raise), bump pointer | rewound per unit for streaming filters |
| String scratch | declared cap, bump pointer | same |
| Collector buffers | one per `sort`/`group_by`/`add`/`unique` site, carved from the arena | whole run |
| Output | declared cap, flushed when half full for streaming filters | whole run |

Rules:

- Nothing allocates at run time; the only dynamic thing is a bump pointer inside a reserved region. Exhausting a region is a
  visible error naming the flag to raise it, never silent growth.
- Pages are committed as the scanner reaches them, so a 4 GiB document that exits early commits little.
- Slot count is a compile-time constant: 3 demanded paths means 3 slots.

### 3.3 What a result is

A result is a tagged value. Writing a Span copies its bytes from the input (compact mode strips whitespace while copying, 7.8).
Writing a Num prints it; writing a Str re-escapes if it was unescaped. Lists and Objects write element by element. No document
fragment is held outside the arena and slots.

## 4. Demand analysis

### 4.1 Definitions

A **path** is a sequence of steps from the root: `.key`, `[N]` (constant index), `[]` (every element), `*` (every child). A filter's
**demand** is a set of `(path, kind)` pairs.

| Kind | Meaning | Cost when the scanner reaches it |
| --- | --- | --- |
| Span | offsets only; bytes copied to output later or compared raw | scanner skips the value anyway; stores 2 offsets |
| Number | parsed inline as i64/f64, plus the literal span | digits accumulate as they pass |
| String | compared or unescaped inline; span kept | byte loop with an escape flag |
| Bool/Null | one tag | 4 to 5 byte compare |
| Type | only the type tag (`type`, truthiness, `has`) | first byte of the value, then skip |
| Keys | the set of keys of an object | key spans collected while skipping values |
| Count | number of elements or keys (`length`) | counter in the skipper |
| All-children | everything below the node, in Span form | node kept as a span for a bounded re-scan (section 6) |

Demands merge to the stronger kind (Number implies Span and Type; String implies Span; All-children implies all below).
Over-approximation is allowed because it costs two stored offsets.

### 4.2 Procedure

1. Parse the filter into a tree (a compile-time structure, not run-time data).
2. Walk it carrying a **context**: the set of paths the current `.` stands for (initially the root). `.k` extends every context path
   with `.k`; `.[]` with `[]`; `a | b` runs `b` in the context `a` yields; `a, b` unions.
3. Where a value is consumed, record `(context path, kind)`: comparison and arithmetic add Number or String; `select(C)` adds the
   demand of `C` and passes the context on; construction `{k: E}` adds the demand of `E`, a bare path as Span; `length` adds Count;
   `keys` adds Keys; a result position adds Span.
4. Branches (`if`, `//`, `try`, `and`, `or`, `,`) take the union of all arms.
   `if .type=="a" then .x else .y end` demands `.type` (String), `.x`, `.y`.
5. `E as $v | body` demands `E` and makes `$v` an alias of its slot. `reduce` and `foreach` demand source, init and update; the loop
   variable aliases the source element context.
6. A dynamic key (`.[$k]`), `keys`, `to_entries`, `..`, `walk`, `paths` gives All-children (or Keys) on the enclosing node.
7. **Unit**: the shortest prefix ending in `[]` that all demanded paths share (`.users[]`). With no `[]`, the unit is the document.
   If paths share no iteration (`.a[].x, .b[].y`), the unit is the document and the iterations fill collectors (5.4).
8. **Early exit**: possible when every demanded path is constant (no `[]`, no `*`, no collector). The scan ends when all slots are
   filled and no later key could change one (duplicate-key rule in 7.1).

### 4.3 Worked examples

**1. `.users[0].n`**

| | |
| --- | --- |
| Demand | `s0: .users[0].n (String)`, also written as Span, so String |
| Unit | document |
| Automaton | root object: key `users` -> A; A array: index 0 -> B; B object: key `n` -> fill s0 |
| Early exit | yes, once s0 is filled and the duplicate-key rule allows it |
| Program | `OUT_SPAN s0` |
| Touches | bytes before `users`: 1 each (skipped); `users[0].n`: 1; everything after: 0 |

**2. `.users[] | select(.age >= 85) | .n`**

| | |
| --- | --- |
| Demand | `s0: .users[].age (Number)`, `s1: .users[].n (Span)` |
| Unit | each element of `.users` |
| Automaton | root: key `users` -> A; A array: element -> unit state U (program runs at element end); U: key `age` -> s0, key `n` -> s1 |
| Program | `LOAD r0,s0; CONST r1,85; CMP >=,r0,r1,r2; JF r2,end; OUT_SPAN s1; end: RESET 1` |
| Touches | `age` digits parsed inline (1); `n` stored as a span (1), copied only for matching rows; other fields skipped (1) |
| Notes | A missing `age` loads as Null, and `null >= 85` is false by jq's type order |

**3. `.users[] | {name: .n, city: .addr.city}`**

| | |
| --- | --- |
| Demand | `s0: .users[].n (Span)`, `s1: .users[].addr.city (Span)` |
| Unit | each element of `.users` |
| Automaton | U: key `n` -> s0; key `addr` -> state C (object): key `city` -> s1 |
| Program | `OBJ_BEGIN; KEY "name"; PUSH s0; KEY "city"; PUSH s1; OBJ_END r0; OUT r0; RESET 1` |
| Notes | Missing fields give `null`. The keys are program constants; values are copied from the input |

**4. `.users | map(.age) | add`**

| | |
| --- | --- |
| Demand | `s0: .users[].age (Number)` |
| Unit | each element of `.users` (`map(f)` is `[.[] | f]`) |
| Program | per element: `LOAD r0,s0; ACC_ADD a0,r0; RESET 1`; at end: `OUT a0` |
| Notes | `map` followed by `add` is recognized as a fold, so no list is built. How `add` treats null elements: unverified, test against jq 1.8.2. Sum is i64 while exact, then f64 |

**5. `[.users[] | .age] | sort | .[0]`**

| | |
| --- | --- |
| Demand | `s0: .users[].age (Number)` |
| Unit | each element |
| Program | per element: `LOAD r0,s0; COLLECT c0,r0; RESET 1`; end: `SORT c0; INDEX r1,c0,0; OUT r1` |
| Memory | `c0` is a collector: 16 bytes per age. `sort | .[0]` can be recognized as a minimum (running min, no collector); fall back to the collector when unsure |
| Notes | Mixed types sort in jq order: null, false, true, numbers, strings, arrays, objects |

**6. `.users | group_by(.addr.city) | map({city: .[0].addr.city, n: length})`**

| | |
| --- | --- |
| Demand | `s0: .users[].addr.city (String)`; group members are used only through `.[0].addr.city` (same slot) and `length` (Count of the group) |
| Unit | each element of `.users` |
| Program | per element: `LOAD r0,s0; GROUP_ADD g0,r0; RESET 1`; end: for each group in key order, build `{city: key, n: count}`; `OUT` |
| Memory | one entry per distinct city: key plus count, 32 bytes |
| Limit | Works because the analysis proves members are used only via the grouping key and `length`. If another member field is used (`.[0].n`), add a slot and the group stores the first member's slot value. If all members are used (`map(.n)`), the group stores a list. If use cannot be proved (members passed to a user function), reject |

**7. `.a, .b` on one object**

| | |
| --- | --- |
| Demand | `s0: .a (Span)`, `s1: .b (Span)` |
| Unit | document |
| Program | `OUT_SPAN s0; OUT_SPAN s1` |
| Notes | Results come in filter order (`.a` then `.b`) even if `b` comes first in the input. That is why slots exist: the scan fills them in input order, the program reads them in filter order. Early exit once both are filled |

**8. `reduce .users[] as $u (0; . + $u.age)`**

| | |
| --- | --- |
| Demand | `s0: .users[].age (Number)` |
| Unit | each element of `.users` |
| Program | before the scan: `CONST a0,0`; per element: `LOAD r0,s0; ARITH +,a0,r0,a0; RESET 1`; end: `OUT a0` |
| Notes | The accumulator is a register, not reset per unit. The general form: the update body is the per-unit program with `.` bound to the accumulator register. No special recognition is needed |

## 5. Automaton and slot-program formats

### 5.1 Path automaton

A trie of the demand set. Each node is a **state** describing the container the scanner is in.

```
State {
  kind:      Object | Array | Any
  key_table: wanted keys -> (action, next_state)
  idx_table: constant indices wanted -> (action, next_state), or "every element"
  default:   Skip | Capture            // for unlisted keys (Capture under All-children)
  on_close:  program entry or none     // run when this container ends (unit end)
}
Action = FillSlot(slot, kind) | Descend(state) | Both
```

- States are numbered; tables are flat arrays indexed by state number. Wanted keys per state are few, so lookup compares key
  length and first byte against a small table, then the full bytes. Above 16 keys, a perfect hash chosen at filter-compile time.
- A raw key with escapes is unescaped into a small stack buffer (longest wanted key + 1; a longer key cannot match) before comparing.
  Wanted keys are stored unescaped.
- `Both` fills a slot and descends, so `.a` (Span) and `.a.b` (Number) are extracted in one pass.
- Automaton depth is the demanded path depth, a compile-time constant. Skipped values push no states.

### 5.2 Scanner loops

| Loop | Job |
| --- | --- |
| `scan_state` | in a wanted container: read key or element boundary, look up the action, dispatch |
| `skip_value` | in an unwanted value: find the end and validate structure (escapes, bracket pairing); no slot writes |
| `read_scalar(kind)` | demanded scalar: parse the number or string while advancing |

`skip_value` keeps a fixed container-kind stack for bracket pairing (declared maximum depth, error beyond it; the value is a
decision, jq's own limit is unverified).

### 5.3 Slot table

```
Slot {            // 16 bytes
  tag: u8         // Empty | Span | Num | Str | True | False | Null | Count | KeysList
  gen: u8         // validity generation (7.4)
  a:   i64        // span start, number bits, or string offset
  b:   i64        // span end, or literal-span end for numbers
}
```

A later fill overwrites the slot (last wins, 7.1). A `[]` demand that is not the unit gets a List slot; fills append to the arena.

### 5.4 Unit boundary and multiple iterations

- **One shared iteration** (`.users[] | ...`): unit = element; the program runs at element end.
- **No iteration**: unit = document; the program runs at end of input or at early exit.
- **Nested iteration** (`.a[] | .b[] | ...`): the unit is the inner element; outer slots are sticky (reset at the outer element's
  end). The compiler assigns each slot a **reset level**.
- **Independent iterations** (`.a[] | f, .b[] | g`): filter order needs all of the first before any of the second, but input order
  may interleave. The unit is the document and both fill collectors, so memory is proportional to the extracted values. The
  compiler says so in a diagnostic.

### 5.5 Slot program instructions

A register machine over slots, registers (accumulators, collectors, loop variables) and an output stream. One-byte opcode, up to
three small operands.

| Instruction | Semantics |
| --- | --- |
| `LOAD r, s` | r = slot s (Empty becomes Null) |
| `CONST r, k` | r = compile-time constant k |
| `JMP L`, `JT r, L`, `JF r, L` | jump; truthiness: only null and false are false |
| `CMP op, a, b, r` | compare by jq's type order and number rules; Bool into r |
| `ARITH op, a, b, r` | `+ - * / %`, plus string/array concatenation, object merge, null as identity for `+`; errors as jq |
| `NOT r`; `AND`/`OR` by jumps | boolean ops with short circuit |
| `TYPE r, a` | type name string |
| `LEN r, a` | jq `length` (codepoints, elements, fields, number magnitude) |
| `OUT_SPAN s` | write slot s's span to output |
| `OUT r` | write a register value of any tag |
| `OBJ_BEGIN`, `KEY k`, `PUSH r`, `OBJ_END r` | build an object in the arena |
| `ARR_BEGIN`, `PUSH r`, `ARR_END r` | build an array in the arena |
| `COLLECT c, r` | append to collector c |
| `ACC_ADD a, r` | fold-add (fast path for `add`) |
| `SORT c`, `SORT_BY c`, `GROUP_BY c`, `UNIQUE c` | order a collector as jq does (stability rules: unverified, test) |
| `GROUP_ADD g, r` | add to a group table keyed by r, keeping first member values and a count |
| `INDEX r, a, i`, `FIELD r, a, k` | index a built List/Object; on a Span, run a bounded re-scan (section 6) |
| `CALL f`, `RET` | user functions are inlined when non-recursive; otherwise a fixed-size call stack |
| `TRY L`, `CATCH` | errors from the guarded body jump to L |
| `FOR_BEGIN r, c`, `FOR_NEXT r, L` | loop over a collector or built list (`foreach`, `limit` over built values) |
| `LIMIT n, L` | after n results jump to L; mark early exit when nothing later is needed |
| `RESET level` | clear slots of that level (7.4); rewind arena and scratch to the level's mark |
| `HALT` | end this unit; with the early-exit flag, end the scan |
| `ERR r` | raise error r |

Generators inside a unit (`.[]`, `,`, `range`) compile to loops with explicit resume points, not a general backtracking machine. A
generator whose source is neither extracted data nor a bounded collector is rejected at compile time.

## 6. jq feature table

**Fits** = single forward pass with constant or collector memory. **Fits+** = needs a bounded extra scan of a captured span.
**All** = all-children demand. **Reject** = compile error at first, may be added later.

| Feature | Demand it creates | Single pass? | Cost / fallback |
| --- | --- | --- | --- |
| `.a`, `.a.b`, `.["a"]`, `.[0]` | Span/Number/String at the path | Fits | Trie lookup per key; constant index counted in the skipper |
| `.[]`, `.a[]` | unit boundary or `[]` step | Fits | per-element reset |
| `.[-1]`, `last` | last element, unknown until the array ends | Fits | keep-last slot overwritten per element; no early exit |
| slices `.[a:b]` | index range | Fits for constant non-negative bounds | counter in skipper; negative bounds capture all elements as spans |
| `..` | All-children | All | root kept as a span, recursive walk by a second scan, jq pre-order. Reject in stage 1 |
| pipe `a \| b` | `b` runs in the context of `a` | Fits | demand composes |
| comma `a, b` | union | Fits | slots plus filter-order output; two iterations: collectors (5.4) |
| `select(f)` | demand of `f` plus context | Fits | per-unit branch |
| `map(f)` | `[.[] \| f]` | Fits | fold when followed by `add`, `length`, `min`, `max`; else a list in the arena |
| `keys`, `keys_unsorted` | Keys | Fits | key spans collected while skipping; `keys` sorts by codepoint (non-BMP behavior: unverified) |
| `length` | Count; string length; number magnitude | Fits | counter in skipper; a string needs a codepoint count |
| `type` | Type | Fits | first byte |
| `add` | fold | Fits | accumulator; empty input gives null |
| `sort`, `sort_by(f)` | key of `f` per element | Fits | collector of keys (and element spans if output); memory linear in count |
| `group_by`, `unique_by`, `unique`, `min_by`, `max_by` | key of `f`; members only as used downstream | Fits | example 6; members used in full are stored as spans |
| `to_entries`, `from_entries`, `with_entries(f)` | All-children on the object | Fits+ | entries are key/value span pairs; `f` runs per pair |
| `has(k)`, `in(o)` | presence (constant k) or Keys (dynamic k) | Fits | presence slot or membership test |
| `if/elif/else` | union of arms and condition | Fits | over-demand is cheap |
| `a // b` | union | Fits | Empty or Null slot selects the right side |
| `try E catch H`, `E?` | demand of E and H | Fits | guarded region. Malformed-input errors are not catchable (jq equivalence: unverified) |
| `reduce`, `foreach` | source, init, update | Fits | accumulator registers; update body is the per-unit program |
| `limit`, `first(f)`, `first`, `isempty`, `until` | as `f` | Fits | early exit when no later slot is needed; `last(f)` cannot exit early |
| `range(a;b)` | none, or extracted Numbers | Fits | generator loop |
| `path(f)`, `paths`, `getpath`, `setpath`, `delpaths`, `del` | node positions | Reject (stage 1) | static `path(f)` can be computed at compile time; the rest need all-children capture and positions |
| `walk(f)` | All-children | All | needs a rebuilt value, so a tree of that node only. Reject first |
| variables `E as $v` | demand of E | Fits | `$v` aliases a slot or register; destructuring adds constant index paths |
| user functions `def f(x): ...;` | demand of the inlined body | Fits (non-recursive) | closure parameters inlined as filter fragments; recursion rejected at first |
| `input`, `inputs` | next document | Fits | each document is a new scan with the same program; early exit must not skip later documents unless the filter says so |
| `--slurp` | whole input as one array of documents | Fits+ | synthetic outer `[]` unit per document |
| `--stream` | path/leaf events | Reject (stage 1) | natural later fit: the scanner knows the structure; needs a path stack |
| `tojson`, `fromjson` | Span as string; scan of a string | Fits / Fits+ | `tojson` needs the normalization in 7.3 and 7.5; `fromjson` runs a nested scan on scratch |
| `@csv`, `@tsv`, `@sh`, `@uri`, `@html`, `@json`, `@base64`, `@base64d` | elements as String/Number | Fits | output-side transform; `@base64d` decodes into scratch |
| regex (`test`, `match`, `capture`, `sub`, `gsub`, `split/2`) | String | Fits+ | needs a regex engine (jq uses Oniguruma, details unverified); out of scope first |
| dates (`strptime`, `mktime`, `todate`, `now`) | Number/String | Fits | pure functions; `now` and `localtime` are non-deterministic, excluded from the oracle |
| `$ENV`, `env` | none | Fits | compile-time constant |
| string interpolation `"a \(.x)"` | embedded filters as String/Number | Fits | `tostring` of each, assembled in scratch |
| `tostring`, `tonumber`, `ascii_downcase`, `startswith`, `ltrimstr`, `join`, `split("x")` | String | Fits | register ops; results in scratch |
| dynamic access `.[$k]`, `.[expr]`, `getpath($p)` | All-children on the enclosing node | Fits+ | node kept as a span; bounded re-scan once the key is known, a second touch on that node only. A key that is constant after inlining folds into a static path |
| math functions (`floor`, `sqrt`, `pow`, ...) | Number | Fits | pure; bit-exact agreement with jq: unverified, test |
| `limit` with a non-constant count | as `f` | Fits | count register |

Unsupported features fail with `jx: filter not supported by the scanner: <feature>` before any input is read, never with different
semantics.

## 7. Semantic gaps and decisions

### 7.1 Duplicate keys

jq 1.8.2, checked on `{"a":1,"a":2,"n":100000000000000000001}`: `.a` gives `2`, and `.` prints `{"a":2,"n":...}`, the key in the
position of its first occurrence with the last value. Consequences:

- **Last wins** for slots. A node cannot be treated as closed after its first match unless no second occurrence is possible.
  Options (decision 2, section 11): (a) early exit at the end of the container that holds the last wanted key (skip the rest of that
  container, not the rest of the document); (b) early exit at first fill, which differs from jq on duplicate keys; (c) no early exit
  before the end of the document. Recommended: (a), with an opt-in flag for (b).
- **Copying an object from the input** differs from jq when it has duplicate keys: jq re-serializes the deduplicated object; a span
  copy keeps both. `OUT_SPAN` on a container is exact only if no object inside has duplicate keys, and the skipper cannot cheaply
  check that. Decision 1: container copy-through is exact only for documents without duplicates; a `--strict` mode checks key sets
  of captured containers. Scalars are exact.

### 7.2 Malformed input in skipped regions

| Checked while skipping | Not checked |
| --- | --- |
| brackets and braces pair correctly (container-kind stack) | number grammar inside skipped values beyond "a run of number characters" (leading zeros, `1.`) |
| strings terminate; a backslash is followed by a valid escape letter, or `u` plus four hex digits | UTF-8 validity inside skipped strings (jq's handling: unverified) |
| commas and colons appear where the grammar requires them (a small state flag per container) | duplicate keys |
| `true`, `false`, `null` are spelled fully | |
| depth within the declared limit | |

Demanded values are fully validated (number grammar, UTF-8). After early exit the unread remainder is not validated at all; jq
rejects the whole document. This is a deliberate difference (decision 3); `--validate` reads to the end and checks structure,
giving back the full touch count.

If the input is malformed after output has started, earlier results are already written; the error goes to stderr with a non-zero
exit code (jq's behavior in every such case: unverified).

### 7.3 Numbers

- The span preserves the literal. jq 1.8.2 prints `100000000000000000001` unchanged for the input above, so large integer
  literals survive paths without arithmetic. Canonicalization of other literals (`1.0`, `1e2`, `0.10`) is unverified: the oracle
  decides which literals may be copied as spans and which must print in canonical form.
- Arithmetic uses f64 like jq, with an i64 fast path while both operands are exact integers. Comparison of huge literals follows
  jq's rules (jq 1.7+ is believed to compare by literal value: unverified; test).
- Number parsing happens inline as bytes pass; the literal span is kept so output does not reformat.

### 7.4 Slot reset

Each slot has a generation byte; a unit end increments the current generation, so a slot is Empty when its `gen` differs. No
zeroing loop per unit (wraparound every 256 units needs one real clear: a cost to measure). Collectors and accumulators are outside
slot levels. A slot with a reset level above 1 is reset at its level's boundary. Arena and scratch are rewound to the mark taken at
unit start.

### 7.5 Strings and escapes

- Key matching: wanted keys are stored unescaped. A raw key with no backslash is compared directly; otherwise unescaped into a
  stack buffer (5.1). A `\u0000` in a key compares as a NUL, as jq does (unverified).
- A String slot of an unescaped string is a span and costs nothing. A string with escapes is unescaped into scratch when used as a
  value, and copied through as the original span otherwise. jq re-escapes strings on output with its own choices (which control
  characters and whether DEL are escaped: unverified), so copy-through of a string that contains a backslash is exact only when
  the document's escapes match jq's. The scanner knows a "has escape" flag per string for free; the safe rule is: any string with a
  backslash takes the Str path (unescape, then re-escape as jq does). Decision 1 covers whether to relax this.
- Surrogate pair handling and invalid surrogates follow jq (replacement behavior: unverified; oracle-tested).
- `-r` writes a String result raw. `-j`, `-a`, `--raw-output0` are separate formatter modes (later).

### 7.6 Order of results

Results come in filter order, not input order. Within a unit that is the program's order. Across units it is input order, as in jq.
Filters that reorder across units (`sort`, `group_by`) emit at end of input. `limit` and `first` count results in filter order, so
the scan may stop earlier or later than input order suggests.

### 7.7 Errors

| Error | Behavior |
| --- | --- |
| Runtime type error (`.a.b` where `.a` is a number) | jq's message text where the jq test suite checks it; non-zero exit (jq uses 5: unverified); earlier results already written |
| Filter syntax error | before reading input; jq uses exit 3 (unverified) |
| Unsupported filter feature | before reading input; own exit code |
| Malformed input | message with the byte offset; wording need not match jq |
| Arena or scratch exhausted | named error with the flag to raise it |

Exact error text is a non-goal except where `jq.test` checks it.

### 7.8 Flags

| Flag | Behavior |
| --- | --- |
| `-c` | compact: the formatter drops whitespace while copying spans |
| default | indented: streaming formatter with a depth counter, two spaces, `[]` and `{}` for empty containers |
| `-r` | raw strings |
| `-s` | slurp: one array of all input documents (synthetic outer array) |
| `-n` | null input: the filter runs once without reading unless it calls `input`/`inputs` |
| `-e`, `--arg`, `--argjson`, `--args`, `--tab`, `--indent n`, `-S`, `-a` | later; `-S` needs sorted keys on output, which reorders object spans, so it needs key-sorting in the formatter |

## 8. Performance model

### 8.1 Model

For a streaming filter over `N` input bytes, `D` demanded bytes, `R` units:

```
time ~= N / skip_rate + D / parse_rate + R * (unit_overhead + program_cost) + output_bytes / copy_rate
```

Estimates, all unverified until measured (scalar code, no SIMD):

| Term | Guess | Basis |
| --- | --- | --- |
| `skip_rate` | 0.3 to 1.5 GB/s, lower for structure-dense text | a table-driven byte loop. Current jx measures about 8 ms/MB (125 MB/s) including a validation pass plus lookup, so several times that is plausible but not shown |
| `parse_rate` | 200 to 500 MB/s of digit text | inline accumulation |
| `unit_overhead` | 20 to 60 ns | automaton dispatch, generation bump, program entry |
| `program_cost` | 10 to 50 ns for select plus output | a few dispatched instructions |
| `copy_rate` | memory speed compact; 300 to 800 MB/s indented | |

For the 1.78 MB, 20,000-row document: skip and parse at about 200 MB/s gives roughly 9 ms, units about 2 ms, so low single digits to
about 10 ms plus process start. For 17.2 MB, roughly 90 to 120 ms if the model holds. These are targets, not promises. Reading from a
pipe and first-touch page commit may dominate.

### 8.2 Comparison with the measured results

| Document (Windows) | jx now | jq | jaq |
| --- | --- | --- | --- |
| 1.78 MB, 20,000 rows | 31 to 58 ms | 99 to 128 ms | 55 to 105 ms |
| 17.2 MB | cannot run yet | 581 to 838 ms | 381 to 849 ms |

jq and jaq cost about 20 to 35 ms per MB; current jx about 8 ms per MB for a first-element lookup. Targets to check: 3 ms per MB or
less for streaming filters touching few fields; early-exit filters cost proportional to the offset of the last needed byte
(`.users[0].n` on 17.2 MB near the cost of reading up to that offset).

### 8.3 What to measure

1. Skip speed: MB/s of `skip_value` alone on string-heavy, number-heavy and structure-dense documents.
2. Per-unit overhead: `.users[] | select(false)`, time per element.
3. Slot reset cost: the same with 1, 8 and 64 slots; check the 256-unit wraparound clear.
4. Demand scaling: `.users[].age` against `.users[] | {5 fields}`; marginal cost of a demanded field.
5. Early exit: `.users[0].n` on the 1.78 MB and 17.2 MB documents; time should not scale with size.
6. Output: `-c` of a large span against indented.
7. Peak committed memory for streaming filters (should be constant) and for `sort` (linear).
8. Against jq 1.8.2 and jaq 3.1.2 on the same files and machine, process start included, with the repo's ABBA ordering; on
   Linux/WSL under the benchmark lock when comparing there.
9. Touch count: an instrumented build counting reads per input byte, to verify the table in 1.3.

## 9. Staged implementation plan

Conformance oracle: jq's own test file `tests/jq.test` in https://github.com/jqlang/jq (also `tests/man.test`, `tests/onig.test`,
`tests/optional.test`; exact current file names unverified), about 1000 cases, each a program line, an input line, and expected
output lines. Check out the tag matching the installed jq 1.8.2 into a scratch directory outside this repo; not downloaded as part
of this design. Cases outside the supported subset go in a skip file with a reason, and the skip list shrinks over time as a measure
of progress. Output oracle: a corpus of filters x documents run through jq 1.8.2 and jaq 3.1.2; the scanner must match jq byte for
byte; where jq and jaq differ, jq wins and the difference is logged.

| Stage | Adds | Exit test | Benchmark |
| --- | --- | --- | --- |
| 0 | this document reviewed; owner decisions (section 11) | decisions recorded | none |
| 1 | span navigator and automaton for `.`, `.field`, `.[n]`, `.[]`, pipes, `select` with comparison, `length`, output (compact and indented); structure-validating skipper; slots; minimal program (`LOAD`, `CONST`, `CMP`, `JF`, `OUT_SPAN`, `LEN`, `RESET`, `HALT`); filter compiled to tables | all current `examples/jx/e2e.sh` cases pass; every `jq.test` case inside the subset passes; byte-identical to jq on a 40-filter corpus over 6 documents (with and without duplicate keys, escapes, big numbers; those are expected to fail first and drive 7.1 and 7.5) | skip speed (8.3.1), per-unit overhead, early exit; table against current jx, jq, jaq |
| 2 | Number and String kinds; arithmetic; `,`; `//`; `if`; `and/or/not`; construction; `keys`, `type`, `has`, `map`, `add`, `first`, `limit`; variables; `try` | jq.test subset; corpus grows to 100 filters | demand scaling, slot reset cost |
| 3 | collectors: `sort`, `sort_by`, `group_by`, `unique`, `min/max`, `reduce`, `foreach`; fold recognition; `to_entries`/`from_entries`/`with_entries`; sticky slots | jq.test subset; memory check (constant for streaming, linear for collectors) | memory (8.3.7); 17.2 MB against jq/jaq |
| 4 | all-children capture and bounded re-scan: dynamic keys, `getpath`, `..`, `walk` on captured nodes, `paths`; `--slurp`, `input`/`inputs`, `-n` | jq.test subset; remaining skip list | cost of the re-scan |
| 5 | strings: interpolation, `@` formats, `tojson`/`fromjson`, `ltrimstr`; regex only if the owner wants it | jq.test string cases | none new |
| 6 | `--stream`, `-S`, remaining flags; word-at-a-time or SIMD skipping if measurements justify it | corpus identical | skip speed after the change |

**Stage 3 (added by the owner, 2026-11-12):** `--explain` (print the automaton and slot program for a filter), with tests/explain.txt regression pairs.

For every stage: the scanner is a new program beside the current jx until it passes the stage 1 exit test; no feature lands without
its `jq.test` cases enabled; the skip list is part of the commit.

## 10. Risks and open questions

### 10.1 Risks

1. **Copy-through exactness.** Spans of containers and of strings with escapes may differ from jq's re-serialized output (duplicate
   keys, escape choices, number canonicalization). The fast path needs a guard or the output is not byte-identical to jq.
2. **Early exit against validation and duplicate keys.** Early exit leaves the rest unvalidated and can miss a later duplicate; jq
   rejects the whole document. Either way behavior differs from jq somewhere.
3. **Feature surface.** Features needing whole values (`walk`, `paths`, `setpath`, regex, dynamic keys) require a tree of a captured
   node. If real use needs many, the scanner is a fast path with a slow path, which conflicts with "no diverging approaches". Compile-time
   rejection avoids a silent second engine but leaves gaps.
4. **Demand analysis soundness.** Under-approximation silently gives wrong answers (an unfilled slot reads as null). Rule: when
   unsure, demand all-children or reject; add a debug mode that cross-checks scanner output against a full evaluation on small inputs.
5. **Speed claims are unmeasured.** The model in 8.1 may be off by 2 to 3 times; skip speed depends on the C the compiler emits.
6. **Generators inside a unit** (`.[] | .a[] | ...` with `,` and `limit`) are the hardest part of the program format; the compile-to-loops
   rule may reject real filters.
7. **Collector memory** for `sort`/`group_by` on a 4 GiB input is linear in extracted values and can exceed any fixed arena.

### 10.2 Questions not settled here

- Whether error messages and exit codes must match jq, or only successful output.
- Behavior of `input_line_number`, `$__loc__`, `input_filename`, `debug`, `stderr` (low value; skipped at first).
- Where the filter compiler lives: in the Mitochondria compiler (Rust), or as Mitochondria code as jx is now. This changes the
  build and the bootstrapping story.

## 11. Decisions the owner must make

1. **Exactness of copy-through.** Accept that copying a container or an escaped string from the input is exact only for documents
   without duplicate keys and with canonical escapes (fast, with a `--strict` check), or require byte-identity with jq always
   (re-serialize containers and escaped strings: slower, more touches)?
2. **Early exit and duplicate keys.** Stop at first fill (fast, differs from jq on duplicates), at the end of the enclosing
   container (recommended), or never before the end of the document (jq-exact)?
3. **Validation policy.** Validate everything read (skipped and demanded) but not the unread tail after early exit (recommended), or
   always validate the whole document (removes the early-exit win)?
4. **Unsupported features.** Reject at compile time with a clear error (recommended; no second engine), or build a node-local tree
   fallback for `walk`, `paths`, `setpath`, dynamic keys (a second engine, more jq coverage)? Is regex in scope?
5. **Where the filter compiler lives.** Written in Mitochondria (like jx today) or inside the Rust compiler, and is the scanner a new
   program that replaces jx after stage 1 (recommended) or an in-place rewrite of `examples/jx`?

## Owner decisions (2026-11-12)

All five open decisions were settled as recommended:

1. **Copy-through exactness:** copying a container or an escaped string straight from the input may differ from jq on duplicate keys, non-canonical escapes and number forms; a `--strict` mode checks for it.
2. **Early exit and duplicate keys:** stop at the end of the enclosing container (not at the first fill, not never).
3. **Validation:** validate everything the scanner reads; the unread tail after an early exit is not validated.
4. **Unsupported features:** `walk`, `paths`, `setpath`, dynamic keys and regex are rejected at filter-compile time with a clear error. No second engine. Regex is out of scope.
5. **Where it lives:** the filter compiler is Mitochondria code (like examples/jx today), not part of the Rust compiler. The scanner replaces `examples/jx` after Stage 1 (examples/jx stays in benwmaddox/mitochondria until then).
