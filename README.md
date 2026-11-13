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

jx reads one document (standard input, or one input file) and takes the filter as its first argument; flags are `-c` (compact; the default is jq's
indented output), `-r` (a string result is written raw) and `--validate` (below). Results are written after the whole document has been read; an error
writes a message to standard error and exits with 1 (jq uses 2, 3 and 5), with nothing on standard output.

**Options.** jx parses its own arguments (the program takes the runtime's raw `args`), so an option is understood or refused wherever it is written, before or
after the filter, long or short, combined (`-cr`): `-c`, `-r`, `-j`, `-n`, `-e`, `-s`/`--slurp`, `-a`/`--ascii-output`, `--seq`, `-M`, `--tab`, `--indent n`, `--arg`,
`--argjson`, `--args`, `--jsonargs`, `--slurpfile`, `--rawfile`, `-f`/`--from-file`, `-R`/`--raw-input`, `-h`/`--help`, `-V`/`--version`, `--validate`, `--explain`
and `--dump-program` are built; every other jq option is a hard error before anything is read, `jx: option '-S' is not supported yet` (`-S -C -L -b` and `--stream
--stream-errors --sort-keys --color-output --raw-output0 --library-path --binary --build-configuration --strict`), `jx: unknown option '--bogus'` for anything else.
Standard input is read only when the filter needs it (`stdin_text`, a Mitochondria runtime feature): `-n`, `--explain`, `--dump-program`, `--help`, `--version` and a
run with an input file never wait for it. `jx --version` prints `jx 0.1` (jq prints `jq-1.8.2`); `--help` prints a short usage text of jx's own.
`-s` wraps the one document in an array (no input at all gives `[]`); a second value is the usual "more than one JSON value" error, so `-s` over several
documents fails instead of answering. `-a` writes every character above 127 as a `u`-escape (and with `-r` a string is still written quoted, as jq does); `--seq` writes
a record separator (U+001E) before each result. `-S` is refused because document values are copied as spans and never parsed, so keys cannot be sorted
without parsing every object; `-C` because the writer copies spans; `-L` (modules) by owner scope.

**Input files.** `jx FILTER FILE` reads the file as the document (`-` is standard input). jx reads one document, so exactly one file is accepted; a second one is
`jx: not supported yet: more than one input file` (exit 2), and so is a file holding several values (the usual "more than one JSON value" error). A file that
cannot be opened is `jx: error: Could not open file NAME: No such file or directory` (exit 2, as jq; jq's text starts with `jq:`). `-n` never opens the file.
`-f FILE` / `--from-file FILE` reads the filter from a file (jq's flag takes the first plain argument as the file name: `jx -f prog.jq data.json`); the filter
may have `#` comments and any whitespace, with jq 1.8's rule that a comment goes on past a line break preceded by an odd number of backslashes (also before CRLF); comments are
accepted in filters given on the command line too (up to 65,536 bytes of filter text, 16,384 bytes of builtins written in jq). `--slurpfile NAME FILE` binds `$NAME` to an array of
every value in the file and `--rawfile NAME FILE` to its text; both appear in `$ARGS.named` (the first of several options with one name wins, as in jq). The files
are read when the filter is compiled and held with the filter's literals (4 MiB in all; a bigger file is `jx: ... is too large`); a `--slurpfile` file that is not
JSON fails when `$NAME` is used (exit 5; jq exits 2 with `Bad JSON in --slurpfile` before it starts). `-R`/`--raw-input` makes the input one string: with
`-s` the whole text (also empty), without it the one line (several lines would be one document each and are `not supported yet`; up to 16 MiB as a JSON string);
`-n` ignores the input as always. `$ENV` and `env` give the environment as an object (built only when the filter mentions `ENV` or `env`; up to 1 MiB of environment);
`input_filename` is `null` with `-n` and otherwise the file name (`<stdin>` for standard input, as jq 1.8.2 does); `input_line_number` is jq's count of the input
lines read when the first value is complete (jq reads 4,095-byte pieces; the number is worked out the same way). `debug`, `debug(msg)` and `stderr` write to
standard error while the filter runs (`["DEBUG:",value]` and a line break; `stderr` writes a string raw and any other value as compact JSON, no line break, as jq 1.8.2);
standard output is written at the end, so the two streams are only ordered as jq orders them when you capture them separately (`tests/runtime.py` compares both).

Everything else is rejected **when the filter is compiled**, before any input is read: exit code 1, `jx: not supported in Stage 2: ...` with the filter position,
nothing on standard output. There is no fallback engine. By owner scope (Stage 3) these stay rejected: regular expressions (`test match capture sub gsub scan
splits`), `walk`, `path paths getpath setpath delpaths del pick`, `tostream fromstream truncate_stream`, assignment and update (`=`, `|=`, `+=` ...), computed
and negative indexes in user filters (only the built-in prelude may use them), `..` and `recurse`, dates, modules (`import`, `include`), `$__loc__`,
SQL-style operators, `input`/`inputs`, and a `[]` together with a key or an index on the same value (`.[] , .a`). `tests/reject.txt`
lists them. Syntax errors exit with 1 and say `syntax error` (`tests/syntax.txt`). A few operations on values of the document that jx does not parse fail at run
time with `not supported` (a repeated string over 15 MB, `keys` of an object with more than 4,000 keys).

**Mitochondria runtime features used.** `stdin_text` (stdin read on first use), `from env`, `read_file`/`file_exists`, `eprint` and the libm builtins (Mitochondria PR #47,
compiler built from commit 31f49b2 or later: `build.sh` looks for `target/jxrx-mito`, `MITO=` overrides; an older compiler gives a false 27 ms start-up).
Still missing in the runtime: `hypot`-style functions `jn`, `yn`, `erf`, `erfc` (so these three are rejected), `input`/`inputs` and a way to exit from a filter (`halt`).

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
- `python tests/fuzz.py --grammar base|s3|mixed`, `python tests/explain.py`: golden `--explain` outputs.
- `python tests/fuzz.py`: random filters from the supported grammar over random documents against jq, from fixed seeds (`--seeds`, `--count`, `--only` to reproduce a case).
- `python -I tests/jqtest.py`: jq's own `tests/jq.test` (fetched as data to `D:\tmp\w\jqcompat\jq.test`, never executed) through jx, by class and by tag; `--inset` lists the cases of the Stage 2 decision set that do not pass yet.
- `python tests/numcheck.py`, `python tests/numarith.py`: the number layer against Python and jq.

Results of the last run are in the section "Results" below and in [docs/progress.md](docs/progress.md).

## Stage 3 (branch stage3, in progress)

**Verification (stage3-verified, 2026-11-12).** Full `tests/run.py`: 36,652 cases, 33,195 pass, 3,456 expected differences, 1 fail (`nums`: `.users[] | (.age | tostring | tonumber)`, the known `tonumber` difference, identical to Stage 2); the old `join` failures are gone. `tests/fuzz.py --grammar s3` (reduce, foreach, def, patterns, collectors, math, strings over random documents): 4,000 cases, 0 FAIL after two fixes (`abs` on strings, arrays and objects returns them unchanged and only null and booleans fail; `transpose` as jq 1.8.2 defines it, so objects work). Golden dumps: 36 of 36 unchanged.
**Start-up note.** Building with the older `jx-mito2` compiler gave a 27 ms start-up (tiny document) against 10 ms; `build.sh` now defaults to the `jxs3-mito` compiler (Mitochondria main b27b504), and the Stage 3 build matches the bytecode-final build within 3% on the 16 MB document (median of 15 alternating runs: tiny 10.2 vs 10.2 ms, `.users[] | .n` 68.8 vs 64.8, select 63.7 vs 62.0, `.addr.city` 75.0 vs 72.1, `{n,c}` 128.4 vs 130.7). The prelude costs nothing measurable at start-up.


Built: `reduce` and `foreach` (2 and 3 arguments, with patterns), destructuring `. as [$a, {b: $c}]` and `{$a}` (`?//` below, no computed keys), `def` with closure and `$` parameters (inlined at every call by parsing the body again; recursion is rejected), collectors (`sort`, `sort_by`, `group_by`, `unique`, `unique_by`, `min`, `max`, `min_by`, `max_by`, `reverse`, `flatten`, `any`, `all`, `contains`, `inside`, `in`, `IN`, `to_entries`, `keys_unsorted`, `transpose`, `join`), math (`floor ceil round sqrt fabs abs trunc exp exp2 log log2 log10 sin cos tan asin acos atan sinh cosh tanh cbrt nearbyint pow atan2 fmod infinite nan isinfinite isnan isnormal`, and from the runtime-features branch `exp10 expm1 log1p acosh asinh atanh logb rint significand gamma lgamma tgamma lgamma_r j0 j1 y0 y1 frexp modf copysign drem remainder nextafter nexttoward scalb scalbln ldexp fmin fmax hypot fdim fma`; `jn yn erf erfc` stay rejected, the runtime has no function for them), strings (`ascii_downcase`, `ascii_upcase`, `ltrimstr`, `rtrimstr`, `trimstr`, `startswith`, `endswith`, `split/1`, `trim`, `ltrim`, `rtrim`, `utf8bytelength`, `tojson`).
Computed indexes (`.[$k]`, `.[expr]`, negative literal indexes) stay rejected in filters: the owner postponed them; only the prelude (builtins written in jq, `prelude_text` in `src/compile.mito`) may use them. Collectors keep at most 524288 elements (a named error beyond). The parser nests at most 12 `parse_expr` levels (Mitochondria allows 64 nested calls): deeper filters, and deep expansions such as `from_entries`, `with_entries`, `map_values`, are rejected with "not supported". Values nested more than 40 levels deep are rejected when copied.
**`from_entries`, `with_entries`, `map_values`.** They overflowed Mitochondria's 64 nested calls when written in the prelude. `from_entries` is now native (`from_entries_of` in `src/lib.mito`, builtin id 34) with jq 1.8.2's rules, probed against the real jq: key = `.key // .Key // .name // .Name` (`k`, `K`, `v`, `V` are not read in 1.8.2), value = `.value` if the entry has a `value` field, else `.Value`, else null; a key that is not a string is `Cannot use T (v) as object key`; later entries win. `with_entries(f)` is `to_entries | map(f) | from_entries`, `map_values(f)` keeps the first output of `f` per element and drops the element when `f` is empty (jq 1.8). Keys are looked up in a list, so `from_entries` is quadratic in the number of distinct keys. Two calls of `map_values` nested in each other still hit the parse limit and are rejected. The recursive-descent parser spends about 4 calls per nesting level, so `jj.pdepth` rejects at 12 levels instead of crashing (an iterative parser would lift it). The analysis (`an`, limit 20 in `jj.cdepth`) and `cmp_vals`/`copy_deep`/`contains` are recursive too (guarded at 40).

**stage3-strings-flags result.** jq.test 359/531 (67.6%), differ 3, error 3, rejected 166. The differ and error cases are all documented: line 2005 (non-ASCII filter text on the Windows command line), lines 2319 and 2407 (input with `nan`, non-strict), lines 2324 and 2498 (`fromjson` error wording), and line 2359 (jq prints `"hi there!"` before the error, jx writes no partial output on an error). Full `tests/run.py`: 37,703 cases, 33,992 pass, 3,668 expected differences, and the only fails were two of this branch's own corpus lines that use `?//` mixes now rejected (replaced); `tests/fuzz.py --grammar s3` over 20,000 cases with 0 FAIL after the fixes above; golden dumps 36 of 36. Optimized build on the 16.3 MB document (median ms, peak 42 MB): `.users[0].n` 17, `.users[] | select(.age >= 85) | .n` 65, `.users[] | .age + 1` 106, against jq 556/766/850 and jaq 413/-/824.
**Later in Stage 3.** `?//` alternative destructuring (a pattern error or a body error continues with the next alternative on the same value, as nested `try`s; every name of any alternative is a variable, null where the pattern does not bind it); alternatives may mix array and object patterns and nest containers. String interpolation (`"a \(.x)"`: `tostring` of each value, added left to right as jq does) and the formats `@text @json @csv @tsv @html @uri @sh @base64 @base64d`, also as `@fmt "string \(x)"` (the format applies to the interpolated values; `@base32`, `@base32d` and unknown names are compile errors, as in jq 1.8.2). `indices`, `index`, `rindex` (strings: codepoint offsets of overlapping matches; arrays: element or subarray), `explode`, `implode`, `fromjson` (strict JSON; `nan`, `NaN`, `Infinity` and their negatives are accepted as jq does; other non-JSON text is an error whose wording differs from jq's, see Expected differences added), `tostring` edge cases, and a fix for error text that was cut inside a multi-byte character. Flags: `-n` (input null; the runtime still reads standard input to its end), `-e` (exit 1 when the last output is null or false, 4 when there is none; with `-r`, a last output that prints as `null` or `false` cannot be told from the string and is an error), `-j`, `-M` and `--unbuffered` (accepted), `--arg`, `--argjson`, `$ARGS.named` and `$ARGS.positional` with `--args` and `--jsonargs`, `--indent n` (0 to 7; 0 writes newlines without indentation, as jq 1.8.2 does), `--tab`. Still rejected (usage error 2 or "not supported"): `-s`, `-S`, `-a`, `-C`, `-f`, `--stream`, `--seq`, `--slurpfile`, `--rawfile`, `-R`, `$ENV` and `env` (Mitochondria has no environment access), `input` and `inputs`, `label` and `break`, `--explain`.
**Mixed-shape bug (fixed).** Present in Stage 2 and the bytecode build on main (d071893 reproduces it): when the same value was read by key in one branch and by index in another and the document mixed shapes, an index or key read was lost (`echo '[{"a":1},[4]]' | jx -c '.[] | [.a?, .[0]?]'` printed `[1]` and `[]` instead of `[1]` and `[4]`). Cause: the scanner records "this node was not an object / not an array" per node with one generation counter shared by the key and the index children; an element of one shape made the stale mark of the other kind look current for the next element. Fix: separate generations per kind (`serrg` for keys, `serrgi` for indexes), so an object container uses only the key entries and an array container only the index entries of the same automaton node. Regression cases are in `tests/filters2.txt` (mixed_shapes and mixed_objs documents), and `tests/fuzz.py --grammar mixed` generates documents with objects, arrays and scalars at the same positions and filters that read the same node by key, by index and by iteration with `?`, `//`, `type`, `try`, `if`. The `?//` guard (alternatives mixing array and object patterns, nested containers) is lifted. Two related bugs found by the new fuzz and corpus: `(.a.b)?` was parsed as `.a | (.b)?` (a parenthesized term is one term), and an error raised in the continuation of two nested `try`s was caught by the outer one.
**`label`/`break`.** `label $x | body` runs the body in a frame that catches `break $x`; as in jq 1.8.2 a break is the error `{"__jq": N}` (N the number of the label in the program), so `try`/`?` inside the label catch it (`[label $x | try (1, break $x) catch .]` is `[1,{"__jq":0}]`) and the label resumes on it. A body that breaks to an outer label is not streamed (labels are treated like outer variables by the stream analysis). Labels are numbered in the order they appear in the filter; a `def` that contains a label and is called twice gets two numbers (jq gives one), which only shows if a `catch` prints the break object.
**`--explain`.** `jx --explain FILTER` prints the automaton (path of each node, slot, iterates, unit, streamed), the scopes and the program with the paths of the nodes it reads; `tests/explain.py` checks 20 golden outputs (`tests/explain.txt`; `--update` rewrites them). `--dump-program` keeps its raw form (`tests/dump.py`).
**Other additions.** `-s`, `-a`, `--seq` (above); `tonumber` keeps the literal digits of any strict JSON number string, as jq 1.8.2 does (`"85.0" | tonumber` prints `85.0`); `limit` with a negative count is jq's error. Not done: `-S`, `-C`, `-f`, `input_line_number`, `debug`, `stderr`, `ldexp scalb scalbln drem significand gamma lgamma tgamma frexp modf logb expm1 log1p exp10 rint j0 j1 y0 y1` and the other libm functions (Mitochondria has no libm access beyond its own math built-ins, and an approximation would not be exact).
**Expected differences added.** The `fromjson` error text for invalid JSON differs from jq's (jq words the position and the parser state; jx says the text is not strict JSON), so `try fromjson catch .` differs on invalid text (jq.test lines 2324 and 2498). `tojson | fromjson` and `map(try implode catch .)` on inputs with `nan` are the existing non-strict-input differences.

## Results

**529 MB document, stage3-shapefix build** (jx only, seconds / peak MB, one run each; jq and jaq numbers are the ones above): `.users[0].n` 0.2 / 554, `.users | length` 1.0 / 555, `select` 1.5 / 567, `{n: .n, c: .addr.city}` 4.4 / 940, `[label $o | .users[] | .age, break $o]` 1.4 / 802 (the label forces the whole array to be read as a value). `reduce .users[] as $u (0; . + $u.age)` fails on this document: `out of value memory at nesting depth 0` (the loop keeps 6.5 million element values; reduce over huge arrays is a known limit, fine on the 16 MB document).


**jq.test** (jq 1.8.2's own test file, `python -I tests/jqtest.py`, details by tag in [docs/progress.md](docs/progress.md)): **196 of 531 runnable cases pass (36.9%)**, 1 differs, 0 error, 334 rejected
at compile time; 6 of the 19 `%%FAIL` cases (programs that must not compile) also pass, 13 are accepted programs jx rejects as not supported, none is accepted wrongly. The one `differ` is `"x" * range(0;12;2) + "(a star)" * 8 | try -. catch .`:
the filter contains a non-ASCII character, which the C runtime's narrow argv turns into `?` on Windows (expected difference above). Stage 1 passed 9. Of the 191 cases whose tags are all in the Stage 2 decision set
(`tests/jqtest.py --inset`), 182 pass; the 9 left are computed indexes (`.[$x]`, `.foo[.baz]`: decided as postponed), `_strindices`, `builtins`, the argv case and `?//` syntax.

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

**runtime-features result.** jq.test 365/531 (68.7%), differ 3, error 3, rejected 160 (the same 3 and 3 as before; the benchmark of what the runtime adds is `tests/runtime.py`: 247 differential cases against jq 1.8.2, standard output, exit code and, for `debug`/`stderr`, standard error byte for byte, plus `--math`: 63 function sweeps over 47 values and over value pairs). Math is the platform's C library: on the Windows build `lgamma`/`gamma` are less accurate near 1 and 2 than glibc (relative error 1e-10 at 1.0000000001), jq.exe's own libm differs from the Windows C library in the last digit of `lgamma` for some arguments and returns a wrong value for `lgamma` of subnormals, `frexp` of infinity/NaN gives exponent 0 here and -1 in jq.exe, and `exp10 gamma lgamma_r significand drem scalb` do not exist in the chocolatey jq.exe at all (checked against Python's `math` instead). `debug`/`stderr` are refused next to `first limit any all isempty label nth` because jx evaluates every element of an array it streams where jq stops at the first result, and with a debug in both operands of an operator jq evaluates the right one first (jx the left): stdout is the same, the order of the debug lines is not. `$ENV` values with non-ASCII text are exact in jx; Windows jq.exe replaces them with U+FFFD, and the Windows command line passes a non-ASCII filter to jx in the ANSI code page.
