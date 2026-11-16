# jx

A jq-compatible JSON filter that reads its input once, front to back, and keeps only what the filter needs. Before any input is read, the
filter is compiled into a plan of the paths it uses; the scanner then checks the input as it goes and builds values only for those paths,
using vector instructions (64 bytes at a time) for strings and for parts it skips. It reads streams of JSON values (NDJSON) as jq does,
maps input files instead of copying them, and reads pipes in fixed memory. Written in [Mitochondria](https://github.com/benwmaddox/mitochondria).

## Quick start

Download a build from [Releases](https://github.com/benwmaddox/jx/releases) (`jx` runs on any x86-64 CPU; `jx-x86-64-v3` needs AVX2 and
is faster), or build it with the Mitochondria compiler:

```
./build.sh jx.exe                       # MITO=path/to/mito.exe; CPU=x86-64-v3 for an AVX2 build
echo '{"users":[{"n":"ann","age":91},{"n":"bo","age":7}]}' | ./jx.exe -c '.users[] | select(.age >= 85) | .n'
"ann"
zcat events.json.gz | jx -c 'select(.type == "WatchEvent") | .repo.name'    # NDJSON from a pipe, in fixed memory
jx --selective -c '.[] | .id' big.json   # skip what the filter does not read, without checking it
```

Checked mode (the default) validates every value as jq does; `--selective` skips objects and arrays the filter does not read without checking
them; `--first` reads only the first value and stops as soon as the filter is done.

## Performance

Every `WatchEvent`'s `repo.name` from 3 hours of GH Archive (2024-01-15, hours 12-14: 2.9 GB of NDJSON, 827,068 events), the same file for
every reader. One core of a Core Ultra 9 185H (WSL 2, Linux), file in the page cache, best of 5 runs (jq, jaq and gojq: best of 3), jx v0.2.0.
Every reader finds the same 28,483 stars. Reproduce with [bench/gharchive/run.sh](bench/gharchive/run.sh).

- **File in memory:** the parse alone. simdjson and yyjson are libraries, run by [ghbench.cpp](bench/gharchive/ghbench.cpp) (g++ 13
  `-O3 -march=native`): the best of 5 parses in one process after the file has been loaded. jx maps its input file, so it has no load step: its
  figure is the whole run minus its 3 ms start-up (the page faults of the mapping stay in). jq, jaq and gojq read while they parse: no figure.
- **Whole run:** what a user waits for: process start, getting the file into memory, the parse, printing the results. "(pipe)" rows read the file
  through `cat |`, in pieces, in fixed memory (42 MB).

*Selective* reads only what the query needs and skips the rest without checking it (jx `--selective`, simdjson On-Demand). *Checked* reads
and validates every value, as jq does (jx by default, DOM parsers, jq-like tools).

**Selective**

| Reader | Input | Best throughput, file in memory | Best throughput, whole run |
| --- | --- | --- | --- |
| simdjson 5.2.0 On-Demand | file | **5.93 GB/s** | 2.05 GB/s |
| jx v0.2.0 `--selective`, x86-64-v3 build | file | 5.01 GB/s | **4.99 GB/s** |
| jx v0.2.0 `--selective` | file | 3.59 GB/s | 3.58 GB/s |
| jx v0.2.0 `--selective`, x86-64-v3 build | pipe | | 1.56 GB/s |

**Checked**

| Reader | Input | Best throughput, file in memory | Best throughput, whole run |
| --- | --- | --- | --- |
| simdjson 5.2.0 DOM | file | **3.43 GB/s** | 1.66 GB/s |
| simdjson 5.2.0 On-Demand, every value read | file | 2.83 GB/s | 1.51 GB/s |
| yyjson 0.13.0 DOM | file | 2.27 GB/s | 1.35 GB/s |
| jx v0.2.0, x86-64-v3 build | file | 2.03 GB/s | **2.03 GB/s** |
| jx v0.2.0 | file | 1.84 GB/s | 1.83 GB/s |
| jx v0.2.0, x86-64-v3 build | pipe | | 1.09 GB/s |
| jaq 3.1.2 | file | | 0.36 GB/s |
| jq 1.8.1 | file | | 0.15 GB/s |
| gojq 0.12.20 | file | | 0.12 GB/s |

jx v0.1.0 (one byte at a time, input copied) ran the checked query at 0.62 GB/s whole run.

**Why jx wins some rows and loses others**

- **Whole run from a file: jx is fastest in every row because of how it gets the file, not how it parses.** jx maps the input file into memory
  (one system call; the pages come straight from the system's file cache). The libraries, as `ghbench.cpp` uses them, load the file with their
  own loaders, which copy all 2.9 GB into newly allocated memory first; that copy takes about 1 s, longer than the parse. A program built on
  simdjson could map the file too and would then be close to its in-memory figure.
- **Selective, file in memory: simdjson is faster (5.93 against 5.01 GB/s).** simdjson classifies every byte of a block in one vector pass
  (quotes, backslashes, brackets, separators, all at once, with table lookups) and then jumps from one structural character to the next. jx uses
  vectors for string contents and for skipping objects and arrays it does not read, but it steps through the parts it reads one token at a time:
  each key and string is its own 64-byte check plus a key lookup, and the commas, colons, numbers and white space between them are handled one
  byte at a time.
- **Checked, file in memory: simdjson and yyjson are faster (3.43 and 2.27 against 2.03 GB/s).** Checking every value is where jx is still
  mostly byte-at-a-time: numbers digit by digit, `true`/`false`/`null`, separators, and the objects and arrays it does not need are parsed
  token by token so that an invalid document fails as it does in jq. simdjson validates structure and UTF-8 with vector instructions. The next
  steps for jx are vector loops for numbers and separators and a vector-based check of the parts it skips.
- **From a pipe** jx is bounded by the pipe and the copy into each piece, not by the scan, but it reads any amount of input in 42 MB; the file
  readers above hold the whole file.
- **One big document or many small ones: the same for jx.** It makes a single forward pass, so the events as one 2.9 GB array run at the same
  speed as the NDJSON file. simdjson's first pass indexes a whole document before its second pass reads it: on one 2.9 GB array its On-Demand
  reader drops to 3.22 GB/s in memory (v0.1.0 measurements), because the index no longer fits in cache.
- **Against jq, jaq and gojq: jx is 5 to 15 times faster checked (5.6 to 17 with the x86-64-v3 build).** Those tools build a full value
  (objects, arrays, strings) for every event and then run the filter on it. jx compiles the filter into a plan of the paths it needs before
  reading, keeps only those values, and never builds the rest.
- **The x86-64-v3 build** (`CPU=x86-64-v3 ./build.sh`) adds AVX2 and the bit-counting instructions: 40% faster with `--selective`, which counts
  bits for every 64 bytes it skips, and 10% faster checked. The default build runs on any x86-64 CPU.

## Documentation

- [Using jx](docs/usage.md): streams, pipes and large input, options, input files
- [Differences from jq](docs/differences.md)
- [How jx works](docs/internals.md), and the full [design](docs/design.md)
- [Testing](docs/testing.md), [progress against jq's test file](docs/progress.md), [feature matrix](docs/jq-feature-matrix.md)
- [Stage notes and older measurements](docs/history.md)
- Benchmark script: [bench/gharchive](bench/gharchive)

## License

Apache License 2.0, copyright 2026 Maddox Labs LLC: see [LICENSE](LICENSE) and [NOTICE](NOTICE).
