#!/usr/bin/env bash
set -euo pipefail
umask 077

ROOT=/scratch/trazzaque/chipyard
SIM_ROOT="$ROOT/sims/firesim/sim/generated-src/f2"
PREFIX=f2-fasedtests-AXI4Fuzzer-FuzzMask3FFF_NT10e3_DefaultConfig
CONFIG="$ROOT/sims/firesim/sim/custom-runtime-configs/hbm2-FRFCFS-2400-OP-REFab.conf"
OUT=/scratch/trazzaque/firesim-host-builds/hbm-backend-depth-ab-20261021

mapfile -t mm_args < <(sed 's/=\(.*\)$/_0=\1/' "$CONFIG")
test "${#mm_args[@]}" -eq 34
for arg in "${mm_args[@]}"; do
  [[ "$arg" =~ ^\+mm_[A-Za-z0-9_]+_0=[0-9]+$ ]]
done

for variant in default4 backend8; do
  case "$variant" in
    default4) platform=HBMF2Config ;;
    backend8) platform=HBMF2Backend8Config ;;
  esac
  sim="$SIM_ROOT/$PREFIX-$platform/VAXI4Fuzzer"
  run_dir="$OUT/$variant"
  test -x "$sim" && test ! -L "$sim"
  test ! -e "$run_dir"
  mkdir -p "$run_dir"
  sha256sum "$sim" >"$run_dir/simulator.sha256"
  (
    cd "$run_dir"
    printf 'START_UTC=%s\n' "$(date -u +%FT%TZ)"
    set +e
    timeout --signal=INT --kill-after=10s 5m "$sim" \
      "${mm_args[@]}" +max-cycles=1000000000
    rc=$?
    printf 'COMMAND_EXIT_CODE="%d"\n' "$rc"
    printf 'END_UTC=%s\n' "$(date -u +%FT%TZ)"
    exit "$rc"
  ) >"$run_dir/console.log" 2>&1
  rg 'PASSED|FAILED|COMMAND_EXIT_CODE' "$run_dir/console.log" | tail -5
done
