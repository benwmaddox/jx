#!/bin/bash
# GH Archive star count: every WatchEvent's repo.name from 3 hours of GH Archive (2024-01-15, hours 12-14: 2.9 GB, 827,068 events).
# Prints one table: per mode and reader, the best throughput with the file in memory and for the whole run (start, reading, scanning, printing).
# One core (taskset), best of RUNS, the files in the page cache.
#   in memory: simdjson and yyjson (libraries, run by ghbench.cpp): the best of RUNS parses in one process after the file is loaded.
#              jx: the whole run minus the same binary's start-up (a filter that stops at once); jx maps its input file, so there is no load to remove.
#              jq, jaq and gojq read as they parse: no figure.
# usage: bench/gharchive/run.sh   (Linux; needs curl, g++; jq, jaq and gojq are timed when on PATH)
#   JX: the jx to time (default ./jx); JX_V3: an x86-64-v3 build (optional); CPU: the core (default 2); RUNS (default 5);
#   SLOW_RUNS: runs of jq, jaq and gojq (default 1); WORK: where data and the harness go (default ~/ghbench-work)
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
size() { stat -L -c %s "$1"; }
S='.[] | select(.type == "WatchEvent") | .repo.name'
G='select(.type == "WatchEvent") | .repo.name'
# best wall time in ms of n runs of a command (its stdout in out/r.txt)
best() { local n=$1; shift; local b=999999999; for r in $(seq $n); do local s=$(date +%s%N); taskset -c $CPU "$@" > out/r.txt 2> out/err.txt; local e=$(date +%s%N); local ms=$(( (e-s)/1000000 )); [ $ms -lt $b ] && b=$ms; done; echo $b; }
gbs() { echo "$1 $2" | awk '{ if ($2 <= 0) print "-"; else printf "%.2f GB/s", $1 / 1e9 / ($2 / 1000) }'; }
stars() { wc -l < out/r.txt; }
row() { printf "| %s | %s | %s | %s | %s | %s |\n" "$@"; }
echo "| Mode | Reader | Input | Best throughput, file in memory | Best throughput, whole run | Stars |"
echo "| --- | --- | --- | --- | --- | --- |"
# jx: whole runs, and start-up measured with a filter that ends at once
jxrow() { local mode=$1 name=$2 bin=$3; shift 3
  local up=$(best $RUNS "$bin" "$@" '.[0].id' $A); local w=$(best $RUNS "$bin" "$@" "$S" $A); local st=$(stars)
  row "$mode" "$name" array "$(gbs $(size $A) $((w - up)))" "$(gbs $(size $A) $w)" "$st"; }
# a library through ghbench: whole runs (one parse each), then RUNS parses in one process (its best)
librow() { local mode=$1 name=$2 m=$3 f=$4 input=$5
  local w=$(best $RUNS ./ghbench $m $f 1); local st=$(grep -o 'stars [0-9]*' out/r.txt | tail -1 | cut -d' ' -f2)
  taskset -c $CPU ./ghbench $m $f $RUNS > out/r.txt 2> out/err.txt
  local mem=$(grep -o 'run [0-9]*: [0-9.]* s' out/r.txt | awk '{print $3 * 1000}' | sort -n | head -1)
  row "$mode" "$name" $input "$(gbs $(size $f) $mem)" "$(gbs $(size $f) $w)" "$st"; }
clirow() { local name=$1 bin=$2; local w=$(best $SLOW_RUNS $bin "$G" $N); row Checked "$name" NDJSON "-" "$(gbs $(size $N) $w)" "$(stars)"; }
[ -n "$JX_V3" ] && jxrow Selective "jx (x86-64-v3 build) --selective" "$JX_V3" --selective
jxrow Selective "jx --selective" "$JX" --selective
librow Selective "simdjson On-Demand (reads type, repo.name)" od-sel $N NDJSON
librow Selective "simdjson On-Demand (reads type, repo.name)" od-sel-arr $A array
[ -n "$JX_V3" ] && jxrow Checked "jx (x86-64-v3 build)" "$JX_V3"
jxrow Checked "jx" "$JX"
librow Checked "simdjson DOM" dom $N NDJSON
librow Checked "simdjson On-Demand, full walk" od-full $N NDJSON
librow Checked "yyjson DOM" yy $N NDJSON
command -v jaq >/dev/null && clirow "jaq $(jaq --version | cut -d' ' -f2)" jaq
command -v jq >/dev/null && clirow "jq $(jq --version | sed 's/jq-//')" jq
command -v gojq >/dev/null && clirow "gojq $(gojq --version | cut -d' ' -f2)" gojq
