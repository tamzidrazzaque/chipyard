# Native STREAM and Spatter workload audit

This audit started from `copparihollmann/radiance-kernels` branch
`spatter-workloads` at exact handoff
`9532571b2caa27da097108f041945d05a151bc90`. The checkout is
`/scratch/trazzaque/radiance-kernels`; no FPGA was opened or programmed. The
workload-side fixes are on local branch `investigation/two-sm-workloads`:

- `36e1d8b`: selectable one-/two-cluster STREAM and standard Spatter mappings;
- `7daa95e`: reject unsafe multi-cluster materialized Spatter chains;
- `97649f2`: deterministic STREAM poison and fenced per-core END completion;
- `955a8b8`: address-hash/build provenance in every result manifest;
- `d0cc00b`: strict archive validation of every selected core's mailbox report;
- `94c9b41`: document the new timing and correctness contract.

The final 36-ELF two-SM matrix was built at `d0cc00b286f5f3b6de6238857746ffca3f83838b`.

## Pinned inputs and tools

- GPU STREAM Spatter deck:
  `kernels/spatter/inputs/standard-suite/basic-tests/gpu-stream.json`, SHA-256
  `34d10c083f159800fbfd05fa50ae8041a871e3e9872cf8692c9d8c0523ebb4c9`.
- Upstream Spatter correctness oracle:
  `hpcgarage/spatter` at
  `ec8923711f8dc21eedff7189f12b02eb06845d2f`.
- Muon LLVM source/release:
  `d2f676d746659a79902328d77371d9f136aace65`; the released
  `llvm-muon.tar.xz` has SHA-256
  `d9a59878bba627f668246ed3790534a3f1d2187f7a264562cc2329f3272bc999`
  and the release-script MD5
  `8b25da8981a6d93df4b8a8ea956cbfd2`.
- `lib/mxgemmini` submodule:
  `6fc8ec79bc828b33628ec951bfa1d0f65278a338`.
- Cross compiler used for this compile check:
  `riscv64-unknown-elf-gcc 13.2.0` from Chipyard's pinned conda environment.
  The local HTIF libgloss was built from Chipyard submodule
  `39234a16247ab1fa234821b251f1f1870c3de343` because the conda toolchain did
  not yet contain `htif_nano.specs` or `libgloss_htif.a`.

## Exact nine-case baseline

### What "SM" means here

In this project, **one SM is one Radiance cluster**, and a cluster contains two
Muon cores. This is explicit in three independent primary sources:

- `radiance/cyclotron/src/command_proc.rs` says the command processor schedules
  threadblocks onto "clusters (CUs/SMs)", while `radiance/docs/muon.md` says a
  cluster contains multiple Muon cores, SMEM, and L1.
- This workload SHA's `lib/include/nightly/device.h` calls
  `RadianceHBMConfig` "2 clusters (SMs)"; `nightly/host.h` separately fixes two
  cores per cluster.
- The shared archive named `radiance-2sm-hbm-2026-10-11` records target class
  `FireSimE4M3MxGemminiTwoClusterHBMRadianceConfig`; the corresponding
  `radiance-1sm-hbm-2026-10-11` archive records the single-cluster
  `FireSimE4M3MxGemminiHBMRadianceConfig`.
- The attached handoff itself labels Chipyard commit `7799285d` as “two
  clusters” and `3dd077e9` as “four clusters” while requesting historical
  “2-SM”/“4-SM” comparisons. The attached transcript also reads out
  `FireSimE4M3MxGemminiTwoClusterRadianceConfig` while discussing the 2-SM
  build. The transcript is noisy, but here it agrees with source and archives.

The pinned E4M3 Scala config agrees: `SingleClusterConfig` has one
`WithRadianceCluster` and `WithMuonCores(2)`, while `TwoClusterConfig` repeats
that pair for clusters 0 and 1. Thus the requested/historical two-SM target is
**TwoCluster/four Muon cores**, not SingleCluster/two cores.

All kernels schedule four warps per Muon core: eight warps/128 launch threads
per cluster. The handoff default remains one cluster/two cores, while
`--muon-clusters 2` emits the requested two-SM topology: two clusters, four
Muon cores, and 256 launch threads. The generated config precedes
`mu_intrinsics.h`, and the global work stride includes both clusters. Each case
executes once per ELF; there is no in-guest warm-up loop and no repeated timed
iteration.

| Case | Native size | Logical payload | Complete-output FNV-1a digest |
| --- | ---: | ---: | --- |
| STREAM Copy | 1,048,576 FP32 elements | 8,388,608 B | `49fabae987622325` |
| STREAM Scale | 1,048,576 FP32 elements | 8,388,608 B | `6e48e2288e622325` |
| STREAM Add | 1,048,576 FP32 elements | 12,582,912 B | `8bf67ebb39622325` |
| STREAM Triad | 1,048,576 FP32 elements | 12,582,912 B | `44cd90308b622325` |
| Spatter 0 Gather | 256 entries x 1,024 repetitions | 4,194,304 B | `b0f2661f6d70c8cf` |
| Spatter 1 Scatter | 256 entries x 1,024 repetitions | 4,194,304 B | `6395beb9b9c4eb25` |
| Spatter 2 GS | 256 entries x 1,024 repetitions | 4,194,304 B | `5aa95b60e54bf326` |
| Spatter 3 MultiScatter | 256 entries x 1,024 repetitions | 4,194,304 B | `6395beb9b9c4eb25` |
| Spatter 4 MultiGather | 256 entries x 1,024 repetitions | 4,194,304 B | `b0f2661f6d70c8cf` |

STREAM runs are independent ELFs, not a Copy -> Scale -> Add -> Triad chain.
Copy and Scale access one 4 MiB input and one 4 MiB output; Add and Triad
access two 4 MiB inputs and one 4 MiB output. Spatter moves each opaque 64-bit
value as two 32-bit loads and two 32-bit stores. Its logical payload excludes
pattern/index traffic and cache-line amplification.

The Spatter deck's `local-work-size: 1024` is retained only as
`requested_local_work_size` in the manifest. It does not set the Muon launch:
the kernel launch is fixed at four warps per core. The identity-pattern deck
therefore measures the Radiance mapping, not an upstream CUDA launch geometry.

## Timing and correctness boundary

Build the measured ELFs with both `--full-host-check` and `--host-timing`.
`HOST_RELEASE_TO_DONE_CYCLES` is read by the RV64 host immediately before reset
release and immediately after every selected Muon core posts a nonzero END
mailbox. Every thread first reaches barrier 15; one warp then executes
`mu_fence` on each core, and lane 0 posts END only after that fence returns.
Thus the interval includes launch/polling and the selected cores' L0d drains,
but excludes the later UART report and output digest. Its units are RV64 host
cycles, not Muon cycles or calibrated nanoseconds. The report separately emits
each core's Muon `mcycle` START/END and `kernel_cycles = latest END - earliest
START`. FireSim's `*** PASSED *** after N cycles` remains a whole-program target
count and must not be substituted for either interval.

This protocol deliberately does not use raw `GPU_ALL_FINISHED`: the pinned
hardware exports `core.io.finished` before its finish-triggered L0d flush is
known complete. It requires `lw.shared`/`sw.shared` mailbox decoding and a
functional per-core `mu_fence`. Handoff Radiance `dd1a74f` does not decode the
shared memory opcode variants, so these ELFs will wait forever there. Local
Radiance commit `bd6c4b7af8fc90b939061862baa35c2f200899cd` adds that decode and
also fixes soft-reset fetch and keeps simulation alive for host readback. An
FPGA image must include that fix (or an independently equivalent, tested fix)
before this workload protocol can execute.

The strict parser is `kernels/evaluation/firesim/host_interval.py`. In addition
to one positive interval, a passing guest, simulator completion, driver exit
zero, full readback, planned ELF hash, and a byte-identical untimed RV32
control, it now requires the exact manifest protocol and one ordered,
internally consistent START/END report for every selected core. The final
matrix passed byte-identity checks for all 18 timed/control RV32 pairs.

There is no built-in warm-up. For the final pair, use a separately labelled
excluded first run followed by at least five complete, independently captured
runs per case/model. Alternate the model order across run blocks when practical
and retain every correctness result; do not silently retry or discard a failed
run. This is an external campaign rule, not a property of the current ELF.

## Direct-load address hashing

For a direct `+loadmem` or FireSim LoadMem load into a target that instantiates
the four-slice GPU address hash, use:

```sh
MU_ADDR_HASH=1 MU_ADDR_HASH_SIZE=0x80000000 \
MU_ADDR_HASH_UNIT=32 MU_ADDR_HASH_SLICES=4
```

Use `MU_ADDR_HASH=0` for an unhashed target or a TSI path. Never send a hashed
ELF through TSI, which would apply the hash twice. The nine hashed builds in
this audit each contain:

```text
unit=32 slices=4 size=0x80000000 gpu_base=0x100000000
```

in `.radiance_addr_hash`; all nine unhashed controls lack that section. The
rewritten PT_LOAD contents were reproduced with `scramble_gpu_elf.py`, including
its 100,000-address bijection check. This validates the software rewrite, not
that a newly generated target uses those parameters. Require the generated RTL
parameters to agree before loading.

The fixed `result.json` records `mu_addr_hash`, normalized size/unit/slices,
ELF and GPU host bases, the required load path, exact source-bundle hash,
tool/submodule revisions, and SHA-256/size for the linked device ELF, fused SoC
ELF, hash-rewritten device ELF when applicable, and `libmuonrt.a`. A generated
host-settings stamp also forces `host.host.o` to rebuild when timing or full
readback flags change.

## Correctness findings and remediation

1. Spatter clears its complete output and writes guard words before the timed
   interval, then checks a full digest and both guards after it. All five
   generated expectations were rerun locally through the pinned, unmodified
   upstream Spatter serial kernels and matched.
2. The handoff STREAM host left its BSS output untouched, so a repeated run
   could inherit a correct result. The fixed host fills every FP32 output word
   with a deterministic quiet-NaN poison before the timestamp. Native STREAM
   results are finite, so skipped or partial output cannot match the digest.
3. Radiance uses **cluster = CU/SM**, not Muon core = SM. The exact source says
   its command processor schedules onto "clusters (CUs/SMs)" and documents a
   Radiance cluster as containing multiple Muon cores, SMEM, and L1. The pinned
   E4M3 `SingleClusterConfig` instantiates one cluster with two Muon cores; its
   `TwoClusterConfig` instantiates two such clusters, hence four Muon cores.
   This also matches the archived image labels: `radiance-1sm-hbm-2026-10-11`
   names `FireSimE4M3MxGemminiHBMRadianceConfig` (the single-cluster target),
   whereas `radiance-2sm-hbm-2026-10-11` names
   `FireSimE4M3MxGemminiTwoClusterHBMRadianceConfig`. Therefore the handoff's
   historical/requested **two-SM target is TwoCluster/four Muon cores**, not
   SingleCluster/two cores.

   The handoff hard-coded `MU_NUM_CLUSTERS=1`; on TwoCluster that duplicated
   residue classes and invalidated traffic/timing. The fixed generators keep
   one cluster as the default but accept `--muon-clusters 2`, emit the constant
   before `mu_intrinsics.h`, record the complete topology, and use a 256-thread
   global stride. All nine requested standard cases were rebuilt that way.
   `run_chain.py` intentionally rejects two clusters because its stage barrier
   is cluster-local and cannot order an intermediate produced by the other
   cluster; standard cases 0-4 do not use that materialized chain.
4. Both families now launch through the repository's proven nightly mailbox
   protocol and accept completion only after every selected core's barrier,
   L0d fence, and END post. This fixes the workload boundary but depends on the
   shared-opcode RTL support described above; compilation alone cannot validate
   that hardware behavior.

## Tests completed on this VM

```text
python3 -m unittest -v kernels/test_build_metadata.py   4/4 passed
cd kernels/stream && python3 -m unittest -v test_run.py 1/1 passed
cd kernels/spatter && python3 -m unittest -v test_run.py
                                                        10/10 passed
python3 -m unittest -v kernels/evaluation/firesim/test_host_interval.py
                                                        7/7 passed
python3 -m compileall -q kernels/stream kernels/spatter kernels/evaluation/firesim
                                                        passed
two-SM result/artifact/marker/topology verifier          36/36 passed
timed/control embedded RV32 image comparison            18/18 equal
hashed/unhashed embedded RV32 negative comparison        9/9 different
sha256sum -c investigation/workload-elfs-two-sm.sha256  36/36 passed
```

The core setup/build commands used were:

```sh
GIT_CONFIG_GLOBAL=/dev/null git clone --branch spatter-workloads --single-branch \
  https://github.com/copparihollmann/radiance-kernels.git \
  /scratch/trazzaque/radiance-kernels
git -C /scratch/trazzaque/radiance-kernels rev-parse HEAD
GIT_CONFIG_GLOBAL=/dev/null git -C /scratch/trazzaque/radiance-kernels \
  submodule update --init lib/mxgemmini llvm/llvm-src

cd /scratch/trazzaque/radiance-kernels
./scripts/llvm_prebuilt.sh

mkdir -p /scratch/trazzaque/tools/libgloss-build \
  /scratch/trazzaque/tools/riscv64-unknown-elf
cd /scratch/trazzaque/tools/libgloss-build
PATH=/scratch/trazzaque/chipyard/.conda-env/riscv-tools/bin:$PATH \
  /scratch/trazzaque/chipyard/toolchains/libgloss/configure \
  --prefix=/scratch/trazzaque/tools/riscv64-unknown-elf \
  --host=riscv64-unknown-elf --disable-multilib
PATH=/scratch/trazzaque/chipyard/.conda-env/riscv-tools/bin:$PATH make -j4
PATH=/scratch/trazzaque/chipyard/.conda-env/riscv-tools/bin:$PATH make install
```

`make install` copied the requested files and then returned nonzero because the
separate prefix is intentionally outside GCC's default search list. The builds
therefore pass it explicitly with `-B`:

```sh
cd /scratch/trazzaque/radiance-kernels
export LLVM_MUON=/scratch/trazzaque/radiance-kernels/llvm/llvm-muon
export RISCV_TOOLCHAIN_PATH=/scratch/trazzaque/chipyard/.conda-env/riscv-tools
export RISCV_PREFIX=riscv64-unknown-elf
export RISCV_SYSROOT=$RISCV_TOOLCHAIN_PATH/riscv64-unknown-elf
export RISCV64_TOOLCHAIN_PATH=$RISCV_TOOLCHAIN_PATH
export RISCV=$RISCV_TOOLCHAIN_PATH
export GEMMINI_SW_PATH=/scratch/trazzaque/radiance-kernels/lib/mxgemmini
export MU_STACK_WORD_STRIDE=16
export HOST_LDFLAGS='-static -B/scratch/trazzaque/tools/riscv64-unknown-elf/lib/ -specs=/scratch/trazzaque/tools/riscv64-unknown-elf/lib/htif_nano.specs'

MU_ADDR_HASH=1 python3 kernels/stream/run.py --kind copy \
  --elements 1048576 --full-host-check --host-timing \
  --muon-clusters 2 \
  --out kernels/stream/runs/two-sm-native/hashed/timed/copy
MU_ADDR_HASH=1 python3 kernels/spatter/run.py \
  --suite kernels/spatter/inputs/standard-suite/basic-tests/gpu-stream.json \
  --case 0 --full-host-check --host-timing --muon-clusters 2 --build-only \
  --out kernels/spatter/runs/two-sm-native/hashed/timed/case-0-gather
```

The four STREAM kinds and Spatter cases 0 through 4 were built sequentially,
with `make clean` and `make clean-generated` before every artifact because each
family shares `generated/`. The same commands with `MU_ADDR_HASH=0` produced
the unhashed set; omitting `--host-timing` produced the untimed controls.

An independent CPU implementation reproduced all four 1,048,576-element
STREAM digests. The pinned upstream Spatter serial implementation reproduced
all five Spatter digests and parser expansions. All 36 two-SM fused SoC ELFs
built: nine cases x hashed/unhashed x timed/control. Each timed build has a
full-readback control with a byte-identical embedded RV32 image.
`workload-elfs-two-sm.sha256` records the 36 fused hashes; its paths are
relative to `/scratch/trazzaque/radiance-kernels`.

The first standard fused link failed exactly at:

```text
riscv64-unknown-elf-gcc: fatal error: cannot read spec file 'htif_nano.specs'
```

Building pinned libgloss locally supplied the missing link collateral without
changing Chipyard source. The first runtime-library compile also exposed that
`lib/Makefile` did not add the released Muon compiler's bundled libc++ include
directory: the RV32 compile selected the RV64 GCC `type_traits` and then failed
on `bits/c++config.h`. Supplying
`-isystem /scratch/trazzaque/radiance-kernels/llvm/llvm-muon/include/c++/v1`
in `LLVM_CFLAGS` fixed the runtime build; the STREAM and Spatter Makefiles
already add that same intended include directory.

No full-SoC simulator or FPGA was run by this workload audit, so compilation,
static ELF checks, and software oracles do not establish target execution. The
software topology, poison, drained completion protocol, provenance, and all
timed/control pairs are prepared. Next run a passing full-output simulation on
Radiance `bd6c4b7` (or equivalent), first through a loader appropriate to the
target, then confirm the generated target's address-hash parameters before any
FPGA LoadMem run. `workload-elfs-two-sm.sha256` records the final 36 fused ELF
hashes; the earlier `workload-elfs.sha256` remains the unmodified one-SM
handoff audit and must not be used for two-SM measurements.
