# Five-bridge FASED runtime-config audit

Scope: the exact target
`FireSimE4M3MxGemminiTwoClusterHBMRadianceConfig` with platform
`HBM2FRFCFS16GBDualPC_BaseCorigineXB10Config`; the companion
`FRFCFS8GBQuadRank_BaseCorigineXB10Config` was also checked for the DDR deploy
profile. No FPGA was accessed.

## Finding

The target annotation JSON contains five `midas.models.FASEDMemoryTimingModel`
bridges with contiguous IDs 0 through 4. All have a 64-bit AXI data interface.
The address map associates bridge 0 with the host region and bridges 1 through
4 with the four 512 MiB GPU regions:

| FASED ID | Base | Mask |
| --- | ---: | ---: |
| 0 | `0x80000000` | `0x7fffffff` |
| 1 | `0x100000000` | `0x1fffffff` |
| 2 | `0x120000000` | `0x1fffffff` |
| 3 | `0x140000000` | `0x1fffffff` |
| 4 | `0x160000000` | `0x1fffffff` |

The checked-in HBM runtime configs are deliberately unsuffixed, for example
`+mm_hbmTimings_tCAS=17`. They are not directly valid driver configurations:

- `RuntimeConfigGenerationPhase.scala` collects all FASED bridges but calls
  `getSettings` on only `headOption`.
- `FASEDMemoryTimingModel.settingsToString` emits
  `+mm_<register>_<widget-id>=<value>`.
- The C++ FASED driver accepts an argument for model N only if it contains
  suffix `_<N>`; an unsuffixed setting is skipped by every model. Current
  initialization then rejects an empty or incomplete explicit configuration
  unless the operator supplies the separate hardware-default opt-in.
- The manager copies a custom runtime config verbatim into the simulator
  command. It does not add model indices.

The built-in generator is also broken earlier in this tree: a direct invocation
on an already completed HBM fuzzer's `post-bridge-extraction.json` instantiated
its bridges, then failed in `PlatformShim`/`SpecifyXDCCircuitPaths` with
`IllegalArgumentException: must be inside Builder context` and emitted no
runtime config. Even if that Chisel-context failure is repaired, the
`headOption` logic still leaves four exact-target models unconfigured.

The first exact-target Golden Gate validation attempt used a 16 GiB Java heap
and exhausted it during `EmitFirrtl`. It produced no driver header (only a
zero-byte `post-split-expressions.fir`), so that attempt is not register-map
evidence. The identical HBM generation was restarted with a 64 GiB heap and
completed with exit status zero, as did the exact DDR generation. Their final
driver headers, not the failed attempt's partial output, were used below.

Consequently, a complete explicit configuration for this target needs 34
settings for each of `_0`, `_1`, `_2`, `_3`, and `_4`: 170 plusargs. The
unsuffixed OP/REFab file happens to equal the compiled HBM defaults, but the
hardened driver no longer permits that coincidence to look successful: raw
unsuffixed OP/REFab, closed-page, and REFSB profiles fail during initialization.

The exact platform uses five independent, single-channel HBM model instances.
Do not use the `*-4ch-radiance.conf` file: it includes `chAddr` registers that
exist only in the quad-channel HBM model and the exact driver's strict register
check will reject them.

The current post-fix Golden Gate rebuild under
`/scratch/trazzaque/firesim-host-builds/b0bb67a7cf4454b8-590ebc4e7e1061a7`
reconfirmed the exact generated HBM header SHA-256
`0aef519a016689628f352d153a11d36659a08ef0a08923f7939c5ce0ce289ecf`.
It contains exactly five FASED constructors with IDs 0 through 4, writable-map
sizes of 34 each, and `memory_stats0.csv` through `memory_stats4.csv`. Every
writable set exactly equals every per-model key set in both actual 170-line
HBM profiles. The same fresh build reconfirmed the exact DDR header SHA-256
`aba73f208700dc7060bfa2dfd6055a404bbc94b7e2fd39939b4b8e5119cb8d60`;
it likewise has IDs 0 through 4 and distinct statistics files, with 28
writable keys per model exactly matching the actual 140-line DDR profile.

## Fresh host runtime realization

The post-fix simulators ran all three profiles sequentially with the pinned
hashed two-SM ELF. Each console command line contained every canonical profile
argument exactly once. Each driver then emitted exactly one acceptance
diagnostic for models 0 through 4, with the expected setting count and
`hardware defaults disabled`.

| Profile | Arguments | Settings/model | Pass cycle | Terminal statistics |
| --- | ---: | ---: | ---: | --- |
| HBM2-2400 | 170 | 34 | 395266 | five indexed files |
| HBM2-2000 | 170 | 34 | 392194 | five indexed files |
| DDR3-2133 | 140 | 28 | 386050 | five indexed files |

Every statistics file contains its header, initial row, and shutdown row. No
latency-histogram or range-counter file exists, matching the exact generated
register maps. The UART parser accepted four ordered mailbox reports and the
canonical pass for every run. Full per-core values and hashes are in
`metasim-flow-audit.md`; these are host correctness/configuration smokes, not
physical-XB10 performance measurements.

## Safe expansion

`expand_fased_runtime_config.py` validates an unsuffixed config, derives and
checks contiguous FASED IDs from target annotations, and writes the expanded
config to standard output. For the exact target, run from `chipyard/`:

```sh
python3 investigation/expand_fased_runtime_config.py \
  sims/firesim/sim/custom-runtime-configs/hbm2-FRFCFS-2400-OP-REFab.conf \
  --annotations sims/firesim/sim/generated-src/corigine_xb10/corigine_xb10-firesim-FireSim-FireSimE4M3MxGemminiTwoClusterHBMRadianceConfig-HBM2FRFCFS16GBDualPC_BaseCorigineXB10Config/firechip.chip.FireSim.FireSimE4M3MxGemminiTwoClusterHBMRadianceConfig.anno.json \
  > sims/firesim/sim/custom-runtime-configs/hbm2-FRFCFS-2400-OP-REFab-5bridge.conf
```

The original integration also concatenated `../sim/custom-runtime-configs` and
the YAML value without inserting `/`, so the documented bare filename resolved
incorrectly. FireSim commit
`590ebc4e7e1061a7b96bb333b7c692701a791bac` includes the tested path join,
invocation-independent resolution, byte-identical manager-visible profiles,
strict parser, and content-hash/path tests. Reference only
the bare filename, for example
`hbm2-FRFCFS-2400-OP-REFab-5bridge.conf`, in `custom_runtime_config` (or
`metasim_customruntimeconfig`); do not use an absolute path, a symlink, or
directory traversal. Inspect the resulting driver bundle to prove that the
file is present. Preserve the expanded file with the run artifacts and hash
it.

## Tests and limits

- Six Python unit tests cover exact expansion, comments/blanks, duplicate and
  pre-indexed rejection, malformed/out-of-uint32-range values, the full uint32
  endpoint, annotation ID sorting, and noncontiguous-ID rejection.
- Twelve runtime/profile tests prove the HBM and DDR timing sources, exact
  annotation-derived expansion, and five complete per-model maps; two more
  tests prove the exact target's widths, address map, and 1 GHz clock.
- Strict exact-header checks proved five constructors, five distinct statistics
  files, and per-model writable-set equality for both HBM profiles and the DDR
  profile. They also reject duplicate IDs, duplicate keys, missing/extra keys,
  or a profile line that cannot be parsed.
- Focused manager tests prove `None`, documented relative, and legacy
  leading-slash path handling, then resolve and hash-check all three deployed
  bare filenames from the manager's intended directory. The complete FireSim
  deploy pytest suite passes 130 tests (with only Paramiko's known Blowfish
  deprecation warning).
- The host-only runtime validator passes all build-pair, workload, LoadMem,
  five-ID profile, topology, and campaign checks. It reports only the expected
  pre-deployment blockers for the two final simulator/driver bundles and the
  coordinated one-entry FPGA database; manager-visible profile copies are no
  longer blockers.
- The deployed HBM 2400, HBM 2000, and DDR files have SHA-256 values
  `372af4e4a05a168bcdcc37dd853f6dbf3849b6c3585fc595b31522290f852cf8`,
  `2d45764907b723a66dc30a4547f9ed10d122a9da8132e5380febac76f80fd5ab`,
  and `dc133659c8f8e4a8cfd14e6779a373bbcb005cc7143507320d1edf5e1014fc6a`,
  respectively; `cmp` proved they are byte-identical to the canonical outputs.
- `transactionQueueDepth` is a writable register, but the HBM scheduler is
  constructed with the elaboration-time `cfg.transactionQueueDepth`; changing
  the runtime field does not resize or control that scheduler. Keep it at 8
  and do not interpret it as an independently swept parameter.
