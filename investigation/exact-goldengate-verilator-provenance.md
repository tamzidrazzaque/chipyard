# Exact Golden Gate and Verilator provenance

Audit date: 2026-10-21 PDT

This is a host-only provenance snapshot. It did not access SSH, Vivado, XDMA,
or an FPGA. Fresh post-fix Golden Gate and Verilator builds completed for both
HBM and DDR in an isolated build root; both `VFireSim` executables passed their
link/dependency audits. These are host-simulation artifacts, not bitstreams or
physical-FPGA deployment evidence.

The source identities are parent commit
`b0bb67a7cf4454b825e131277386bdcbf3cac403`, FireSim
`590ebc4e7e1061a7b96bb333b7c692701a791bac`, Gemmini
`b2320ba173263b740e2ee4c00f5e2e22a9129906`, and Radiance
`bd6c4b7af8fc90b939061862baa35c2f200899cd`. The working checkout also contains
an unrelated user modification to Gemmini's generated software-test header.
That file was not changed or staged by this investigation, but its presence
means this checkout must not be described as clean deployment provenance.

All fresh outputs are under:

```text
/scratch/trazzaque/firesim-host-builds/b0bb67a7cf4454b8-590ebc4e7e1061a7
```

The root was created with mode 0700 and separate staging, classpath, cache, and
generated-source trees. Existing canonical FireSim generated directories were
not reused or overwritten.

## Shared target input

The HBM and DDR output directories contain target FIR, annotation, and
dependency symlinks to the same fresh staging directory. Byte comparison of
each HBM/DDR pair passed.

| Input | SHA-256 |
| --- | --- |
| `firechip.chip.FireSim.FireSimE4M3MxGemminiTwoClusterHBMRadianceConfig.fir` | `e0dfe17302c65ae77b33be04a27cd5dcc0e96ddf8f9831ee3a4536165f3168ea` |
| `firechip.chip.FireSim.FireSimE4M3MxGemminiTwoClusterHBMRadianceConfig.anno.json` | `5d74fe915096616e84162a2616d5d688acbb9f454ffe1ea6a5eb5fd0cae99411` |

The common staging FIR path is:

```text
/scratch/trazzaque/firesim-host-builds/b0bb67a7cf4454b8-590ebc4e7e1061a7/staging/generated-src/firechip.chip.FireSim.FireSimE4M3MxGemminiTwoClusterHBMRadianceConfig/firechip.chip.FireSim.FireSimE4M3MxGemminiTwoClusterHBMRadianceConfig.sfc.fir
```

The freshly rebuilt FireChip and FireSim-main jars have SHA-256 values
`6b79d91673b02d116ac15e9ae5a2d6dfc72055699c63732633a2c8e057df0cfe`
and `106f80b6e4927712c9ef4371c6676b280d528fa19617f7db57b94267e73606d1`,
respectively.

## Fresh post-fix Golden Gate outputs

Golden Gate ran with `JAVA_TOOL_OPTIONS=-Xmx64G -Xss8M`. Both builds exited
zero after the five-bridge address map, the single 4 GiB host-memory backing
allocation, and FPNew package reordering.

| Artifact | HBM SHA-256 | DDR SHA-256 |
| --- | --- | --- |
| target FIR | `e0dfe17302c65ae77b33be04a27cd5dcc0e96ddf8f9831ee3a4536165f3168ea` | `e0dfe17302c65ae77b33be04a27cd5dcc0e96ddf8f9831ee3a4536165f3168ea` |
| target annotations | `5d74fe915096616e84162a2616d5d688acbb9f454ffe1ea6a5eb5fd0cae99411` | `5d74fe915096616e84162a2616d5d688acbb9f454ffe1ea6a5eb5fd0cae99411` |
| `FireSim-generated.sv` | `646b84c28d02dc5bb001de66f67f13de658d5b5dd9b62cea0d9d96f19a4df83e` | `eeadc277afb7000e4eb6b43db300021d87438fe24a472ecc1d941e9d8dbbccf4` |
| `FireSim-generated.defines.vh` | `d83752f6629f6f600728f83eb57627fa420047ce4767d8f839132f57f6cf7009` | `d83752f6629f6f600728f83eb57627fa420047ce4767d8f839132f57f6cf7009` |
| `FireSim-generated.const.h` | `0aef519a016689628f352d153a11d36659a08ef0a08923f7939c5ce0ce289ecf` | `aba73f208700dc7060bfa2dfd6055a404bbc94b7e2fd39939b4b8e5119cb8d60` |
| `FireSim-generated.synthesis.xdc` | `ae49751c4a82941dc61b0380511207e9c11bbb3b16c0493f2575ca4357bc969b` | `ae49751c4a82941dc61b0380511207e9c11bbb3b16c0493f2575ca4357bc969b` |
| `FireSim-generated.implementation.xdc` | `8f554f06fa2d9687c801f8ae06d0dfd4061dc9fa35965db826fa5441c6fe8c40` | `8f554f06fa2d9687c801f8ae06d0dfd4061dc9fa35965db826fa5441c6fe8c40` |
| `post-bridge-extraction.json` | `fd1d05e054c64d8d9de02dd1e63e660d58a7ddd583ad01bd2c9754d40a77777e` | `fd1d05e054c64d8d9de02dd1e63e660d58a7ddd583ad01bd2c9754d40a77777e` |

The completed logs are:

| Log | SHA-256 |
| --- | --- |
| `logs/hbm-goldengate.log` | `22ece17e9b748dccdc23dc5c1f7ff9900464a723c1125da637ec30c450cfd2d3` |
| `logs/ddr-goldengate.log` | `0d5ba8e0968f44d82d8bec0ba8084e2d09bd881324f1be9854083372120a80cb` |

Each result has FASED bridge register windows `[0x000,0x0ff]` through
`[0x400,0x4ff]`. All five bridges share one 4 GiB host backing allocation.
The target topology is one 32-bit host window and four 33-bit GPU windows; the
target clock is 1 GHz. HBM has 34 writable timing/model settings per bridge and
DDR has 28.

The generated HBM data contains exactly five models with 34 writable defaults
each; DDR contains five models with 28. Both have exactly five bridge windows
and one shared 4 GiB backing allocation. A width scan found a largest sized
literal of 16,383 bits and largest numeric packed range of 17,407 bits. It
found neither the old 262,159-bit mask-shift shape nor any object wider than
65,536 bits. Consequently the successful builds did not use a
`--max-num-width` override.

## Host FESVR dependency

Verilator 5.022 is installed in the pinned conda environment. The target
cross-toolchain prefix has no host FESVR/Spike libraries, so a clean no-Boost
host installation was built separately at:

```text
/scratch/trazzaque/tools/spike-host-9c190a07c683-noboost
```

It was built from the clean Chipyard Spike submodule at commit
`9c190a07c6838f6392bafa4ad83acea462c7f759`. `libfesvr.a` has SHA-256
`251b001beb6a387f306ee86e58dc69d013c452c30eea8ad069097c5b39d82867`,
`libriscv.so` has SHA-256
`e6c85d5a37d9e34eebb405c89f71aca6125d32ae0b1e0e18e7dad7290ea933ef`,
and the installed include tree has SHA-256
`a15648d7dcedaba7a061218a420fe65eddc4688493b31f33e98a752c79258a49`.
`ldd -r` reports no unresolved symbols and neither host library has a Boost
runtime dependency.

Use:

```bash
export FIRESIM_FESVR_PREFIX=/scratch/trazzaque/tools/spike-host-9c190a07c683-noboost
```

Do not repoint `RISCV`; it remains the target cross-toolchain. Nested FireSim
commit `590ebc4e7e1061a7b96bb333b7c692701a791bac` forwards the separate prefix
through bitbuilder and runtime-manager build commands. The target driver
makefrags require the same prefix and link both `libfesvr` and `libriscv`.

## Successful post-fix Verilator builds

The builds ran sequentially. Each used eight C++ compile jobs, `--assert`, its
own generated-directory include path, `-Wno-BLKANDNBLK`, and `-Wno-fatal`.
Neither used `--max-num-width`. Both selected the pinned FESVR headers and
linked `libfesvr` plus `libriscv` from the separate host prefix.

| Condition | `VFireSim` bytes | `VFireSim` SHA-256 | Build-log SHA-256 |
| --- | ---: | --- | --- |
| HBM | 3,585,305,056 | `519241cb84371a1013a55090cfa48eeec4aea919b18b3df4e10ea74a651bc353` | `ce32c9e35113c1aebe9552e7f16a117906c9e9b42fdc4568ede9413a9b40c83e` |
| DDR | 3,553,276,688 | `14591281c1aa1f8c1d98820d91e2d96e1b13d1fe4b19a6edb1228f6ae7f7b874` | `8976df3c83acb4d8566e3f7c6ba3ea90ccc47fa0b22812d36268755359942963` |

Both outputs are regular executable files, not symlinks. Their exact ELF
`RPATH` is
`/scratch/trazzaque/tools/spike-host-9c190a07c683-noboost/lib:/scratch/trazzaque/chipyard/.conda-env/lib`;
it has no empty component or `$ORIGIN`. `ldd -r` reports no missing library or
unresolved symbol for either executable. Strict build-log scans found no
compiler/link failure, no hidden width override, and no malformed RPATH token.

Each build kept 528 ordinary Verilator warnings visible. The identical warning
histogram is `ASCRANGE=109`, `GENUNNAMED=26`, `IMPORTSTAR=6`,
`PINCONNECTEMPTY=6`, `SYNCASYNCNET=1`, `UNOPTFLAT=18`, `UNSIGNED=2`,
`UNUSEDPARAM=25`, `WIDTHCONCAT=4`, `WIDTHEXPAND=267`, and `WIDTHTRUNC=64`.
An independent review traced the 18 `UNOPTFLAT` reports to the same packed
FPNew structures in both targets. The normalized reset/`UNOPTFLAT` signal set
also matches byte-for-byte, SHA-256
`faa237ea41aafdf6c9824b655b8cffd94d23c7e38d2fe96bcafe377d5cdeae1f`.
The warnings were not hidden; runtime still treats assertions or convergence
failure as fatal.

## Historical failed HBM Verilator stages

These superseded attempts explain the final build controls. None is recorded
as success.

| Stage | Log and SHA-256 | Exact stopping condition |
| --- | --- | --- |
| Default environment | `hbm-verilator.log` — `6f45ce17a9045d1fe3bce409aa456c185256b9f9f3748f7f68c6fb44dfcbfb7f` | Missing `$RISCV/lib/libfesvr.a`; the build stopped before Verilator. |
| Separate FESVR prefix | `hbm-verilator-fesvr.log` — `d653adb583895c7ad511723f0e20b6b370ab38874cd4f6ecf7e313203f69cfb5` | Missing generated-directory include path for `registers.svh`, plus Verilator's default numeric-width limit rejected `262143'd0`. |
| Include path and `--max-num-width 262159` | `hbm-verilator-width.log` — `f4d49aa181bc15bb22a0f98f34db7906735aa890771608b15eaf31af82804421` | Verilator stopped after 50 `BLKANDNBLK` errors in imported CVFPU/FPNew RTL. |
| Added `-Wno-BLKANDNBLK` | `hbm-verilator-blkandnblk.log` — `0d82c2acb6d83a423441efbc6c3a7649ebf10c8f99846dfdfc2ab2555496332c` | RTL elaboration emitted C++, then `-Wall` stopped on 528 warnings because warnings remained fatal. |
| Nonfatal warnings and source width fix | `hbm-verilator-widthfix.log` — `14440cede12722b5802c47a9b8322fbcb4c5f6d03c2d5e30a7884640d0a86f68` | All 1,584 generated C++ units compiled; final link failed on 14 unique Spike/cospike symbols because the old prefix lacked `libriscv`. |

The last historical attempt retained ordinary diagnostics with `-Wno-fatal`;
its failure was strictly a host-library link failure. The fresh builds above
use the complete no-Boost prefix and close that link failure.

The superseded generated RTL has only eight objects above Verilator's default
64K maximum: the 262159-bit mask-shift wires created by
`Controller.scala:208`, containing 262143-bit zero literals. The next-largest
object is 17,407 bits. Gemmini commit
`b2320ba173263b740e2ee4c00f5e2e22a9129906` fixes that source width. The fresh
scan and successful no-override builds above confirm the correction.

## FASED output contract for the smoke

FireSim commit `590ebc4e7e1061a7b96bb333b7c692701a791bac` makes every optional histogram
and range filename model-indexed, avoids placeholder files when the feature is
absent, and appends a final memory-statistics row at bridge shutdown. The exact
HBM and DDR generated address maps expose neither histogram nor range-counter
registers. Consequently each completed smoke must produce exactly
`memory_stats0.csv` through `memory_stats4.csv`, each with at least one data
row, and no histogram/range files.

The three expanded profiles were checked byte-for-byte against the
manager-visible copies pinned by that FireSim commit. Their hashes
are:

| Profile | Arguments | SHA-256 |
| --- | ---: | --- |
| HBM2-2400 | 170 (34 x 5) | `372af4e4a05a168bcdcc37dd853f6dbf3849b6c3585fc595b31522290f852cf8` |
| HBM2-2000 | 170 (34 x 5) | `2d45764907b723a66dc30a4547f9ed10d122a9da8132e5380febac76f80fd5ab` |
| DDR3-2133 | 140 (28 x 5) | `dc133659c8f8e4a8cfd14e6779a373bbcb005cc7143507320d1edf5e1014fc6a` |

## Completion status and physical boundary

The fresh HBM and DDR Golden Gate builds, width scan, sequential Verilator
builds, ELF dependency checks, and strict build-log scans all pass. HBM2-2400,
HBM2-2000, and DDR3-2133 then passed sequential host metasims with the pinned
hashed ELF. Their exact UART, realized-profile, console, and five-CSV evidence
is recorded in [`metasim-flow-audit.md`](metasim-flow-audit.md) and bound by
`host-only-validation.sha256`.

This closes the host-build and correctness-smoke criteria only. No Vivado run,
20 MHz TIMING bitstream archive, packaged hardware driver, SSH session, XDMA
access, or FPGA programming occurred. The fail-closed physical deployment
blockers in `xb10-runtime-deployment.md` remain in force.
