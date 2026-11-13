#!/bin/bash
# Builds jx.exe with the Mitochondria compiler (MITO: path to mito.exe, default the one built from Mitochondria's main:
#   cd <Mitochondria checkout> && CARGO_TARGET_DIR=<dir>/target/jx-mito2 cargo build --release ; the build needs main with PR #44, `byte_at` as an inline load).
# usage: ./build.sh [output.exe]      INLINE=1 adds clang's bigger inlining budget (README: Measurements); the default is clang -O3.
if [ -z "$MITO" ]; then
  MITO=D:/code/Mitochondria/target/jxs3-mito/release/mito.exe
  [ -f "$MITO" ] || MITO=D:/code/Mitochondria/target/jx-mito2/release/mito.exe
  [ -f "$MITO" ] || MITO=D:/code/Mitochondria/target/jx-mito/release/mito.exe
fi
OUT=${1:-jx.exe}
HERE=$(cd "$(dirname "$0")" && pwd)
if [ -n "$INLINE" ]; then
  "$MITO" build "$HERE/src/jx.mito" -o "$OUT" --cflag -O3 --cflag -mllvm --cflag -inline-threshold=10000
else
  "$MITO" build "$HERE/src/jx.mito" -o "$OUT" --cflag -O3
fi
