# jx

A jq-compatible filter engine that is a scanner and extractor, not a parser: the filter is compiled into a program that tells a
scanner which parts of the input it needs, and the input is read in one forward pass, copying only the extracted values. Written in
the Mitochondria language (https://github.com/benwmaddox/mitochondria).

Status: design stage. No implementation here yet.

- [docs/design.md](docs/design.md): goals, demand analysis, automaton and slot-program formats, jq feature table, staged plan, open decisions.
- Starting point: `examples/jx` in benwmaddox/mitochondria, a small jq that treats a value as a position in the input text.
