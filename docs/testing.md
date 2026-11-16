# Testing jx

Back to the [README](../README.md). Results by stage are in [progress.md](progress.md) and [history.md](history.md).


- `python tests/run.py [jx.exe]`: every filter of `tests/filters.txt` (Stage 1), `filters2.txt` (Stage 2), `filters_pretty.txt` and `filters_raw.txt` over every document of `tests/docs.txt` and `tests/bad.txt` and the generated
  ones, through `jq` 1.8.2 and jx, byte for byte on standard output; where jq fails jx must fail with a message. Also the compile-time rejections, the syntax errors, the options and `--validate`.
- `python tests/fuzz.py --grammar base|s3|mixed`, `python tests/explain.py`: golden `--explain` outputs.
- `python tests/fuzz.py`: random filters from the supported grammar over random documents against jq, from fixed seeds (`--seeds`, `--count`, `--only` to reproduce a case).
- `python -I tests/jqtest.py`: jq's own `tests/jq.test` (fetched as data to `D:\tmp\w\jqcompat\jq.test`, never executed) through jx, by class and by tag; `--inset` lists the cases of the Stage 2 decision set that do not pass yet.
- `python tests/numcheck.py`, `python tests/numarith.py`: the number layer against Python and jq.

Results of the last runs are in the README's Performance section, [history.md](history.md), and [docs/progress.md](progress.md).
