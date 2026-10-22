#!/usr/bin/env bash
set -euo pipefail
umask 077

ROOT=/scratch/trazzaque/chipyard
OUT=/scratch/trazzaque/firesim-host-builds/fixed-read-probe
GEN_DIR="$ROOT/sims/firesim/sim/generated-src/f2/f2-fasedtests-FixedReadProbe-DefaultConfig-HBMF2Config"
SIM="$GEN_DIR/VFixedReadProbe"
FIR="$GEN_DIR/firesim.fasedtests.FixedReadProbe.DefaultConfig.fir"
SIM_SHA=607e81443d1269616709de02dba1cc9ba150e2f17fa101d503f521a05f647647
FIR_SHA=8e8a36a8ca3242a3ac5ccbdb083b178307f66043b29ecdf09327a818839bd087

case "${1:-}" in
  raw2400)
    profile="$ROOT/investigation/runtime-configs/hbm2-FRFCFS-2400-OP-REFab.source.conf"
    profile_sha=9212d7c7d7417ec591a608136289eb0ef7c27311273a0a029d883db7518e11f9
    ;;
  converted2400)
    profile="$ROOT/investigation/runtime-configs/hbm2-FRFCFS-2400-1GHz-OP-REFab.source.conf"
    profile_sha=e5cd0194bc18ed24ad082cfd6ca277eb1d04b1a6ca7b12cfffe428ed45366cea
    ;;
  *)
    printf 'usage: %s {raw2400|converted2400}\n' "$0" >&2
    exit 2
    ;;
esac

run_dir="$OUT/timebase-$1"
test -z "$(pgrep -u "$USER" -x VFixedReadProbe || true)"
test ! -e "$run_dir"
test -x "$SIM" && test ! -L "$SIM"
test "$(sha256sum "$SIM" | awk '{print $1}')" = "$SIM_SHA"
test "$(sha256sum "$FIR" | awk '{print $1}')" = "$FIR_SHA"
test "$(sha256sum "$profile" | awk '{print $1}')" = "$profile_sha"
mapfile -t mm_args < <(awk 'NF && $1 !~ /^#/' "$profile" | sed 's/=\(.*\)$/_0=\1/')
test "${#mm_args[@]}" -eq 34
for arg in "${mm_args[@]}"; do
  [[ "$arg" =~ ^\+mm_[A-Za-z0-9_]+_0=[0-9]+$ ]]
done

mkdir -p "$run_dir"
(
  cd "$run_dir"
  printf 'START_UTC=%s\n' "$(date -u +%FT%TZ)"
  set +e
  timeout --signal=INT --kill-after=10s 5m "$SIM" "${mm_args[@]}" +max-cycles=5000000
  rc=$?
  printf 'COMMAND_EXIT_CODE="%d"\n' "$rc"
  printf 'END_UTC=%s\n' "$(date -u +%FT%TZ)"
  exit "$rc"
) >"$run_dir/console.log" 2>&1
rg -q '\*\*\* PASSED \*\*\* after [0-9]+ cycles' "$run_dir/console.log"
! rg -q '\*\*\* FAILED \*\*\*' "$run_dir/console.log"
test -s "$run_dir/memory_stats0.csv"
rg 'PASSED|COMMAND_EXIT_CODE' "$run_dir/console.log" | tail -3
