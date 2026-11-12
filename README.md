# jx

A jq-compatible filter engine that is a scanner and extractor, not a parser: the filter is compiled before the input is read into a
path automaton (a trie of the paths the filter needs) and a small slot program; the input is then read once, front to back, checking
its structure as it goes and keeping only the spans of the values the filter asked for. Nothing is allocated at run time. Written in
the [Mitochondria](https://github.com/benwmaddox/mitochondria) language. The design is [docs/design.md](docs/design.md); this is its
**Stage 1**.

## Build and run

```
./build.sh jx.exe                  # needs the Mitochondria compiler (MITO=path/to/mito.exe), built from its main branch
echo '{"users":[{"n":"ann","age":91},{"n":"bo","age":7}]}' | ./jx.exe -c '.users[] | select(.age >= 85) | .n'
"ann"
```

jx reads one document on standard input and takes the filter as its first argument; flags are `-c` (compact; the default is jq's
indented output) and `-r` (a string result is written raw). Results are written after the whole document has been read; an error
writes a message to standard error and exits with 1 (jq uses 2, 3 and 5), with nothing on standard output.

The input size is the one literal in `doc: utf8<1073741824>` in `src/jx.mito` (1 GiB; the runtime reserves it and commits pages as
they are read, so a small input costs nothing). Output is capped at 32 MB (`Out.text`), strings with escapes at 1 MB when they are
compared (`J.tmp`); depth is 10000 like jq. `build.sh` adds `-mllvm -inline-threshold=10000` to clang's flags: see Measurements.

## What it supports

| Filter | |
| --- | --- |
| `.` | the document, indented or compact |
| `.name`, `."odd key"`, `.["key"]`, `.a.b`, `.a[0].b`, `.a.[0]` | a field or an element; null when missing |
| `.[n]` | an element by a non-negative constant index |
| `.[]` | each element of an array, or each value of an object |
| `a \| b` | pipes; a path after a `select` continues from the same value |
| `select(PATH)`, `select(PATH OP LITERAL)` | OP is `==` `!=` `<` `<=` `>` `>=`; a literal is a number, a string, `true`, `false` or `null`; compared in jq's order (null < false < true < numbers < strings < arrays < objects), numbers exactly as decimals (`1.0 == 1`, `1e3 == 1000`, 21-digit integers) |
| `length` | of an array or object (counted while scanning), string (codepoints), number (absolute value), null; an error for booleans. It must be the last step |
| `-c`, `-r` | as in jq |

Output matches jq 1.8.2 byte for byte for everything above, including the forms jq canonicalizes: numbers are written in decNumber's
form (`1e3` -> `1E+3`, `0.0001e5` -> `1E+1`, `1.0` stays), strings are re-escaped as jq does (`\u00e9` -> `é`, `\/` -> `/`, DEL and
controls as `\u00XX`, lone low surrogates as U+FFFD), also inside copied arrays and objects. Runtime type errors are jq's (`Cannot index
number with "a"`, `Cannot iterate over null`).

## What is rejected, and how

Everything else is rejected **when the filter is compiled**, before any input is read: exit code 1, `jx: not supported in Stage 1: ...`
with the filter position, nothing on standard output. There is no fallback engine. `tests/reject.txt` lists 36 of them, for example
`..`, `.[-1]` (needs the array's length), `.[1:2]`, `.a?`, `.[]?`, `,`, `+`, `//`, `keys`, `type`, `map(...)`, `add`, `first`,
`if`, `as`, `reduce`, object and array construction, `and`/`or`/`not`, a comparison with anything but a literal, `select(.a | ...)`,
`select` with a `[]` inside, a string interpolation, a step after `length`, and a `[]` after a `select` (that needs buffering, Stage 3).
The old `examples/jx` filters `keys` and `type` are in this list (Stage 2).

## How it works (files in `src/`)

| File | |
| --- | --- |
| `compile.mito` | Parses the filter once (no tree). Paths become **nodes** of a trie: a node is "the value reached by this path", with child entries by key, by index and by `[]`. A node whose value the program uses is **wanted** and owns a slot. A `select` adds a comparison instruction; the end of the filter adds `OUT` or `LEN`. The **unit** is the node under the deepest `[]` on the result's path (an element); with no `[]` the unit is the document. |
| `scan.mito` | The scanner. One loop with three modes (a value starts, a value ended, a key starts) and an explicit stack of open containers (depth 10000). Each open container carries its automaton node, or -1 when nobody wants it (it is then only skipped, but still checked: brackets pair, commas and colons are where they belong, strings end, escapes and `\u` surrogate pairs are valid, numbers follow the JSON grammar, literals are spelled out). When a wanted value ends its slot gets (tag, start, end, count). When a unit ends the program runs and the slots are cleared by bumping a generation number. |
| `prog.mito` | The slot program: `CMP slot, literal*8+op` (a failed comparison ends the unit: `select`), `OUT slot`, `LEN slot`. Exact decimal comparison of number spans; string comparison decodes escapes only when the string has one. |
| `out.mito` | Writes a value from its span: compact or indented, numbers and strings normalized as jq does. |
| `util.mito`, `jx.mito` | helpers; the state (one nested struct `J`) and `@main`. |

Details that matter:

- **Last key wins** (jq's rule for duplicate keys): a repeated key forgets what the earlier occurrence filled. A repeat on a path that is being streamed (`.users[]` with two `users` keys) is an error, not a silently different answer.
- **Early exit** (design decisions 2 and 3): a filter with no `[]` stops after the container that held its last filled value ends (so `.users[0].n` reads up to the end of the first element), and the unread tail is not validated. A document with trailing data after its root value is an error (jx reads one document; jq would run the filter on each).
- **Missing values** are null; a missing or null value that the filter iterates is jq's error, found when the enclosing container ends.
- Empty or blank input prints nothing and exits 0, as jq does.

## Differences from jq (expected, in `tests/xdiff.txt`)

| Case | jx | jq |
| --- | --- | --- |
| Duplicate keys inside a copied object, `length` of an object with duplicate keys (decision 1) | copied as written, counted twice | keeps the last, one key |
| Early exit with a damaged tail, or an outer repeated key after the exit point (decisions 2, 3) | answers | rejects the document / uses the last key |
| `NaN`, `Infinity`, `01`, `1.`, `.5`, `+1`, more than one top-level value | rejected (strict JSON, one document) | accepted |
| Invalid UTF-8 | copied through | replaced by U+FFFD |
| Runtime error after some results | no stdout, exit 1 | earlier results on stdout, exit 5 |
| Malformed input | exit 1 | exit 2 |
| Pretty output more than 32 MB | error (`Out.text` is a declared size) | prints |
| A non-ASCII character typed in the filter on Windows | mangled by the C runtime's narrow argv (jq too, from Git Bash): write `\u00e9` | same |
| `--strict` (design decision 1) | not implemented | n/a |

## Tests

`python tests/run.py [jx.exe]` runs every filter of `tests/filters.txt` (174, over 73 documents, `-c`), `filters_pretty.txt` (9, indented),
`filters_raw.txt` (11, with `-r` and `-c -r`) through `jq` 1.8.2 and jx and compares standard output byte for byte; where jq fails, jx must
fail with a message on standard error. Documents: `tests/docs.txt` (nested and escaped strings, unicode escapes, surrogates, numbers such as
`1e3`, `0.0001e5`, 21-digit integers, duplicate keys, empty arrays and objects, whitespace variations, comparisons across types), `tests/bad.txt`
(40 malformed or jq-only inputs) and some generated in `run.py` (CRLF, no final newline, empty, blank, raw tab, invalid UTF-8, BOM, depth 9999 and 10001, a
300-row table, early-exit tails). The 36 compile-time rejections are checked for the exit code, the message and an empty standard output.
`JX_K=text` and `JX_DOCS=text` select filters and documents. Result of the last run: see Measurements.

## Byte-touch accounting

A byte is touched when a loop reads it to decide something. Per filter, for a row `{"n":"user7","age":55,"tags":["a","b"],"addr":{"city":"c7","zip":21}}`:

| Filter | Touches per input byte |
| --- | --- |
| every filter, every byte the scanner reaches | **1** in the scanner loop (the byte decides structure, validity and, if wanted, the span end). There is no second skipping pass and no separate validation pass |
| `.users[0].n` | 1 for the bytes up to the end of `users[0]`; **0** after (early exit). The runtime still reads all of stdin into memory first, which costs about 0.75 ms per MB |
| `.users \| length` | 1; the array's count is kept by the frame, so `length` costs 0 extra touches |
| `.users[] \| select(.age >= 85) \| .n` | 1, plus the `age` digits read again at comparison time (2-3 bytes of about 80), plus matched key names read again by the key comparison (`n`, `age`, `users`), plus the copy of the output string for passing rows |
| `.users[] \| .addr.city` | 1, plus the matched key names again, plus the output copy of each city |
| a container result (`.users[0]`) | 1 for the scan, plus 1 more in the output formatter, which re-tokenizes the span to strip whitespace or indent and to normalize numbers and strings |
| `length` of a string | 1 plus one pass over the string for the codepoint count |

The design's table (1.3) says key bytes are touched once and Number kind digits are parsed inline; Stage 1 reads matched keys twice and
compared numbers twice. Both are small (a few bytes per row), and both are the first things to fold into the scan loop in Stage 2.
There is no instrumented build: the counts above come from the code (every byte passes through `scan_string`, `scan_number`,
`scan_literal` or the whitespace skip exactly once).

## Measurements

Windows, the whole process (start, read stdin, filter, write), median of 15 runs (5 for the 16 MB document), `python bench/bench.py`
(`JX`, `JXI`, `OLDJX` name the executables). Documents `{"users":[{"n":"user%d","age":N,"tags":["a","b"],"addr":{"city":"c%d","zip":N}}...]}`.
"jx" is the default clang -O3 build, "jx inline" is `./build.sh` (adds `-mllvm -inline-threshold=10000`), "old jx" is `examples/jx` from
Mitochondria's main (which now reads up to 4 GiB). Milliseconds; jq 1.8.2, jaq 3.1.2.

| rows | size | filter | jx | jx inline | old jx | jq | jaq |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 5 | 0.00 MB | `.users[0].n` | 11 | 11 | 52 | 47 | 14 |
| 5 | 0.00 MB | `.users \| length` | 10 | 11 | 53 | 48 | 17 |
| 5 | 0.00 MB | `.users[] \| select(.age >= 85) \| .n` | 12 | 12 | 52 | 46 | 16 |
| 5 | 0.00 MB | `.users[] \| .addr.city` | 11 | 12 | 52 | 45 | 17 |
| 20000 | 1.59 MB | `.users[0].n` | 12 | 12 | 66 | 103 | 57 |
| 20000 | 1.59 MB | `.users \| length` | 25 | 17 | 81 | 105 | 57 |
| 20000 | 1.59 MB | `.users[] \| select(.age >= 85) \| .n` | 30 | 20 | 96 | 127 | 86 |
| 20000 | 1.59 MB | `.users[] \| .addr.city` | 28 | 20 | 104 | 138 | 130 |
| 200000 | 16.34 MB | `.users[0].n` | 22 | 23 | 199 | 668 | 445 |
| 200000 | 16.34 MB | `.users \| length` | 148 | 64 | 354 | 660 | 447 |
| 200000 | 16.34 MB | `.users[] \| select(.age >= 85) \| .n` | 194 | 96 | 493 | 867 | 719 |
| 200000 | 16.34 MB | `.users[] \| .addr.city` | 176 | 90 | 563 | 978 | 1001 |

What the numbers say:

- The single pass pays: at 16 MB the inline build is 7 to 10 times faster than jq and 5 to 11 times faster than jaq on the three streaming filters, and the
  early-exit filter is 22 ms against 445 to 668 ms (the time is then reading stdin: 11 ms at 1.6 MB to 22 ms at 16 MB).
- The process floor is about 11 ms (an empty 5-row document), so at 1.6 MB the scan is 1 to 9 ms. The scan costs about 2.5 ms per MB for `length`
  and 4 to 4.5 ms per MB when it also compares and copies (about 360 ns per row for the select filter). The design's goal was 3 ms per MB or less for
  streaming filters touching few fields: met for `length`, missed by 1.5 times for select and city. Not reached: the model's skip rate of 0.3 to 1.5 GB/s (this is 0.25 to 0.4 GB/s).
- **Where it is slower than expected, and why.** In the default build the scan runs at 7 to 8 ms per MB, not 2.5. The C that `mito build` emits reads
  every input byte with `byte_at`, which is a call through the runtime's function table (`mito_h.builtin(c, 58, ...)`), and clang does not inline it into the big scanner
  function with its default budget. `-mllvm -inline-threshold=10000` makes clang inline it and gives 2.3 times (148 to 64 ms, 194 to 96 ms). The compiler should emit
  `byte_at` (and the per-iteration `text_len` call in loops) as a direct load; that is a code generator fix, not something jx can do from the language.
- The remaining per-row cost is key lookup (a length and first-byte test, then a text comparison per candidate key), the generation bump and the
  program dispatch per unit, and the output copies; none of it is a second pass over the input.
