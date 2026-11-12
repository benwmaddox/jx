#!/bin/bash
# Builds jx.exe with the Mitochondria compiler (MITO: path to mito.exe, default the one built from Mitochondria's main).
# usage: ./build.sh [output.exe]      the default build flags are clang -O3; this adds a bigger inlining budget (README: Measurements).
MITO=${MITO:-D:/code/Mitochondria/target/jx-mito/release/mito.exe}
OUT=${1:-jx.exe}
HERE=$(cd "$(dirname "$0")" && pwd)
"$MITO" build "$HERE/src/jx.mito" -o "$OUT" --cflag -O3 --cflag -mllvm --cflag -inline-threshold=10000
