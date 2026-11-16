#!/bin/bash
# GH Archive star count: every WatchEvent's repo.name from 3 hours of GH Archive (2024-01-15, hours 12-14: 2.9 GB, 827,068 events).
# Times each tool's whole run (start, reading the file, scanning, printing) pinned to one core, best of RUNS, the file in the page cache.
# usage: bench/gharchive/run.sh   (Linux; needs curl, g++, bc; jq, jaq and gojq are timed when on PATH)
#   JX: the jx to time (default ./jx); JX_V3: an x86-64-v3 build (optional); CPU: the core (default 2); RUNS (default 5);
#   SLOW_RUNS: runs of jq, jaq and gojq (default 1); WORK: where data and the harness go (default ~/ghbench-work)
# ghbench.cpp runs simdjson and yyjson (libraries, not command-line tools) on the same task; its rows include loading the file.
set -u
HERE=$(cd "$(dirname "$0")" && pwd)
W=${WORK:-$HOME/ghbench-work}; mkdir -p "$W/data" "$W/lib" "$W/out"
CPU=${CPU:-2}; RUNS=${RUNS:-5}; SLOW_RUNS=${SLOW_RUNS:-1}
JX=${JX:-./jx}; JX_V3=${JX_V3:-}
cd "$W/data"
for h in 12 13 14; do f=2024-01-15-$h.json.gz; [ -f $f ] || curl -sfO https://data.gharchive.org/$f; done
[ -f gh.ndjson ] || zcat 2024-01-15-1[2-4].json.gz > gh.ndjson
[ -f gh.array.json ] || { printf '['; sed '$!s/$/,/' gh.ndjson; printf ']'; } > gh.array.json
cd "$W/lib"
for f in simdjson.h simdjson.cpp; do [ -f $f ] || curl -sfO https://raw.githubusercontent.com/simdjson/simdjson/v5.2.0/singleheader/$f; done
for f in yyjson.h yyjson.c; do [ -f $f ] || curl -sfO https://raw.githubusercontent.com/ibireme/yyjson/0.13.0/src/$f; done
[ -x "$W/ghbench" ] || g++ -O3 -march=native -I. -x c++ -std=c++20 "$HERE/ghbench.cpp" simdjson.cpp -x c yyjson.c -o "$W/ghbench"
cd "$W"; N=data/gh.ndjson; A=data/gh.array.json
cat $N $A > /dev/null
GB=$(stat -L -c %s $N | awk '{printf "%.3f", $1/1e9}')
S='.[] | select(.type == "WatchEvent") | .repo.name'
G='select(.type == "WatchEvent") | .repo.name'
# best wall time in ms of n runs, and the stars counted (lines printed, or the harness's own count)
t() { local n=$1; shift; local best=999999999; for r in $(seq $n); do s=$(date +%s%N); taskset -c $CPU "$@" > out/r.txt 2> out/err.txt; e=$(date +%s%N); ms=$(( (e-s)/1000000 )); [ $ms -lt $best ] && best=$ms; done
  if [ "$1" = ./ghbench ]; then echo "$best $(grep -o 'stars [0-9]*' out/r.txt | tail -1 | cut -d' ' -f2)"; else echo "$best $(wc -l < out/r.txt)"; fi; }
row() { local name=$1 input=$2 n=$3; shift 3; read ms stars < <(t $n "$@"); printf "| %s | %s | %.2f s | %.2f GB/s | %s |\n" "$name" "$input" "$(echo "$ms/1000" | bc -l)" "$(echo "$GB/($ms/1000)" | bc -l)" "$stars"; }
echo "| tool | input | time | GB/s | stars |"
echo "| --- | --- | --- | --- | --- |"
row "jx (checked, default)" array $RUNS "$JX" "$S" $A
row "jx --selective" array $RUNS "$JX" --selective "$S" $A
if [ -n "$JX_V3" ]; then
  row "jx x86-64-v3 (checked)" array $RUNS "$JX_V3" "$S" $A
  row "jx x86-64-v3 --selective" array $RUNS "$JX_V3" --selective "$S" $A
fi
row "simdjson On-Demand, two fields (ghbench od-sel)" ndjson $RUNS ./ghbench od-sel $N 1
row "simdjson On-Demand, one array (ghbench od-sel-arr)" array $RUNS ./ghbench od-sel-arr $A 1
row "simdjson DOM (ghbench dom)" ndjson $RUNS ./ghbench dom $N 1
row "simdjson On-Demand, every value (ghbench od-full)" ndjson $RUNS ./ghbench od-full $N 1
row "yyjson DOM (ghbench yy)" ndjson $RUNS ./ghbench yy $N 1
command -v jaq >/dev/null && row "jaq $(jaq --version | cut -d' ' -f2)" ndjson $SLOW_RUNS jaq "$G" $N
command -v gojq >/dev/null && row "gojq $(gojq --version | cut -d' ' -f2)" ndjson $SLOW_RUNS gojq "$G" $N
command -v jq >/dev/null && row "$(jq --version)" ndjson $SLOW_RUNS jq "$G" $N
