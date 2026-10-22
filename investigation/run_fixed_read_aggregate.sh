#!/usr/bin/env bash
set -euo pipefail
umask 077

ROOT=/scratch/trazzaque/chipyard
SIM_ROOT="$ROOT/sims/firesim/sim/generated-src/f2"
OUT=/scratch/trazzaque/firesim-host-builds/fixed-read-probe
suffix=${2:-}
if (( $# > 2 )) || [[ -n "$suffix" && ! "$suffix" =~ ^[A-Za-z0-9_-]+$ ]]; then
  printf 'optional repeat label must be a safe basename\n' >&2
  exit 2
fi

case "${1:-}" in
  ddr_1port)
    design=FixedReadProbe1M; platform=DDRF2Config; bridges=1
    fir_sha=b79a7a61aec20c11becf18761bd14a981ed07764405c94415b792088d6a20f8a
    sim_sha=14269590899909e7e1937c168014f68931aa97a19b0f7178456e45de04ea4b57
    ;;
  hbm2_1port)
    design=FixedReadProbe1M; platform=HBMF2Backend8Config; bridges=1
    fir_sha=b79a7a61aec20c11becf18761bd14a981ed07764405c94415b792088d6a20f8a
    sim_sha=8c3976c89654299ab5ade8301517d4bdeaa48408ffd67ea8bbc5edeea178733c
    ;;
  ddr_4port)
    design=FixedReadProbe4; platform=DDRF2Config; bridges=4
    fir_sha=3860853ca2ae7f692c2d010449ed7f28b0c98796d27d336a2ec2d2ab43d223a4
    sim_sha=075ba640bad3915996f02eeeeeab326172180487e07b8989b2b04a21eaed34aa
    ;;
  hbm2_4port)
    design=FixedReadProbe4; platform=HBMF2Backend8Config; bridges=4
    fir_sha=3860853ca2ae7f692c2d010449ed7f28b0c98796d27d336a2ec2d2ab43d223a4
    sim_sha=24e5f0332eec9fb32ce50d463fcbc6ad9eb30f56d7332ed715721aecc31b25dd
    ;;
  hbm2_1port_2400clk)
    design=FixedReadProbe1M; platform=HBMF2Backend8Config; bridges=1
    fir_sha=b79a7a61aec20c11becf18761bd14a981ed07764405c94415b792088d6a20f8a
    sim_sha=8c3976c89654299ab5ade8301517d4bdeaa48408ffd67ea8bbc5edeea178733c
    ;;
  ddr_1port_refresh30k)
    design=FixedReadProbe1M; platform=DDRF2Config; bridges=1
    fir_sha=b79a7a61aec20c11becf18761bd14a981ed07764405c94415b792088d6a20f8a
    sim_sha=14269590899909e7e1937c168014f68931aa97a19b0f7178456e45de04ea4b57
    ;;
  hbm2_1port_refresh30k)
    design=FixedReadProbe1M; platform=HBMF2Backend8Config; bridges=1
    fir_sha=b79a7a61aec20c11becf18761bd14a981ed07764405c94415b792088d6a20f8a
    sim_sha=8c3976c89654299ab5ade8301517d4bdeaa48408ffd67ea8bbc5edeea178733c
    ;;
  hbm2_1port_refsb)
    design=FixedReadProbe1M; platform=HBMF2Backend8Config; bridges=1
    fir_sha=b79a7a61aec20c11becf18761bd14a981ed07764405c94415b792088d6a20f8a
    sim_sha=8c3976c89654299ab5ade8301517d4bdeaa48408ffd67ea8bbc5edeea178733c
    ;;
  hbm2_4port_refsb)
    design=FixedReadProbe4; platform=HBMF2Backend8Config; bridges=4
    fir_sha=3860853ca2ae7f692c2d010449ed7f28b0c98796d27d336a2ec2d2ab43d223a4
    sim_sha=24e5f0332eec9fb32ce50d463fcbc6ad9eb30f56d7332ed715721aecc31b25dd
    ;;
  hbm2_1port_postfix_refab|hbm2_1port_postfix_refsb)
    design=FixedReadProbe1M; platform=HBMF2Backend8Config; bridges=1
    fir_sha=b79a7a61aec20c11becf18761bd14a981ed07764405c94415b792088d6a20f8a
    sim_sha=dbcc2b0c390744d876c468e3729c9b7ee8d456465e62e7d9fe74a687bf8fedcf
    ;;
  hbm2_4port_postfix_refab|hbm2_4port_postfix_refsb)
    design=FixedReadProbe4; platform=HBMF2Backend8Config; bridges=4
    fir_sha=3860853ca2ae7f692c2d010449ed7f28b0c98796d27d336a2ec2d2ab43d223a4
    sim_sha=d0dde63c90a7bad62ecdd9d3ab9235097a3daa2dc8d64f605595ddb72b9c0bca
    ;;
  hbm2_1port_interleaved_refab|hbm2_1port_interleaved_refsb)
    design=FixedReadProbeInterleaved1M; platform=HBMF2Backend8Config; bridges=1
    fir_sha=7fdb993f89f5c5e9530dc403b7af3b05352a236e3913e8ec17f66bf1da0bb0f2
    sim_sha=e0c5666e4e5b244b13e4acc87584fee8cb75d391ef882295e2805415f1d111da
    ;;
  ddr_1port_interleaved)
    design=FixedReadProbeInterleaved1M; platform=DDRF2Config; bridges=1
    fir_sha=7fdb993f89f5c5e9530dc403b7af3b05352a236e3913e8ec17f66bf1da0bb0f2
    sim_sha=77668cd8a602cf825dbf91e6879a4268f4f899870e532fb7a0f42b4689724719
    ;;
  hbm2_4port_interleaved_refab|hbm2_4port_interleaved_refsb)
    design=FixedReadProbeInterleaved4; platform=HBMF2Backend8Config; bridges=4
    fir_sha=d5508f74f2958de14360138917f6b0b190df6025453810c455a2596d7db86cff
    sim_sha=3f70dbdb23432272e0eeba26adc62c62b378944184fedb6c62874a564fab4322
    ;;
  ddr_4port_interleaved)
    design=FixedReadProbeInterleaved4; platform=DDRF2Config; bridges=4
    fir_sha=d5508f74f2958de14360138917f6b0b190df6025453810c455a2596d7db86cff
    sim_sha=93422b9780d2a36c21dea560659be79fc9ec4bfea25c56c97257a516edb26f26
    ;;
  hbm2_4port_2400clk)
    design=FixedReadProbe4; platform=HBMF2Backend8Config; bridges=4
    fir_sha=3860853ca2ae7f692c2d010449ed7f28b0c98796d27d336a2ec2d2ab43d223a4
    sim_sha=24e5f0332eec9fb32ce50d463fcbc6ad9eb30f56d7332ed715721aecc31b25dd
    ;;
  *)
    printf 'usage: %s MODE [repeat-label]; MODE is a DDR/HBM2 fixed-read profile, optionally with _interleaved, _refsb, or _postfix suffix\n' "$0" >&2
    exit 2
    ;;
esac

if [[ "$1" == ddr* ]]; then
  profile="$ROOT/investigation/runtime-configs/ddr3-FRFCFS-8G-4R-2133-OP.source.conf"
  profile_sha=592294830e684f51487d3ab12a4d0ede8a3ee60bb3403c46652b151687427f2f
  settings_per_bridge=28
else
  if [[ "$1" == *_2400clk ]]; then
    profile="$ROOT/investigation/runtime-configs/hbm2-FRFCFS-2400-1GHz-OP-REFab.source.conf"
    profile_sha=e5cd0194bc18ed24ad082cfd6ca277eb1d04b1a6ca7b12cfffe428ed45366cea
  elif [[ "$1" == *_refsb ]]; then
    profile="$ROOT/investigation/runtime-configs/hbm2-FRFCFS-2000-OP-REFSB.source.conf"
    profile_sha=03f86ef86c3095104807f14de46aa0c05e0c058da39bfe616190a56c3e598c69
  else
    profile="$ROOT/investigation/runtime-configs/hbm2-FRFCFS-2000-OP-REFab.source.conf"
    profile_sha=af92398e9db6acf877fc5373db406e78bc2c8841a33911480e8a40945a0c3ed3
  fi
  settings_per_bridge=34
fi

gen_dir="$SIM_ROOT/f2-fasedtests-$design-DefaultConfig-$platform"
sim="$gen_dir/V$design"
fir="$gen_dir/firesim.fasedtests.$design.DefaultConfig.fir"
run_dir="$OUT/aggregate-$1${suffix:+-$suffix}"
test -z "$(pgrep -u "$USER" -x VFixedReadProbe || true)"
test ! -e "$run_dir"
test -x "$sim" && test ! -L "$sim"
test "$(sha256sum "$sim" | awk '{print $1}')" = "$sim_sha"
test "$(sha256sum "$fir" | awk '{print $1}')" = "$fir_sha"
test "$(sha256sum "$profile" | awk '{print $1}')" = "$profile_sha"
mapfile -t base_args < <(awk 'NF && $1 !~ /^#/' "$profile")
test "${#base_args[@]}" -eq "$settings_per_bridge"
if [[ "$1" == *_refresh30k ]]; then
  replaced=0
  for ((arg_idx=0; arg_idx<${#base_args[@]}; arg_idx++)); do
    if [[ "$1" == ddr* && "${base_args[$arg_idx]}" == +mm_dramTimings_tREFI=7800 ]]; then
      base_args[$arg_idx]=+mm_dramTimings_tREFI=30000
      replaced=$((replaced + 1))
    elif [[ "$1" == hbm* && "${base_args[$arg_idx]}" == +mm_hbmTimings_tREFI=3900 ]]; then
      base_args[$arg_idx]=+mm_hbmTimings_tREFI=30000
      replaced=$((replaced + 1))
    fi
  done
  test "$replaced" -eq 1
fi
mm_args=()
for ((idx=0; idx<bridges; idx++)); do
  for arg in "${base_args[@]}"; do
    mm_args+=("${arg/=/_${idx}=}")
  done
done
test "${#mm_args[@]}" -eq "$((bridges * settings_per_bridge))"
for arg in "${mm_args[@]}"; do
  [[ "$arg" =~ ^\+mm_[A-Za-z0-9_]+_[0-3]=[0-9]+$ ]]
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
for ((idx=0; idx<bridges; idx++)); do
  test -s "$run_dir/memory_stats$idx.csv"
done
rg 'PASSED|COMMAND_EXIT_CODE' "$run_dir/console.log" | tail -3
