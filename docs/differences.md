# Differences from jq

Back to the [README](../README.md).

Each is expected (listed in `tests/xdiff.txt`), never a test failure.

| Case | jx | jq |
| --- | --- | --- |
| Duplicate keys inside a copied object, `length` of an object with duplicate keys (decision 1) | copied as written, counted twice | keeps the last, one key |
| Early exit with a damaged tail, or an outer repeated key after the exit point (decisions 2, 3) | answers | rejects the document / uses the last key |
| `NaN`, `Infinity`, `01`, `1.`, `.5`, `+1` | rejected (strict JSON) | accepted |
| `.[]` over an object with duplicate keys | every value | only the last one per key (needs buffering) |
| `--first`: a runtime error or invalid input after some results | no stdout, exit 5 | earlier results on stdout, exit 5 (the stream mode, the default, does as jq) |
| Error messages | `jx: ...` with a byte position | `jq: error (at <stdin>:N): ...` with a line |
| `input`, `inputs` | not supported yet | read the next value |
| A caught `break` (`try (break $x) catch .`) in the second and later values | `{"__jq": N}` with the same N for every value | N counts label runs across the whole input |
| A key with invalid UTF-8 matched by a filter key | compared as bytes | compared after replacement |
| A non-ASCII character typed in the filter on Windows | mangled by the C runtime's narrow argv to `?` (jq too, from Git Bash): write `\u00e9` | same |
| `tonumber` of `nan`, `Infinity`, `0x10` | an error | `nan` and `Infinity` are accepted |
| Output over 4 GiB, strings built by the filter over 16 MB, an arena that is full | error naming the limit (exit 1) | prints |
| `--strict` (design decision 1) | not implemented | n/a |
| `--selective`: invalid JSON inside an object or array the filter does not read | answers | rejects the document |
