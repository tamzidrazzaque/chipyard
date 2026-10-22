#!/usr/bin/env bash
set -euo pipefail
umask 077

ROOT=/scratch/trazzaque/chipyard
SIM_ROOT="$ROOT/sims/firesim/sim/generated-src/f2"
OUT=/scratch/trazzaque/firesim-host-builds/fixed-read-probe
PROFILE="$ROOT/investigation/runtime-configs/hbm2-FRFCFS-2000-OP-REFab.source.conf"
PROFILE_SHA=af92398e9db6acf877fc5373db406e78bc2c8841a33911480e8a40945a0c3ed3
FIR_SHA=8e8a36a8ca3242a3ac5ccbdb083b178307f66043b29ecdf09327a818839bd087

case "${1:-}" in
  default8)
    platform=HBMF2Config
    sim_sha=607e81443d1269616709de02dba1cc9ba150e2f17fa101d503f521a05f647647
    ;;
  explicit4)
    platform=HBMF2Backend4Config
    sim_sha=4b61df1d44020f5046343f957d47d7cef61dc3a0a76f40a8f6275959e4ef1ae9
    ;;
  explicit8)
    platform=HBMF2Backend8Config
    sim_sha=00e1068d78dba0d1be5ac995041d60c169154d4f5e262593bd382b4b40fe65bf
    ;;
  *)
    printf 'usage: %s {default8|explicit4|explicit8}\n' "$0" >&2
    exit 2
    ;;
esac

gen_dir="$SIM_ROOT/f2-fasedtests-FixedReadProbe-DefaultConfig-$platform"
sim="$gen_dir/VFixedReadProbe"
fir="$gen_dir/firesim.fasedtests.FixedReadProbe.DefaultConfig.fir"
run_dir="$OUT/postfix-$1"
test -z "$(pgrep -u "$USER" -x VFixedReadProbe || true)"
test ! -e "$run_dir"
test -x "$sim" && test ! -L "$sim"
test "$(sha256sum "$sim" | awk '{print $1}')" = "$sim_sha"
test "$(sha256sum "$fir" | awk '{print $1}')" = "$FIR_SHA"
test "$(sha256sum "$PROFILE" | awk '{print $1}')" = "$PROFILE_SHA"
mapfile -t mm_args < <(awk 'NF && $1 !~ /^#/' "$PROFILE" | sed 's/=\(.*\)$/_0=\1/')
test "${#mm_args[@]}" -eq 34
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
