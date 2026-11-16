#!/bin/bash
# Builds jx.exe with the Mitochondria compiler (MITO: path to mito.exe, default the one built from Mitochondria's main:
#   cd <Mitochondria checkout> && CARGO_TARGET_DIR=<dir>/target/jx-mito2 cargo build --release ; the build needs main with PR #44, `byte_at` as an inline load).
# MITO must be Mitochondria v0.1.0 or later (byte vectors and mapped input, #55; stdin_text, read_file, from env, eprint, #47).
# usage: ./build.sh [output.exe]      INLINE=1 adds clang's bigger inlining budget (README: Measurements); the default is clang -O3.
# CPU=x86-64-v3 (or x86-64-v2, native) builds for that CPU level (Mitochondria's `--cpu`; needs its byte vectors): about 30% faster with --selective,
# but the binary needs AVX2. The default runs on any x86-64.
if [ -z "$MITO" ]; then
  MITO=D:/code/Mitochondria/target/jxrx-mito/release/mito.exe
  [ -f "$MITO" ] || MITO=D:/code/Mitochondria/target/jxs3-mito/release/mito.exe
  [ -f "$MITO" ] || MITO=D:/code/Mitochondria/target/jx-mito2/release/mito.exe
  [ -f "$MITO" ] || MITO=D:/code/Mitochondria/target/jx-mito/release/mito.exe
fi
OUT=${1:-jx.exe}
CPUFLAG=()
[ -n "$CPU" ] && CPUFLAG=(--cpu "$CPU")
HERE=$(cd "$(dirname "$0")" && pwd)
if [ -n "$INLINE" ]; then
  "$MITO" build "$HERE/src/jx.mito" -o "$OUT" "${CPUFLAG[@]}" --cflag -O3 --cflag -mllvm --cflag -inline-threshold=10000
else
  "$MITO" build "$HERE/src/jx.mito" -o "$OUT" "${CPUFLAG[@]}" --cflag -O3
fi
