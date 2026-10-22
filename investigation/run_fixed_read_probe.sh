#!/usr/bin/env bash
set -euo pipefail
umask 077

ROOT=/scratch/trazzaque/chipyard
SIM_ROOT="$ROOT/sims/firesim/sim/generated-src/f2"
OUT=/scratch/trazzaque/firesim-host-builds/fixed-read-probe
FIR_SHA=f31b0c5357ba61ef113c1626be4b8fba19108c6ca1a2e1fe49aafcb4ec34f247

case "${1:-}" in
  ddr2133)
    platform=DDRF2Config
    sim_sha=e29909b511b80c4051b5ea8656b0ce375617f7094d3c07905fda7010dc4cf4ba
    profile="$ROOT/investigation/runtime-configs/ddr3-FRFCFS-8G-4R-2133-OP.source.conf"
    profile_sha=592294830e684f51487d3ab12a4d0ede8a3ee60bb3403c46652b151687427f2f
    expected_args=28
    ;;
  hbm4_2400|hbm4_2000)
    platform=HBMF2Config
    sim_sha=f5d09f6da188b381d08fa4fa9636f52177c5d9fd4812c1b17c5d7af61567d30a
    expected_args=34
    ;;
  hbm8_2400|hbm8_2000)
    platform=HBMF2Backend8Config
    sim_sha=658feb8434e0c3242328590e898207ddc6a9aec6bcf9a6b4f1cc414f1a71536a
    expected_args=34
    ;;
  *)
    printf 'usage: %s {ddr2133|hbm4_2400|hbm8_2400|hbm4_2000|hbm8_2000}\n' "$0" >&2
    exit 2
    ;;
esac

if [[ "$1" == hbm* ]]; then
  if [[ "$1" == *_2400 ]]; then
    profile="$ROOT/investigation/runtime-configs/hbm2-FRFCFS-2400-OP-REFab.source.conf"
    profile_sha=9212d7c7d7417ec591a608136289eb0ef7c27311273a0a029d883db7518e11f9
  else
    profile="$ROOT/investigation/runtime-configs/hbm2-FRFCFS-2000-OP-REFab.source.conf"
    profile_sha=af92398e9db6acf877fc5373db406e78bc2c8841a33911480e8a40945a0c3ed3
  fi
fi

gen_dir="$SIM_ROOT/f2-fasedtests-FixedReadProbe-DefaultConfig-$platform"
sim="$gen_dir/VFixedReadProbe"
fir="$gen_dir/firesim.fasedtests.FixedReadProbe.DefaultConfig.fir"
run_dir="$OUT/$1"
test -z "$(pgrep -u "$USER" -x VFixedReadProbe || true)"
test ! -e "$run_dir"
test -x "$sim" && test ! -L "$sim"
test "$(sha256sum "$sim" | awk '{print $1}')" = "$sim_sha"
test "$(sha256sum "$fir" | awk '{print $1}')" = "$FIR_SHA"
test "$(sha256sum "$profile" | awk '{print $1}')" = "$profile_sha"
mapfile -t mm_args < <(awk 'NF && $1 !~ /^#/' "$profile" | sed 's/=\(.*\)$/_0=\1/')
test "${#mm_args[@]}" -eq "$expected_args"
for arg in "${mm_args[@]}"; do
  [[ "$arg" =~ ^\+mm_[A-Za-z0-9_]+_0=[0-9]+$ ]]
done

mkdir -p "$run_dir"
(
  cd "$run_dir"
  printf 'START_UTC=%s\n' "$(date -u +%FT%TZ)"
  set +e
  timeout --signal=INT --kill-after=10s 5m "$sim" "${mm_args[@]}" +max-cycles=5000000
  rc=$?
  printf 'COMMAND_EXIT_CODE="%d"\n' "$rc"
  printf 'END_UTC=%s\n' "$(date -u +%FT%TZ)"
  exit "$rc"
) >"$run_dir/console.log" 2>&1
rg -q '\*\*\* PASSED \*\*\* after [0-9]+ cycles' "$run_dir/console.log"
! rg -q '\*\*\* FAILED \*\*\*' "$run_dir/console.log"
test -s "$run_dir/memory_stats0.csv"
rg 'PASSED|COMMAND_EXIT_CODE' "$run_dir/console.log" | tail -3
