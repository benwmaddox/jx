# A stream of documents (design)

jq reads a sequence of JSON values from its input, runs the filter once per value and prints the results in order. jx used to
accept exactly one value. Every rule below was probed on jq 1.8.2 (the real `jq.exe`), not guessed.

## 1. Where one value ends and the next begins

- Values need no separator when the end is unambiguous: `1 2`, `"a""b"`, `[1][2]`, `{"a":1}{"a":2}`, `1"a"`, `1[2]`, `[1]2`,
  `true"a"` are all streams. A comma between values is an error (`1,2`).
- A number or literal is a token that runs up to a delimiter (whitespace, `[ ] { } , : "`). `truefalse`, `nul`, `-`, `1true`,
  `true1`, `1-2`, `1.5.5`, `"a"-` are invalid tokens. (jq also takes `01` as 1, `nan`/`NaN` as null; jx stays strict: a
  documented difference that exists for single documents already.)
- jq prints the results of every good value before a parse error; the error is `jq: parse error: ...` on stderr and the exit
  code is 5 (not 2). `printf '1 2 {' | jq .` prints 1, 2, exit 5. The values after the bad byte are never read.
- The results of a value that is itself broken (`{"a":1} {"a":2`) are not printed: jq runs the filter on complete values only.
  jx streams results while the value is still being scanned, so it remembers where the output of the current value starts and
  cuts it back when the value turns out to be broken.
- A byte order mark is skipped at the start of the input only.

## 2. Per value processing

Per value jx resets what the one-value engine holds: the scanner stack, the slot generation (`dgen`, a counter that replaces
the constant 1 the document level slots and registers used), the arenas (`top = base`, the constants stay), the scratch and
persistent text, the pending error. Slots and registers are reset by the generation counter, not by clearing them: O(1).
The output of earlier values stays.

A runtime error raised for one value (`jq: error (at <stdin>:N): message`): jq prints the results made before the error,
writes the error to stderr, goes on with the NEXT value. The exit code is that of the LAST value: 5 if the filter raised an
error for it, else 0 (so `1\n2` with an error for 1 only exits 0). Probed.
The `N` is `input_line_number` when the error is raised: the number of lines (read in pieces of at most 4095 bytes, counted
when the piece ends in a line feed) jq had read when the value was complete; for a number or literal that is the line of the byte
after it. A value on the last line without a line feed does not count that line: `1 "a" 3` gives 0 for every value. With `-n`
the location is `<unknown>` until something was read. A non-string error is `jq: error (at <stdin>:N) (not a string): {...}`.

## 3. Early exit is no longer free

The scanner used to stop at the end of the enclosing container when all wanted slots were filled. Now it must find the end of
the value, so after the filter is done it keeps scanning with every node switched off (no slot, no scope, no arena use):
validation speed. jq validates the whole value too, so this is the exact jq behavior (a broken tail still fails the value).
`--first` (jx only) means "the input is one value: stop right after the filter has finished with it", the old fast path; it
does not look at what follows. Measured cost on the 529 MB single value, `.users[0].n`: see docs/progress.md (stage `stream`).
The driver cannot know the first value is followed only by whitespace without reading; it does not try.

## 4. Output

Output stays in the output area and is written when main returns (correct, not incremental): Mitochondria has `eprint(text)`
for stderr but no `print`/flush for stdout, so `tail -f | jx` shows nothing until the input ends. Runtime request: a
`print(text)` that writes to stdout at once (and `flush()`), with jx calling it when the area passes a threshold and after each
value when `--unbuffered` is given. Stderr messages are collected and written (`eprint`) when the value they belong to is known
to be complete (never for a value that turns out broken).

## 5. input, inputs, -n, -s, -e, --seq

- `input` is a value of the stream read on demand: the driver finds the next value's end (validating), and the value is
  materialized from its text exactly like `fromjson`. A filter that uses `input`/`inputs` runs through the general evaluator
  once per value pulled by the main loop. Past the end `input` raises the error `break` (jq 1.8.2 says exactly that, and
  `try input catch .` gives "break"). `-n` runs the filter once with null; `first(inputs)` reads only one value (no later
  parse error is seen), as in jq.
- `-s`: the array of all values (no value: `[]`); any parse error: no output, exit 5.
- `-e`: 4 when nothing was printed in the whole stream, else 1 when the last printed value (any value of the stream) is null
  or false, else 0; a runtime error in the last value: 5.
- `--seq`: output as before (RS before each result). Input in `--seq` mode is a different parser in jq (RS framed, truncated
  values ignored with a warning); jx reads `--seq` input like normal input.
- `--stream` stays rejected.
