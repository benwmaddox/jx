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

**Benchmark: GH Archive stars (jx v0.1.0, 2026-11-15).** The query is every `WatchEvent`'s `repo.name`, on 3 hours of GH Archive
(2024-01-15, hours 12-14: 2.9 GB, 827,068 events). One core of a Core Ultra 9 185H (WSL 2, Linux), files in the page cache, best of 5 runs
(jq, jaq and gojq: best of 3). Every reader finds the same 28,483 stars. Reproduce with `bench/gharchive/run.sh`.

Two numbers per reader, both file size divided by time:

- **File in memory:** the parse alone. For simdjson and yyjson (libraries, run by `bench/gharchive/ghbench.cpp`, g++ 13 `-O3 -march=native`):
  the best of 5 parses in one process after the file has been loaded. For jx: the whole run minus its 3 ms start-up (jx maps its input file,
  so there is no load step to take out; the page faults of the mapping stay in). jq, jaq and gojq read while they parse: no such figure.
- **Whole run:** what a user waits for: process start, getting the file into memory, the parse, printing the results.

*Selective* reads only what the query needs and skips the rest without checking it (jx `--selective`, simdjson On-Demand). *Checked* reads and
validates every value, as jq does (jx by default, DOM parsers, jq-like tools).

**Selective**

| Reader | Input | Best throughput, file in memory | Best throughput, whole run |
| --- | --- | --- | --- |
| simdjson 5.2.0 On-Demand | NDJSON | **5.61 GB/s** | 1.95 GB/s |
| jx v0.1.0 `--selective`, x86-64-v3 build | array | 4.72 GB/s | **4.70 GB/s** |
| jx v0.1.0 `--selective` | array | 3.50 GB/s | 3.49 GB/s |
| simdjson 5.2.0 On-Demand | array | 3.22 GB/s | 1.58 GB/s |

**Checked**

| Reader | Input | Best throughput, file in memory | Best throughput, whole run |
| --- | --- | --- | --- |
| simdjson 5.2.0 DOM | NDJSON | **3.39 GB/s** | 1.56 GB/s |
| simdjson 5.2.0 On-Demand, every value read | NDJSON | 2.71 GB/s | 1.42 GB/s |
| yyjson 0.13.0 DOM | NDJSON | 2.20 GB/s | 1.27 GB/s |
| jx v0.1.0, x86-64-v3 build | array | 1.99 GB/s | **1.99 GB/s** |
| jx v0.1.0 | array | 1.85 GB/s | 1.85 GB/s |
| jaq 3.1.2 | NDJSON | | 0.33 GB/s |
| jq 1.8.1 | NDJSON | | 0.14 GB/s |
| gojq 0.12.20 | NDJSON | | 0.11 GB/s |

jx reads one document, so it gets the events as one array (`[ev, ev, ...]`); the others get one event per line (NDJSON), their best case.
simdjson On-Demand is shown on both, as the one reader measured on jx's input. jx before v0.1.0 (one byte at a time, input copied) ran the
checked query at 0.62 GB/s whole run.

**Why jx wins some rows and loses others**

- **Whole run, every row: jx is fastest because of how it gets the file, not how it parses.** jx maps the input file into memory (one system
  call; the pages come straight from the system's file cache). The libraries, as `ghbench.cpp` uses them, load the file with their own loaders,
  which copy all 2.9 GB into newly allocated memory first; that copy takes about 1 s, longer than the parse. A program built on simdjson
  could map the file too and would then be close to its in-memory figure. So the whole-run lead says that jx's input path is efficient,
  not that its parser is faster.
- **Selective, file in memory, NDJSON: simdjson is faster (5.61 against 4.72 GB/s).** simdjson classifies every byte of a block in one vector
  pass (quotes, backslashes, brackets, separators, all at once, with table lookups) and then jumps from one structural character to the next.
  jx uses vectors for string contents and for skipping objects and arrays it does not read, but it still steps through the parts it reads one
  token at a time: each key and string is its own 64-byte check plus a key lookup, and the commas, colons, numbers and white space between them
  are handled one byte at a time.
- **Selective, file in memory, same input (one big array): jx is faster (4.72 against 3.22 GB/s).** simdjson's first pass indexes a whole
  document before the second pass reads it. Fed one line at a time it works in cache-sized batches; fed one 2.9 GB document, the index of every
  structural character goes out to main memory and comes back. jx makes a single forward pass, so one big document and many small ones cost it
  the same.
- **Checked, file in memory: simdjson and yyjson are faster (3.39 and 2.20 against 1.99 GB/s).** Checking every value is where jx is still
  mostly byte-at-a-time: numbers digit by digit, `true`/`false`/`null`, separators, and the objects and arrays it does not need are parsed token
  by token so that an invalid document fails as it does in jq. simdjson validates structure and UTF-8 with vector instructions. The next steps
  for jx are vector loops for numbers and separators and a vector-based check of the parts it skips.
- **Against jq, jaq and gojq: jx is 5.6 to 17 times faster checked (6 to 18 with the x86-64-v3 build).** Those tools build a full value (objects, arrays, strings) for every event
  and then run the filter on it. jx compiles the filter into a plan of the paths it needs before reading, keeps only those values, and never
  builds the rest.
- **The x86-64-v3 build** (`CPU=x86-64-v3 ./build.sh`) adds AVX2 and the bit-counting instructions: 35% faster with `--selective`, which counts
  bits for every 64 bytes it skips, and 8% faster checked. The default build runs on any x86-64 CPU.

## Documentation

- [Using jx](docs/usage.md): streams, pipes and large input, options, input files
- [Differences from jq](docs/differences.md)
- [How jx works](docs/internals.md), and the full [design](docs/design.md)
- [Testing](docs/testing.md), [progress against jq's test file](docs/progress.md), [feature matrix](docs/jq-feature-matrix.md)
- [Stage notes and older measurements](docs/history.md)
- Benchmark script: [bench/gharchive](bench/gharchive)

## License

Apache License 2.0, copyright 2026 Maddox Labs LLC: see [LICENSE](LICENSE) and [NOTICE](NOTICE).
