# jx

A jq-compatible filter engine that is a scanner and extractor, not a parser: the filter is compiled before the input is read into a
path automaton (a trie of the paths the filter needs) and an expression tree; the input is then read once, front to back, checking
its structure as it goes and keeping only the spans of the values the filter asked for. Anything the filter needs beyond that
(arithmetic, construction, `try`, variables, ...) is evaluated on values built in a declared arena. Written in the
[Mitochondria](https://github.com/benwmaddox/mitochondria) language. The design is [docs/design.md](docs/design.md); this is its
**Stage 2**. Progress against jq's own test file is tracked in [docs/progress.md](docs/progress.md).

## Build and run

```
./build.sh jx.exe                  # needs the Mitochondria compiler built from its main branch (PR #44, `byte_at` as an inline load); MITO=path/to/mito.exe
echo '{"users":[{"n":"ann","age":91},{"n":"bo","age":7}]}' | ./jx.exe -c '.users[] | select(.age >= 85) | .n'
"ann"
```

jx reads one document on standard input and takes the filter as its first argument; flags are `-c` (compact; the default is jq's
indented output), `-r` (a string result is written raw) and `--validate` (below). Results are written after the whole document has been read; an error
writes a message to standard error and exits with 1 (jq uses 2, 3 and 5), with nothing on standard output.

**Options.** jx parses its own arguments (the program takes the runtime's raw `args`), so an option is understood or refused wherever it is written, before or
after the filter, long or short, combined (`-cr`): `-c`/`--compact-output`, `-r`/`--raw-output` and `--validate` are built; every other jq option is a hard error
before anything is read, `jx: option '-S' is not supported yet` for a jq option jx does not have yet (`-a -j -s -n -e -S -C -M -f -L -R -h -V -b` and `--tab --indent
--arg --argjson --args --jsonargs --slurp --stream --stream-errors --seq --slurpfile --rawfile --sort-keys --color-output --monochrome-output --ascii-output
--join-output --raw-output0 --null-input --raw-input --exit-status --from-file --library-path --binary --unbuffered --help --version --build-configuration --strict
--explain`), `jx: unknown option '--bogus'` for anything else. A second plain argument is an input file (`jx: input files are not supported yet`). No filter means
`.` as in jq; `--` ends the options.

**Exit codes** are jq's where the situation is the same: 2 for a usage error (above), 3 for a syntax error in the filter, 5 for invalid input and for an error raised
while the filter runs (jq prints the results that came before the error first; jx writes nothing on standard output), 0 otherwise. Exit code 1 is jx's own: a filter that
uses something Stage 2 does not support (`jx: not supported in Stage 2: ...`, found before any input is read) or a limit of jx (a full arena). The message goes to standard error.

**Limits.** The input is up to 4 GiB - 1 (the literal in `doc: utf8<4294967295>` in `src/jx.mito`; the runtime reserves it and commits pages as they are read, so a small input
costs nothing). The output buffer is 1 GiB (`Out.text`): the runtime allows a text field of 4 GiB - 1 and jx was run with one (a 529 MB document printed indented, 1.14 GB, in 22 s with
a 2.8 GB peak), but **every GiB declared costs about 10 ms of start-up on every run** (a tiny document: 27 ms with 1 GiB, 38 ms with 2 GiB, 58 ms with 4 GiB; Stage 1 took 10 ms),
so the default is 1 GiB; an output over it ends with a runtime error naming the field. A 529 MB input, a 138 MB indented output and a 192 MB compact output were run. Strings with escapes are
compared up to 1 MB (`J.tmp`); depth is 10000 like jq. Values built while evaluating live in an arena of 16 M entries at the document level and 1 M entries at each of three nesting
depths of iterations; running out is a named error (exit 1). The arena arrays cost start-up time too (about 0.5 ms per million entries), so the floor of a tiny document is 27 ms against Stage 1's 10 ms
(jq 9 ms); a smaller arena (`Lim.REG0` and the array sizes of `Val` in `src/jx.mito`) trades the capacity of collected lists for start-up time.

## What it supports

| Feature | |
| --- | --- |
| paths | `.`, `.name`, `."odd key"`, `.["key"]`, `.a.b`, `.a[0].b`, `.a.[0]`, `.[]`, `.[2:4]`, `.[:-1]` slices of arrays and strings |
| pipes and generators | `a \| b`, `,`, `//` (also with a generator on the left), `empty`, `select(f)`, `first`, `first(f)`, `last(f)`, `limit(n; f)`, `nth(n; f)`, `skip(n; f)`, `isempty(f)`, `until(c; u)`, `range(n)`, `range(a; b)`, `range(a; b; s)` |
| arithmetic | `+ - * / %` and unary minus: numbers as IEEE doubles printed as jq prints them; `+` on strings, arrays and objects; `-` on arrays; `*` on strings (repeat) and objects (deep merge); `/` on strings (split); `null` is the identity of `+`; division by zero and `%` as jq 1.8.2 |
| comparison and logic | `== != < <= > >=` (jq's order across types, exact on number literals), `and`, `or`, `not`; generators in operands give jq's cartesian order |
| conditionals | `if/elif/else/end` (the condition may be a generator) |
| construction | `[...]`, `{a: .x, "b c": .y, (.k): .v, $x, a}`, `map(f)`; unchanged values are copied from the input as spans |
| errors | `try E`, `try E catch H`, `E?`, `error`, `error(v)`; jq's error messages (`Cannot index number with string ("a")`, `number (1) and string ("a") cannot be added`) |
| variables | `E as $x \| body` (one name, no destructuring), `$x` |
| builtins | `length`, `type`, `keys`, `has`, `add`, `add(f)`, `not`, `tostring`, `tonumber`, `toboolean`, `arrays objects iterables scalars values booleans nulls numbers strings`, `empty` |
| output | indented or compact, numbers as jq prints them, strings re-escaped as jq does, invalid UTF-8 replaced by U+FFFD as jq does |

Number semantics follow jq 1.8.2: a literal that is only passed through keeps its canonical text (`1e3` prints `1E+3`, `100000000000000000000` keeps all its digits,
`-0` stays); arithmetic is on doubles (a literal is first rounded to 17 significant digits, half even, as jq's decNumber step does) and prints the shortest
round-trip form in jq's layout (`1e+17`, `1e-05`, `0.30000000000000004`, `nan` as `null`, infinity as `1.7976931348623157e+308`); comparing two literals is exact
(`100000000000000000000 == 100000000000000000001` is false, `1.0 == 1` is true). `src/num.mito` is the parser and printer (checked in `tests/numcheck.py` against
Python and jq, and in `tests/numarith.py` against jq on 1000 random pairs through every operator).

## What is rejected, and how

Everything else is rejected **when the filter is compiled**, before any input is read: exit code 1, `jx: not supported in Stage 2: ...` with the filter position,
nothing on standard output. There is no fallback engine. `tests/reject.txt` lists 60 of them, for example `..`, `.[-1]`, `.[$k]` and every computed index,
`reduce`, `foreach`, function definitions, destructuring (`. as [$a]`), `label`, assignment and update (`=`, `|=`, `+=`), `path`, `paths`, `walk`, `getpath`,
`setpath`, `del`, `to_entries`, `sort`, `group_by`, `unique`, `min`, `max`, `tojson`, `floor` and the other math functions, string functions, `@format`s, string
interpolation, regular expressions, `input`, `$ENV`, `import`. Syntax errors exit with 1 and say `syntax error` (`tests/syntax.txt`). A few operations on values of
the document that Stage 2 does not parse fail at run time with `not supported` (a repeated string over 15 MB, `keys` of an object with more than 60 keys).

## How it works (files in `src/`)

| File | |
| --- | --- |
| `compile.mito` | Parses the filter (precedence climbing, no recursion over precedence levels because Mitochondria allows 64 nested calls) into an expression tree in fixed arrays, then analyzes it with the *static context*: the automaton node the input of each expression is, if any. A path from a known node becomes a `NODE` read of its slot and creates nodes in the trie. A `[]` over a known node becomes a **scope**: an iteration whose body runs at the end of each element while the document streams by. Generators in operands, `as` and similar are rewritten into chains of variable bindings. |
| `scan.mito` | The scanner. One loop with three modes (a value starts, a value ended, a key starts) and an explicit stack of open containers (depth 10000). Wanted values are kept as spans in slots (numbers also as an integer when they are one of at most 15 digits, strings with a flag for escapes and bytes of 128 or more); at the end of an element of a scope, its body runs. Type errors of navigation are recorded and raised only when the value is read, so `if`, `//` and `try` see them as jq does. |
| `eval.mito` | Values (entries of the arena: spans of the input, literals of the filter, doubles, built arrays and objects), arithmetic, comparison, construction, the builtins, `try`, variables, the generators. `run(e, v)` pushes each output on to the next node (`nx` links) or to the **terminal** of the enclosing scope body: print, append to a register, fold (`add`, `length` while collecting), keep the last, count (`limit`), `//`, `try`. A container taken from the input that the filter navigates without having asked for its paths is built from its span on demand (`materialize`: one extra read of those bytes). |
| `out.mito` | Writes values as jq does: compact or indented, numbers in decNumber's form for literals and jq's double layout for results, strings re-escaped, invalid UTF-8 replaced. |
| `num.mito`, `prog.mito`, `util.mito`, `jx.mito` | numbers; exact decimal comparison; helpers; the state (one nested struct) and `@main`. |

Details that matter:

- **Scopes stream.** `.users[] | select(.age >= 85) | .n` keeps nothing between elements: the body runs when each element ends and prints. `[.users[] | .n] | length` and `.users | map(.age) | add` fold
  (no list is kept). A scope whose body uses a variable bound outside it, or that is not at the head of the filter, collects its results in a register (an arena list) and plays them back when the
  document has been read, so the outer value is complete when the rest of the filter runs; the register's memory is linear in the collected values.
- **Last key wins** (jq's rule for duplicate keys): a repeated key forgets what the earlier occurrence filled. A repeat of a named key on a path that is being streamed is an error, not a silent difference.
- **Early exit** (design decisions 2 and 3): a filter with no `[]` stops after the container that held its last filled value ends, and the unread tail is not validated. `--validate` reads and validates to the end
  and fails (exit 1; jq exits 2) when anything but white space follows the first value.
- **Missing values** are null; a missing or null value that the filter iterates is jq's error, raised when the iteration is played back.
- Empty or blank input prints nothing and exits 0, as jq does.
- **Strings**: bytes that are not valid UTF-8 are replaced as jq's decoder does when the string is printed, compared, measured or built on (one U+FFFD per invalid lead byte, one for a truncated
  or overlong sequence with its valid continuation bytes, a surrogate encoded in UTF-8 as one); a string without a byte of 128 or more needs no check, and strings that are only skipped are never checked.

## Differences from jq (expected, in `tests/xdiff.txt`)

| Case | jx | jq |
| --- | --- | --- |
| Duplicate keys inside a copied object, `length` of an object with duplicate keys (decision 1) | copied as written, counted twice | keeps the last, one key |
| Early exit with a damaged tail, or an outer repeated key after the exit point (decisions 2, 3) | answers | rejects the document / uses the last key |
| `NaN`, `Infinity`, `01`, `1.`, `.5`, `+1`, more than one top-level value | rejected (strict JSON, one document) | accepted |
| `.[]` over an object with duplicate keys | every value | only the last one per key (needs buffering) |
| Runtime error or invalid input after some results | no stdout, exit 5 | earlier results on stdout, exit 5 |
| A key with invalid UTF-8 matched by a filter key | compared as bytes | compared after replacement |
| A non-ASCII character typed in the filter on Windows | mangled by the C runtime's narrow argv to `?` (jq too, from Git Bash): write `\u00e9` | same |
| `tonumber` of `nan`, `Infinity`, `0x10` | an error | `nan` and `Infinity` are accepted |
| Output over 4 GiB, strings built by the filter over 16 MB, an arena that is full | error naming the limit (exit 1) | prints |
| `--strict` (design decision 1) | not implemented | n/a |

## Tests

- `python tests/run.py [jx.exe]`: every filter of `tests/filters.txt` (Stage 1), `filters2.txt` (Stage 2), `filters_pretty.txt` and `filters_raw.txt` over every document of `tests/docs.txt` and `tests/bad.txt` and the generated
  ones, through `jq` 1.8.2 and jx, byte for byte on standard output; where jq fails jx must fail with a message. Also the compile-time rejections, the syntax errors, the options and `--validate`.
- `python tests/fuzz.py`: random filters from the supported grammar over random documents against jq, from fixed seeds (`--seeds`, `--count`, `--only` to reproduce a case).
- `python -I tests/jqtest.py`: jq's own `tests/jq.test` (fetched as data to `D:\tmp\w\jqcompat\jq.test`, never executed) through jx, by class and by tag; `--inset` lists the cases of the Stage 2 decision set that do not pass yet.
- `python tests/numcheck.py`, `python tests/numarith.py`: the number layer against Python and jq.

Results of the last run are in the section "Results" below and in [docs/progress.md](docs/progress.md).

## Stage 3 (branch stage3, in progress)

Built: `reduce` and `foreach` (2 and 3 arguments, with patterns), destructuring `. as [$a, {b: $c}]` and `{$a}` (no `?//`, no computed keys), `def` with closure and `$` parameters (inlined at every call by parsing the body again; recursion is rejected), collectors (`sort`, `sort_by`, `group_by`, `unique`, `unique_by`, `min`, `max`, `min_by`, `max_by`, `reverse`, `flatten`, `any`, `all`, `contains`, `inside`, `in`, `IN`, `to_entries`, `keys_unsorted`, `transpose`, `join`), math (`floor ceil round sqrt fabs abs trunc exp exp2 log log2 log10 sin cos tan asin acos atan sinh cosh tanh cbrt nearbyint pow atan2 fmod infinite nan isinfinite isnan isnormal`), strings (`ascii_downcase`, `ascii_upcase`, `ltrimstr`, `rtrimstr`, `trimstr`, `startswith`, `endswith`, `split/1`, `trim`, `ltrim`, `rtrim`, `utf8bytelength`, `tojson`).
Computed indexes (`.[$k]`, `.[expr]`, negative literal indexes) stay rejected in filters: the owner postponed them; only the prelude (builtins written in jq, `prelude_text` in `src/compile.mito`) may use them. Collectors keep at most 524288 elements (a named error beyond). The parser nests at most 12 `parse_expr` levels (Mitochondria allows 64 nested calls): deeper filters, and deep expansions such as `from_entries`, `with_entries`, `map_values`, are rejected with "not supported". Values nested more than 40 levels deep are rejected when copied.
**Why `from_entries`, `with_entries` and `map_values` are rejected, and what would remove the limit.** Mitochondria allows 64 nested calls. The recursive-descent parser spends about 4 calls per nesting level of `parse_expr` (`parse_expr` -> `parse_unary` -> `parse_primary` -> `parse_expr`), plus extra calls for `if`, objects, arguments and for every inlined function call (`user_call` -> `expand_def`/`expand_closure`), so a prelude body nested 6 levels deep called from a user filter nested 4 levels deep overflows; `jj.pdepth` rejects at 12 levels instead of crashing. The analysis (`an`, limit 20 in `jj.cdepth`) and `cmp_vals`/`copy_deep`/`contains` are recursive too (guarded at 40). What would remove it, for the owner to decide: (1) an iterative parser or an explicit operand stack in `parse_expr` (about 1 call per level), (2) a flatter prelude (more helper defs, each one expression deep, at the cost of more expansions), (3) native Mitochondria implementations of `from_entries`/`map_values` in `src/lib.mito` (no parsing depth at all), or (4) raising the runtime call limit (not changed here).

Not yet built: `?//`, string interpolation, `@formats`, `label`/`break`, `indices`/`index`, `fromjson`, `implode`/`explode`, flags (`-n`, `-e`, `--arg`, ...), `$ENV`, `--explain`.

## Stage 3 (planned)

`--explain` (print the automaton and slot program for a filter), with tests/explain.txt regression pairs.

## Results

**jq.test** (jq 1.8.2's own test file, `python -I tests/jqtest.py`, details by tag in [docs/progress.md](docs/progress.md)): **196 of 531 runnable cases pass (36.9%)**, 1 differs, 0 error, 334 rejected
at compile time; 6 of the 19 `%%FAIL` cases (programs that must not compile) also pass, 13 are accepted programs jx rejects as not supported, none is accepted wrongly. The one `differ` is `"x" * range(0;12;2) + "(a star)" * 8 | try -. catch .`:
the filter contains a non-ASCII character, which the C runtime's narrow argv turns into `?` on Windows (expected difference above). Stage 1 passed 9. Of the 191 cases whose tags are all in the Stage 2 decision set
(`tests/jqtest.py --inset`), 182 pass; the 9 left are computed indexes (`.[$x]`, `.foo[.baz]`: decided as postponed), `map_values`, `_strindices`, `builtins`, the argv case and `?//` syntax.

**Corpus** (`python tests/run.py`, 33,782 cases against jq 1.8.2): 30,787 pass byte for byte (or both fail), 2,783 are listed expected differences (2,341 of them match anyway: early exit with a damaged
tail, duplicate keys), 46 of 46 compile-time rejections, 7 of 7 syntax errors (exit 3), 27 of 27 option cases (exit 2), 11 of 11 exit-code cases, 4 of 4 `--validate` cases. The full run found 212 failures that were
fixed in this stage (a filter starting with `-` taken for an option, `E?` catching more than the last step, duplicate-key documents added to the expected differences); the fixed groups were re-run and pass.
**Fuzz** (`python tests/fuzz.py`, seeds 21-24, 2,000 cases): 1,971 match jq, 0 FAIL, 23 filters rejected at compile time, 6 operations that Stage 2 refuses at run time (not wrong answers).
**Numbers**: `tests/numcheck.py` 107,478 literals against Python's float and a model of jq's printer, 0 mismatches; `tests/numarith.py` 1,000 random pairs through every operator, printing, comparison, `length`, `tostring` against jq, 0 differences.

**Time and peak memory** (Windows, whole process, median of 5 runs, peak working set; jq is the real `jq.exe`; `tools/timing.py`). Documents `{"users":[{"n","age","tags","addr"}...]}`, 16.34 MB (200,000 rows):

| filter | time ms (jx / jq / jaq) | peak MB (jx / jq / jaq) |
|---|---|---|
| `.users[0].n` | 35 / 543 / 389 | 42 / 325 / 336 |
| `.users \| length` | 131 / 614 / 452 | 42 / 325 / 336 |
| `.users[] \| select(.age >= 85) \| .n` | 76 / 733 / 643 | 43 / 325 / 336 |
| `.users[] \| .addr.city` | 91 / 820 / 852 | 46 / 325 / 336 |
| `.users[] \| {n: .n, c: .addr.city}` | 174 / 1037 / 1174 | 55 / 325 / 335 |
| `.users \| map(.age) \| add` | 72 / 716 / 497 | 42 / 330 / 337 |
| `[.users[] \| select(.age >= 85) \| .n] \| length` | 75 / 698 / 585 | 42 / 327 / 336 |
| `[.users[] \| try (.n \| tonumber) catch 0] \| length` | 119 / 863 / 672 | 42 / 330 / 336 |
| `.users \| length as $n \| $n * 2` | 59 / 534 / 392 | 42 / 325 / 336 |
| `[limit(3; .users[])] \| length` | 68 / 534 / 389 | 50 / 325 / 336 |
| `.users[] \| .age + 1` | 116 / 841 / 803 | 43 / 325 / 336 |

The same on the 1.59 MB document is in docs/progress.md. The floor of a whole run on a tiny document is 27 ms for jx (Stage 1: 10 ms, jq 9 ms, jaq 13 ms): the runtime commits the arena arrays and the output buffer at start (see Limits),
which is why the plain-path rows (`.users[0].n`: 35 ms on 1.59 MB, 59 ms on 16 MB against Stage 1's 19) are dominated by start-up and reading standard input, not by the scan. Early exit works in the expression engine: `.users[0].n` reads only up to the end of
the first element (0.2 s on the 529 MB document, which is the time to read standard input; `.users | length`, which must scan the whole array, takes 1.1 s).

**529 MB document** (6.5 million rows, `D:\tmp\w\big500.json`, one run each, seconds / peak working set in MB; `python -I bench/big.py`):

| filter | jx s / MB | jq s / MB | jaq s / MB | output bytes (jx) |
|---|---|---|---|---|
| `.users[0].n` | 0.2 / 554 | 40.5 / 10334 | 24.3 / 10602 | 8 |
| `.users | length` | 1.1 / 554 | 36.2 / 10334 | 18.1 / 10602 | 8 |
| `.users[] | select(.age >= 85) | .n` | 1.6 / 566 | 48.4 / 10333 | 32.2 / 10602 | 5997400 |
| `.users[] | .addr.city` | 1.8 / 630 | 52.8 / 10334 | 66.3 / 10602 | 37700000 |
| `.users[] | {n: .n, c: .addr.city}` | 5.4 / 940 | 68.1 / 10334 | 84.5 / 10602 | 192588890 |
| `.users | map(.age) | add` | 1.5 / 554 | 51.2 / 10486 | 24.8 / 10602 | 10 |
| `[.users[] | select(.age >= 85) | .n] | length` | 1.6 / 554 | 48.2 / 10343 | 29.8 / 10602 | 7 |

**529 MB document, final bytecode build** (commit 04ce47d built with the Mitochondria compiler at main b27b504; seconds / peak working set in MB, one run each, jq 1.8.2 and jaq 3.1.2; the tree column is the frozen Stage 2 tree build):

| filter | bytecode s / MB | tree s / MB | jq s / MB | jaq s / MB |
|---|---|---|---|---|
| `.users[0].n` | 0.3 / 554 | 0.2 / 554 | 39.1 / 10333 | 18.8 / 10602 |
| `.users | length` | 1.2 / 554 | 1.1 / 554 | 37.5 / 10333 | 18.4 / 10602 |
| `.users[] | select(.age >= 85) | .n` | 1.7 / 567 | 1.7 / 566 | 50.0 / 10334 | 33.2 / 10602 |
| `.users[] | .addr.city` | 1.9 / 630 | 2.0 / 630 | 56.3 / 10334 | 64.1 / 10602 |
| `.users[] | {n: .n, c: .addr.city}` | 4.0 / 940 | 5.7 / 940 | 71.4 / 10334 | 82.7 / 10602 |
| `.users | map(.age) | add` | 1.6 / 555 | 1.6 / 555 | 54.6 / 10487 | 25.4 / 10602 |
| `[.users[] | select(.age >= 85) | .n] | length` | 1.7 / 555 | 1.6 / 554 | 51.2 / 10343 | 30.0 / 10602 |

Output of the bytecode, tree and jaq builds is byte-identical on all seven (jq differs only by CRLF line ends). Verification of the final build: `tests/run.py` 30,595 pass, 1 known fail (`nums` `.age|tostring|tonumber`, the tree build fails it too), 3,186 expected differences, 46/46 rejects, 7/7 syntax, 27/27 options; `tests/bcdiff.py` against the tree build: 0 differences on the 33,782-case corpus and 12,000 fuzz cases (seeds 1-30 x 400); jq.test 196/531 (1 differ, 0 error); `tests/dump.py`: 36 golden `--dump-program` dumps.

jx holds the input once (the 554 MB floor); `jq` builds the whole document (10.3 GB peak) and so does `jaq` (10.6 GB). The default build (clang -O3) is as fast as the one with the larger inlining budget now that
Mitochondria emits `byte_at` as an inline load (`.users | length` on the 16 MB document: 60 ms, 67 ms for Stage 1 with the inlining flag), so `build.sh` no longer sets it (`INLINE=1 ./build.sh` still does).

**Byte-touch accounting.** The scan loop is unchanged from Stage 1 (still about 1.55 reads per input byte for `.users | length`: the loops look ahead one byte at the end of each token); Stage 2 removed the second read of a compared integer
(it is parsed while the digits pass) and does not add reads for values that are only skipped. A matched key is still compared once more (`find_key`), and a container that the filter navigates without having asked for its paths is read once more
when it is built (`materialize`). Reading each byte into a local and dispatching on it (decision (d)) was not done in this stage.
