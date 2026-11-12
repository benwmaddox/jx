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

**Options.** Every other jq option is refused by name before anything is read: `jx: option '-S' is not supported yet` for a jq option that is not built
yet (`-n -s -e -S -C -M -a -j -f -L -R -h -V --tab --indent --arg --argjson --args --jsonargs --slurp --stream --seq --slurpfile --rawfile --help --version
--unbuffered --binary --strict --explain`), `jx: unknown option '-Z'` for anything else with a letter. jq exits with 2 on a usage error; a Mitochondria
command-line program can only exit with 1 (a status of 400 or more), so jx exits with 1. What the runtime's flag handling (`runtime/cli.c`) does not let a
program catch: an unknown long option written **after** the filter, and long options with a hyphen (`--raw-output`, `--sort-keys`, `--null-input`, ...), are not
passed to the program at all and are silently ignored; an unknown long option written **before** the filter takes the filter as its value (jx then says
"no filter given"). `--validate .a` is understood (the option gives the filter back).

**Limits.** The input is up to 1 GiB (the literal in `doc: utf8<1073741824>` in `src/jx.mito`; the runtime reserves it and commits pages as they are read, so a small input
costs nothing). The output area is 3 GiB (`Out.text`; the runtime allows 4 GiB - 1 for an answer but a field declared with that size misbehaves in the generated
code, a Mitochondria issue reported with this stage). A 529 MB input, a 138 MB indented output and a 37 MB compact output were run. Strings with escapes are
compared up to 1 MB (`J.tmp`); depth is 10000 like jq. Values built while evaluating live in an arena of 16 M entries at the document level and 1 M entries
at each of three nesting depths of iterations; running out is a named error.

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
| Runtime error after some results | no stdout, exit 1 | earlier results on stdout, exit 5 |
| Malformed input, usage errors | exit 1 | exit 2 |
| A key with invalid UTF-8 matched by a filter key | compared as bytes | compared after replacement |
| A non-ASCII character typed in the filter on Windows | mangled by the C runtime's narrow argv to `?` (jq too, from Git Bash): write `\u00e9` | same |
| `tonumber` of `nan`, `Infinity`, `0x10` | an error | `nan` and `Infinity` are accepted |
| Pretty output over 3 GiB, strings built by the filter over 16 MB | error naming the limit | prints |
| `--strict` (design decision 1) | not implemented | n/a |

## Tests

- `python tests/run.py [jx.exe]`: every filter of `tests/filters.txt` (Stage 1), `filters2.txt` (Stage 2), `filters_pretty.txt` and `filters_raw.txt` over every document of `tests/docs.txt` and `tests/bad.txt` and the generated
  ones, through `jq` 1.8.2 and jx, byte for byte on standard output; where jq fails jx must fail with a message. Also the compile-time rejections, the syntax errors, the options and `--validate`.
- `python tests/fuzz.py`: random filters from the supported grammar over random documents against jq, from fixed seeds (`--seeds`, `--count`, `--only` to reproduce a case).
- `python -I tests/jqtest.py`: jq's own `tests/jq.test` (fetched as data to `D:\tmp\w\jqcompat\jq.test`, never executed) through jx, by class and by tag; `--inset` lists the cases of the Stage 2 decision set that do not pass yet.
- `python tests/numcheck.py`, `python tests/numarith.py`: the number layer against Python and jq.

Results of the last run are in the section "Results" below and in [docs/progress.md](docs/progress.md).

## Stage 3

`--explain` (print the automaton and slot program for a filter), with tests/explain.txt regression pairs.

## Results

@@RESULTS@@
