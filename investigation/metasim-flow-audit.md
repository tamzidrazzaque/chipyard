# Exact two-SM host-metasim flow

Audit date: 2026-10-21 PDT

This flow is host-only. It does not open, program, or otherwise access an FPGA,
and it does not require `sourceme-manager.sh` or SSH.

## Valid smoke artifact

The small controlled smoke ELF is:

```text
/scratch/trazzaque/radiance-kernels/kernels/stream/runs/two-sm-smoke/hashed/timed/copy-4096/kernel.soc.elf
SHA-256 5a4cb33dca8411be0867bf2143f2ee9b2ecf7fd1a7658e30629d94095e2f0bfa
size    93112 bytes
```

Its `result.json` SHA-256 is
`52c1663eca18d330bddea9610808e5d2efb7482f1ea0513ebb81e941b01ef3a8`.
The manifest and ELF were checked together and say:

- STREAM Copy, 4096 FP32 elements, expected complete-output digest
  `1594e827ff586325`;
- complete host readback and digest check, quiet-NaN output poison, and guard
  checks;
- host timing enabled;
- two Radiance clusters, two Muon cores per cluster, four total cores, and 256
  launched threads;
- completion protocol `per-core-barrier-l0d-fence-mailbox`;
- address hash enabled with size `0x80000000`, 32-byte units, four slices, and
  GPU host base `0x100000000`;
- required load path `direct-memory-load`.

The ELF contains `.radiance_addr_hash` with the byte-exact text:

```text
unit=32 slices=4 size=0x80000000 gpu_base=0x100000000
```

The unhashed and hashed builds use the same logical RV32 input ELF, SHA-256
`8b03ec53d15c3f2e7a94808a8ac65d15a9552d3c98df2fe1c3269b02c8b34b07`.
Only the direct-memory physical layout differs. The workload repository was
clean after the build. Its metadata/address-hash tests passed 4/4 and its
STREAM topology test passed 1/1.

The reproducible workload build command is:

```bash
source /scratch/trazzaque/tools/miniforge/etc/profile.d/conda.sh
conda activate /scratch/trazzaque/chipyard/.conda-env
source /scratch/trazzaque/chipyard/env.sh
export RISCV_TOOLCHAIN_PATH="$RISCV"
export RISCV64_TOOLCHAIN_PATH="$RISCV"
export HOST_LDFLAGS='-static -B/scratch/trazzaque/tools/riscv64-unknown-elf/lib/ -specs=/scratch/trazzaque/tools/riscv64-unknown-elf/lib/htif_nano.specs'
cd /scratch/trazzaque/radiance-kernels/kernels/stream
make clean
MU_ADDR_HASH=1 python3 run.py \
  --kind copy \
  --elements 4096 \
  --out runs/two-sm-smoke/hashed/timed/copy-4096 \
  --full-host-check \
  --host-timing \
  --muon-clusters 2
```

## Why the unhashed smoke ELF is invalid here

The controlled target has ExtMem/FASED and a LoadMem widget. In the current
driver, `firesim_tsi_t` unconditionally assigns
`has_loadmem = can_have_loadmem`. During FESVR ELF loading,
`testchip_tsi_t::load_program` consequently selects `load_mem_write`, and
`tsibridge_t` sends those writes directly to
`loadmem_widget.write_mem_chunk(address + host_offset, ...)`. They do not
cross the target's Radiance address-hash node.

This is true both when the ELF is the final positional argument used by
`make run-verilator` and when it is wrapped in `+prog0=...`; those forms only
change how the same TSI bridge constructs FESVR's argv. There is no runtime
plusarg that forces serialized TSI loading in this source. Therefore:

- use the hashed smoke ELF above for both HBM and DDR controlled metasims;
- do not use the existing unhashed smoke ELF on this target;
- do not add `+loadmem=kernel.soc.elf`; that option is a raw-memory-image path,
  not the ELF-aware FESVR path;
- do not use a no-ExtMem target merely to make serialized TSI possible, because
  it would no longer test the controlled five-FASED-bridge target.

## Exact Verilator builds

Both post-fix Golden Gate and Verilator builds completed in the isolated root
`/scratch/trazzaque/firesim-host-builds/b0bb67a7cf4454b8-590ebc4e7e1061a7`.
The HBM executable SHA-256 is
`519241cb84371a1013a55090cfa48eeec4aea919b18b3df4e10ea74a651bc353`;
the DDR executable SHA-256 is
`14591281c1aa1f8c1d98820d91e2d96e1b13d1fe4b19a6edb1228f6ae7f7b874`.
Both are regular executable files, have the exact audited FESVR/conda RPATH,
and pass `ldd -r`. Full generated-artifact, log, width, warning, and dependency
evidence is in
[`exact-goldengate-verilator-provenance.md`](exact-goldengate-verilator-provenance.md).

FESVR is a host dependency, not the target cross-toolchain. The conda target
toolchain does not contain `libfesvr.a`, so keep `RISCV` unchanged and select
the pinned host installation separately:

```bash
source /scratch/trazzaque/tools/miniforge/etc/profile.d/conda.sh
conda activate /scratch/trazzaque/chipyard/.conda-env
source /scratch/trazzaque/chipyard/sims/firesim/env.sh
export FIRESIM_FESVR_PREFIX=/scratch/trazzaque/tools/spike-host-9c190a07c683-noboost
test -d "$FIRESIM_FESVR_PREFIX/include/fesvr"
test -f "$FIRESIM_FESVR_PREFIX/lib/libfesvr.a"
test -f "$FIRESIM_FESVR_PREFIX/lib/libriscv.so"
test "$(sha256sum "$FIRESIM_FESVR_PREFIX/lib/libfesvr.a" | awk '{print $1}')" = \
  251b001beb6a387f306ee86e58dc69d013c452c30eea8ad069097c5b39d82867
test "$(sha256sum "$FIRESIM_FESVR_PREFIX/lib/libriscv.so" | awk '{print $1}')" = \
  e6c85d5a37d9e34eebb405c89f71aca6125d32ae0b1e0e18e7dad7290ea933ef
```

Nested FireSim commit `590ebc4e7e1061a7b96bb333b7c692701a791bac`
forwards `FIRESIM_FESVR_PREFIX` to manager-started bitstream, driver, and
runtime builds. The target-project driver makefrags use that prefix for FESVR
headers plus both `libfesvr` and `libriscv`, and fail immediately if either is
absent. Never set `RISCV` to this host-only prefix;
target software and debug-ROM generation still need the cross-compiler.
The installed include-tree hash is
`a15648d7dcedaba7a061218a420fe65eddc4688493b31f33e98a752c79258a49` and is
checked by the campaign validator.

The successful builds used each generated directory for `registers.svh`, kept
ordinary diagnostics visible with `-Wno-fatal`, used the reviewed imported
FPNew compatibility flag `-Wno-BLKANDNBLK`, and enabled `--assert`. The fresh
width scan found no object above 65,536 bits, so neither command used a
`--max-num-width` override. The exact executables are:

```text
/scratch/trazzaque/firesim-host-builds/b0bb67a7cf4454b8-590ebc4e7e1061a7/generated-src/corigine_xb10/corigine_xb10-firesim-FireSim-FireSimE4M3MxGemminiTwoClusterHBMRadianceConfig-HBM2FRFCFS16GBDualPC_BaseCorigineXB10Config/VFireSim
/scratch/trazzaque/firesim-host-builds/b0bb67a7cf4454b8-590ebc4e7e1061a7/generated-src/corigine_xb10/corigine_xb10-firesim-FireSim-FireSimE4M3MxGemminiTwoClusterHBMRadianceConfig-FRFCFS8GBQuadRank_BaseCorigineXB10Config/VFireSim
```

The pair was built sequentially; each Verilator sub-build used eight jobs.

## Exact smoke runs

The block below reproduces the target makefrag's simulation arguments but runs
each executable in an isolated working directory. Isolation preserves its five
`memory_statsN.csv` files and other relative-path outputs, and avoids the stock
`run-verilator` rule's basename-derived `.out` collision across conditions.
Run the three conditions sequentially because the default NIC shared-memory
name is identical.

```bash
source /scratch/trazzaque/tools/miniforge/etc/profile.d/conda.sh
conda activate /scratch/trazzaque/chipyard/.conda-env
source /scratch/trazzaque/chipyard/sims/firesim/env.sh
set -euo pipefail
umask 077

ROOT=/scratch/trazzaque/chipyard
BUILD_ROOT=/scratch/trazzaque/firesim-host-builds/b0bb67a7cf4454b8-590ebc4e7e1061a7
SIM_ROOT="$BUILD_ROOT/generated-src/corigine_xb10"
HBM_SIM="$SIM_ROOT/corigine_xb10-firesim-FireSim-FireSimE4M3MxGemminiTwoClusterHBMRadianceConfig-HBM2FRFCFS16GBDualPC_BaseCorigineXB10Config/VFireSim"
DDR_SIM="$SIM_ROOT/corigine_xb10-firesim-FireSim-FireSimE4M3MxGemminiTwoClusterHBMRadianceConfig-FRFCFS8GBQuadRank_BaseCorigineXB10Config/VFireSim"
ELF=/scratch/trazzaque/radiance-kernels/kernels/stream/runs/two-sm-smoke/hashed/timed/copy-4096/kernel.soc.elf
OUT="$BUILD_ROOT/metasim-smoke-copy-4096"
printf -v NET_SHMEM '%0100d' 0

run_one() {
  local label=$1 sim=$2 sim_sha=$3 profile=$4 profile_sha=$5 expected_args=$6
  local run_dir="$OUT/$1"
  local arg idx
  local -a mm_args seen=(0 0 0 0 0)
  test -z "$(pgrep -u "$USER" -x VFireSim || true)"
  test -z "$(find /dev/shm -mindepth 1 -maxdepth 1 -name "$NET_SHMEM" -print 2>/dev/null)"
  test -x "$sim"
  test ! -L "$sim"
  test "$(sha256sum "$sim" | awk '{print $1}')" = "$sim_sha"
  test "$(sha256sum "$ELF" | awk '{print $1}')" = \
    5a4cb33dca8411be0867bf2143f2ee9b2ecf7fd1a7658e30629d94095e2f0bfa
  test "$(sha256sum "$profile" | awk '{print $1}')" = "$profile_sha"
  mapfile -t mm_args < <(awk 'NF && $1 !~ /^#/' "$profile")
  test "${#mm_args[@]}" -eq "$expected_args"
  for arg in "${mm_args[@]}"; do
    [[ "$arg" =~ ^\+mm_[A-Za-z0-9_]+_([0-4])=-?[0-9]+$ ]]
    idx=${BASH_REMATCH[1]}
    seen[$idx]=$((seen[$idx] + 1))
  done
  for idx in 0 1 2 3 4; do
    test "${seen[$idx]}" -eq "$((expected_args / 5))"
  done
  # Fail closed rather than mix a rerun with stale relative-path outputs.
  test ! -e "$run_dir"
  mkdir -p "$run_dir"
  (
    cd "$run_dir"
    set +e
    "$sim" \
      +permissive \
      +fesvr-step-size=128 \
      "+shmemportname0=$NET_SHMEM" \
      +macaddr0=00:00:00:00:00:02 \
      +niclog0=niclog0 \
      +linklatency0=6405 \
      +netbw0=100 \
      +netburst0=8 \
      +nic-loopback0 \
      +tracefile=TRACEFILE \
      +blkdev-in-mem0=128 \
      +blkdev-log0=blkdev-log0 \
      +autocounter-readrate=1000 \
      +autocounter-filename-base=AUTOCOUNTERFILE \
      +profile-interval=10000000 \
      +max-cycles=100000000 \
      "${mm_args[@]}" \
      +permissive-off \
      "$ELF" </dev/null
    rc=$?
    printf 'COMMAND_EXIT_CODE="%d"\n' "$rc"
    exit "$rc"
  ) >"$run_dir/console.log" 2>&1
}

run_one hbm2400 "$HBM_SIM" \
  519241cb84371a1013a55090cfa48eeec4aea919b18b3df4e10ea74a651bc353 \
  "$ROOT/investigation/runtime-configs/hbm2-FRFCFS-2400-OP-REFab-5bridge.conf" \
  372af4e4a05a168bcdcc37dd853f6dbf3849b6c3585fc595b31522290f852cf8 170
run_one hbm2000 "$HBM_SIM" \
  519241cb84371a1013a55090cfa48eeec4aea919b18b3df4e10ea74a651bc353 \
  "$ROOT/investigation/runtime-configs/hbm2-FRFCFS-2000-OP-REFab-5bridge.conf" \
  2d45764907b723a66dc30a4547f9ed10d122a9da8132e5380febac76f80fd5ab 170
run_one ddr2133 "$DDR_SIM" \
  14591281c1aa1f8c1d98820d91e2d96e1b13d1fe4b19a6edb1228f6ae7f7b874 \
  "$ROOT/investigation/runtime-configs/ddr3-FRFCFS-8G-4R-2133-OP-5bridge.conf" \
  dc133659c8f8e4a8cfd14e6779a373bbcb005cc7143507320d1edf5e1014fc6a 140
```

HBM-2400 and HBM-2000 deliberately use the same HBM executable; only their
complete indexed runtime timing vectors differ. DDR uses the controlled DDR
executable. The profiles contain 170, 170, and 140 nonempty arguments,
respectively, covering model indices 0 through 4.

The emitted `C0:` instruction lines are the target's built-in RocketCore
printf stream, not TracerV output. This target has no TracerV widget, so the
stock `+tracefile` argument is inert and the zero-byte encoded trace file is
expected. It is not missing correctness evidence; the UART, pass marker, and
five FASED statistics files carry the smoke contract.

## Required passing evidence

For every `console.log`, require all of the following, not merely process exit
zero:

- exactly one `Simulation complete.` and exactly one
  `*** PASSED *** after N cycles`;
- no `*** FAILED ***`;
- appended `COMMAND_EXIT_CODE="0"`;
- one positive `HOST_RELEASE_TO_DONE_CYCLES`;
- exactly four ordered, internally consistent mailbox lines for cluster/core
  `(0,0)`, `(0,1)`, `(1,0)`, `(1,1)`;
- one positive `kernel_cycles` equal to latest END minus earliest START modulo
  32 bits;
- exactly `memory_stats0.csv` through `memory_stats4.csv`, each with a header
  and at least one data row. FireSim commit
  `590ebc4e7e1061a7b96bb333b7c692701a791bac` guarantees a terminal row even
  when the run finishes before its first periodic sample;
- no `latency_histogram*.csv` or `range_counters*.csv` files for these exact
  targets. Their generated bridge address maps contain no histogram or range
  instrumentation, so absent files are the expected result rather than lost
  evidence.

The existing strict UART parser checks the UART and completion conditions
above. Check the CSV conditions separately with the following block.

```bash
PYTHONPATH=/scratch/trazzaque/radiance-kernels/kernels/evaluation/firesim \
python3 - <<'PY'
from pathlib import Path
from host_interval import parse_uart_evidence

root = Path('/scratch/trazzaque/firesim-host-builds/b0bb67a7cf4454b8-590ebc4e7e1061a7/metasim-smoke-copy-4096')
for label in ('hbm2400', 'hbm2000', 'ddr2133'):
    log = (root / label / 'console.log').read_text(errors='replace')
    evidence = parse_uart_evidence(log, expected_clusters=2,
                                   expected_cores_per_cluster=2)
    print(label, evidence)
PY
```

Check the five model outputs:

```bash
for label in hbm2400 hbm2000 ddr2133; do
  run_dir="/scratch/trazzaque/firesim-host-builds/b0bb67a7cf4454b8-590ebc4e7e1061a7/metasim-smoke-copy-4096/$label"
  for idx in 0 1 2 3 4; do
    test -f "$run_dir/memory_stats${idx}.csv"
    awk 'END { exit !(NR >= 2) }' "$run_dir/memory_stats${idx}.csv"
  done
  ! compgen -G "$run_dir/latency_histogram*.csv" >/dev/null
  ! compgen -G "$run_dir/range_counters*.csv" >/dev/null
done
```

The guest sets `tohost=1` only if all four cores complete, both guards remain
intact, and the full 4096-word digest equals `1594e827ff586325`; otherwise it
sets `tohost=3`, which produces a FireSim failure. Thus the pass marker plus the
pinned ELF/manifest hash is the digest evidence even though the digest value is
not printed on UART.

## Fresh sequential host-smoke results

The three conditions ran sequentially from the isolated build root. Every log
contains exactly one completion marker, one canonical pass, and one appended
exit code 0, with no failure, assertion, fatal, or nonconvergence marker. The
strict UART parser accepted exactly two clusters, two cores per cluster, and
four mailbox reports in every condition.

| Condition | Settings/model | Whole-program cycles | Host-release-to-done | Kernel cycles | Host wallclock (s) | Console SHA-256 |
| --- | ---: | ---: | ---: | ---: | ---: | --- |
| HBM2-2400 | 34 | 395266 | 15106 | 13670 | 2325.5 | `816be84116a59a1568911a63167d381faba03dda230f995b067c7d4880a7d75a` |
| HBM2-2000 | 34 | 392194 | 14063 | 12682 | 2302.3 | `99463fad7d77431c865962ffe8cf8c155f31b0c6ef4c4ba4d93c2e8275e0fd7b` |
| DDR3-2133 | 28 | 386050 | 12807 | 11538 | 1521.9 | `cdea3becc6e5d62c52906ca3b1acc031e498c6c44356da40f4d304b32a1a59f4` |

The exact mailbox reports are start-end with each core's elapsed cycles in
parentheses:

| Condition | Cluster 0/core 0 | Cluster 0/core 1 | Cluster 1/core 0 | Cluster 1/core 1 |
| --- | --- | --- | --- | --- |
| HBM2-2400 | 1243-14855 (13612) | 1244-14854 (13610) | 1226-14894 (13668) | 1225-14895 (13670) |
| HBM2-2000 | 1169-13757 (12588) | 1168-13756 (12588) | 1187-13841 (12654) | 1190-13850 (12660) |
| DDR3-2133 | 1297-12443 (11146) | 1259-12572 (11313) | 1034-12178 (11144) | 1037-12198 (11161) |

Every statistics file is a regular, non-symlink file with exactly three rows:
one header, one initial row, and one terminal row. HBM has 16 unique named
fields and DDR has 32; each row also has the generator's expected trailing
empty field after the final comma. Every data cell is a canonical uint32. The
terminal file hashes are:

| Condition | Model | `memory_statsN.csv` SHA-256 |
| --- | ---: | --- |
| HBM2-2400 | 0 | `3668d82d800fb58832bde28ccd8ebf471b09adec81daab5dda306cbe3aaef657` |
| HBM2-2400 | 1 | `aa2c1e11f85a8384558e848d16cc9c6dae844dcac1cf3aac112306c38b68336b` |
| HBM2-2400 | 2 | `4cd0308fc1d7ecd179d5aa7312fd01ae242567d062172b12180135e369f8ff6f` |
| HBM2-2400 | 3 | `a0beeaa8dee8ace2690345fc176850cf18bf6e0c135d0b8bb705052711086730` |
| HBM2-2400 | 4 | `bb0a14342a5ee788663ec827dc62fe15fc2174c328c0b35609a635c6ee2438b9` |
| HBM2-2000 | 0 | `9c2a6d980f2caa59ecfba355cd9aea766f87e9f06dbcad0f21969574c2ef0ed9` |
| HBM2-2000 | 1 | `028f7d3da9ce5eaeb71a163c7320456f406a1c8da5e442ee044cadfdb52c7e5d` |
| HBM2-2000 | 2 | `75642cf918614227dce199b17a165aa3da9dc5b1bf808c8bd66260dd965ecf79` |
| HBM2-2000 | 3 | `c022033746d1e1f1ab4396dacb7212fe71cab4b0ce5128620b07e00cbc14df0c` |
| HBM2-2000 | 4 | `5553a8c769a1cb880d3f887c9febbba24fe6787605158d2367fefdf3742e7897` |
| DDR3-2133 | 0 | `abe862eacb89badd40c08cb26875069047178a858712f4c40b4a31ae56bfeaf1` |
| DDR3-2133 | 1 | `b5c51e257460f60ad605f32ff8e7af0f0067f8ae34bae6da1cbf020f80ea28c7` |
| DDR3-2133 | 2 | `77a25bd44c67237ae06b3b16413174d81d6540ac7a4410137570d2dd748c12cc` |
| DDR3-2133 | 3 | `8b932fd4934d09524e496b4978a7d26be3ad3a6c5e27b2fcd4fb8f610f3c78b7` |
| DDR3-2133 | 4 | `9be3e93e9aec6b28a9dc41a6352d5aaf80496b27a5a3d53535f428ca02b18365` |

No condition emitted a latency-histogram or range-counter file, exactly as the
generated bridge maps predict. `host-only-validation.sha256` binds the raw
consoles and CSVs together with their simulators, profiles, build logs, and
generated artifacts.

These small metasims are correctness/configuration smokes, not FPGA performance
measurements. Do not substitute their wall time or tiny-workload cycles for the
required real-XB10 campaign.

FASED output handling is no longer a five-model collision. FireSim commit
`590ebc4e7e1061a7b96bb333b7c692701a791bac` assigns indexed names
`latency_histogramN.csv` and `range_countersN.csv` when those optional features
exist, emits no placeholder files when they do not, and always appends a final
`memory_statsN.csv` sample in `finish()`. These exact HBM and DDR configurations
disable both optional features, so only the five indexed memory-statistics
files are expected. The explicit 10,000,000-cycle profile interval matches the
controlled runtime templates and adds periodic samples for longer runs without
being required for terminal evidence.
