# Using jx

How jx reads its input, its options, and what it needs from the runtime. Back to the [README](../README.md).

```

jx reads a stream of JSON values, as jq does (standard input, or one input file): NDJSON (one value per line), or values separated by white
space or by nothing where the end is clear (`1 "a" [1][2]{"a":3}`). The filter runs once per value and the results come out in order, written as
each value finishes. The filter is the first argument; flags are `-c` (compact; the default is jq's indented output), `-r` (a string result is written
raw), `--selective`, `--first` and `--validate` (below). An error of the filter in one value goes to standard error after that value's earlier results,
and the next value is read; the exit code is the last value's (5 if the filter failed on it), as in jq. A parse error stops: the results of the values
before it stand, the broken value's are dropped, exit 5. Other errors exit with 1 (jq uses 2, 3 and 5).

**Streams, pipes and large input.** A file (an argument, or `< file`) is mapped, not copied (Linux), up to 4 GiB. Standard input that is not such a
file (a pipe, Windows, more than 4 GiB) is read in pieces of 16 MiB (Mitochondria's `stdin_next`), so any amount of input runs in fixed memory:
2.9 GB of GH Archive through `cat |` takes 42 MB. A value may span pieces (a pretty-printed document is fine) up to 256 MiB.
`--first` reads only the first value and stops as soon as the filter is done with it, without reading the rest (the old single-document mode:
`.users[0].n` of a 529 MB document reads a few bytes); `--first --validate` also checks that only white space follows. `-s` collects every value
into one array (one value of any size; several values up to 16 MiB in all for now).

**Options.** jx parses its own arguments (the program takes the runtime's raw `args`), so an option is understood or refused wherever it is written, before or
after the filter, long or short, combined (`-cr`): `-c`, `-r`, `-j`, `-n`, `-e`, `-s`/`--slurp`, `-a`/`--ascii-output`, `--seq`, `-M`, `--tab`, `--indent n`, `--arg`,
`--argjson`, `--args`, `--jsonargs`, `--slurpfile`, `--rawfile`, `-f`/`--from-file`, `-R`/`--raw-input`, `-h`/`--help`, `-V`/`--version`, `--validate`, `--selective`, `--explain`
and `--dump-program` are built; every other jq option is a hard error before anything is read, `jx: option '-S' is not supported yet` (`-S -C -L -b` and `--stream
--stream-errors --sort-keys --color-output --raw-output0 --library-path --binary --build-configuration --strict`), `jx: unknown option '--bogus'` for anything else.
Standard input is read only when the filter needs it (`stdin_text`, a Mitochondria runtime feature): `-n`, `--explain`, `--dump-program`, `--help`, `--version` and a
run with an input file never wait for it. `jx --version` prints `jx 0.2` (jq prints `jq-1.8.2`); `--help` prints a short usage text of jx's own.
`-s` collects every value into one array (no input at all gives `[]`; several values up to 16 MiB in all for now, one value of any size). `-a` writes every character above 127 as a `u`-escape (and with `-r` a string is still written quoted, as jq does); `--seq` writes
a record separator (U+001E) before each result. `-S` is refused because document values are copied as spans and never parsed, so keys cannot be sorted
without parsing every object; `-C` because the writer copies spans; `-L` (modules) by owner scope.

**Input files.** `jx FILTER FILE` reads the file as the document (`-` is standard input). One file is accepted; a second one is
`jx: not supported yet: more than one input file` (exit 2). A file may hold any number of values (a stream). A file that
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
