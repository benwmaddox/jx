Scratch measurements behind docs/bytecode-design.md (2026-11-12). Nothing here is part of jx.

- `elem_timing.py EXE DOC RUNS nul|file FILTER...`: alternating runs, median ms per filter (whole process).
- `startup_timing.py DOC RUNS "exe|arg|arg" ...`: median ms of several commands on one input, alternating.
- `gen_body.py N`: synthesizes C of about N lines (three hot bodies, `body1..3`, plus filler functions) for the TinyCC tests.
- `tcc_compile.c`: in-process libtcc compile of that C with malloc counting (link with `-Wl,--wrap=malloc,--wrap=calloc,--wrap=realloc,--wrap=free`).
- `body_speed.c`: ns per element of the same bodies as clang code, TinyCC code and a bytecode interpreter (switch and computed goto).
Documents: the 190,000-row 15.5 MB file from `bench/bench.py`'s generator. Builds went under D:\tmp\w\jxbc-build; TinyCC 0.9.27 and clang 18.1.3 ran in WSL.
