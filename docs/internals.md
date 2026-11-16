# How jx works

Back to the [README](../README.md). The full design is [design.md](design.md).

## Files in `src/`

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
- **Early exit** (design decisions 2 and 3): with `--first`, a filter with no `[]` stops after the container that held its last filled value ends, and the
  unread tail is not validated; `--first --validate` reads to the end and fails when anything but white space follows. In a stream (the default) each
  value is read whole, as jq does, so a broken tail fails that value; with `--selective` the rest of the value is skipped once the filter has what it needs.
- **Checked by default, `--selective` on request.** By default every value the scanner passes is checked as strict JSON (numbers, escapes, literals,
  brackets), also inside objects and arrays the filter never reads, so an invalid document fails as it does in jq. `--selective` skips an object or array
  the filter does not read by counting brackets outside strings, 64 bytes at a time, without checking what is inside (simdjson's On-Demand does the same):
  about 2x faster on GH Archive events, and invalid JSON inside a skipped part goes unnoticed. `--selective` with `--validate` is a usage error.
- **Byte vectors.** Strings are scanned 64 bytes at a time up to the next quote, backslash or control byte (Mitochondria's `u8x64`, `mask`,
  `trailing_zeros`), and `--selective` finds the end of a skipped container the same way (`prefix_xor` marks the bytes inside strings).
- **Missing values** are null; a missing or null value that the filter iterates is jq's error, raised when the iteration is played back.
- Empty or blank input prints nothing and exits 0, as jq does.
- **Strings**: bytes that are not valid UTF-8 are replaced as jq's decoder does when the string is printed, compared, measured or built on (one U+FFFD per invalid lead byte, one for a truncated
  or overlong sequence with its valid continuation bytes, a surrogate encoded in UTF-8 as one); a string without a byte of 128 or more needs no check, and strings that are only skipped are never checked.
