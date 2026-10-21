# FireSim/Radiance HBM performance investigation

This directory records reproducible inputs and evidence for the two-SM HBM
investigation on `harp.Millennium.Berkeley.EDU`. Historical numbers and shared
archives are reference data, not new measurements.

## Safety gate

- The host has eight shared `xcvu19p` FPGAs.
- Other users are logged in and the cards were reprogrammed recently.
- Process and device-handle checks cannot prove that another account has not
  reserved a card because this account cannot inspect every `/proc/<pid>/fd`.
- Do not program a card or launch a FireSim driver until an owner/slot is
  explicitly coordinated. Stop after a control timeout or an all-ones read.

## Original and current source baselines

- Chipyard: `ucb-bar/chipyard` `graphics` at
  `30d64bf63d637c049b6661cb64efd3cdb939d093`.
- Radiance gitlink: `dd1a74f1f818514c5fc9657060aaec684c827e15`.
- Gemmini gitlink: `7c02748dca60c73e3434ed9627744a771aa42155`.
- FireSim gitlink: `b084672c2f8cf32e55d78f73a001074c23f8a2b8`.

Those bullets record the original `graphics` baseline. The active investigation
tree now pins Radiance `bd6c4b7af8fc90b939061862baa35c2f200899cd`, Gemmini
`b2320ba173263b740e2ee4c00f5e2e22a9129906`, and FireSim
`590ebc4e7e1061a7b96bb333b7c692701a791bac`. The FireSim commit combines the
XB10 and timed-HBM lines, strict five-bridge runtime configuration, content-
addressed artifact/profile checks, shared-host card isolation, and host-build
tests. The Gemmini commit removes the oversized shift width that invalidated
the earlier generated RTL. Fresh isolated Golden Gate and Verilator artifacts
have now been regenerated from these gitlinks and passed the host-only audits
in `exact-goldengate-verilator-provenance.md` and `metasim-flow-audit.md`.
No Vivado build, bitstream, driver bundle, or physical-FPGA result exists from
that host validation; those deployment artifacts remain blocked.
The live checkout also carries an unrelated user modification to Gemmini's
generated software-test header. It was preserved and excluded from this work,
so the checkout is intentionally not claimed as clean ready-mode provenance.

## Configuration facts established from source

- Radiance uses cluster = CU/SM. `RadianceE4M3MxGemminiSingleClusterConfig`
  therefore instantiates one SM containing two Muon cores.
- `RadianceE4M3MxGemminiTwoClusterConfig` instantiates two SMs with two Muon
  cores each: four Muon cores total. Existing shared archives labeled
  `1sm`/`2sm` follow this cluster/SM count.
- The ordinary target has one memory channel behind a shared 512 KiB L2.
- `WithRadianceHBM` changes the topology to one 256 KiB host L2 slice plus four
  64 KiB GPU L2 slices, five region AXI ports total, and hashes GPU cache lines
  across the four GPU regions. This is not a controlled memory-model-only pair.
- In the composed FireSim target, `WithFireSimConfigTweaks` overrides the
  Radiance base settings and drives MBUS, including every Radiance region port,
  at 1 GHz. The current HBM2-2400 timing table is expressed in 0.833 ns HBM CK
  counts, so consuming those counts on a 1 ns model tick stretches modeled time
  by about 1.20x. Generated clock annotations must confirm this before use.
- `WithEdgeDataBits(64)` implies 8-byte external-memory beats in the source
  configuration; generated AXI must be inspected before treating that as final.

## Measurement rules

- First establish a clean two-SM target and generate both a timed-DDR and HBM
  platform from identical target RTL. Label ideal latency-pipe runs separately.
- Preserve commits, submodule SHAs, generated parameter/RTL hashes, bitstream and
  driver hashes, complete bridge-indexed `+mm_*` settings, timing reports, raw
  logs, workload hashes, correctness output, target cycles, bytes, and repeats.
- Use native STREAM Copy/Scale/Add/Triad and Spatter 0-4 for the final baseline.
- Do not import JESD270-4A/HBM4 timing values into the HBM2 model. The document is
  useful for methodology and traffic-pattern design only.

## Fresh host-only validation

Fresh isolated Golden Gate and Verilator builds completed for the controlled
HBM and DDR platforms. HBM2-2400, HBM2-2000, and DDR3-2133 then passed
sequential two-SM STREAM Copy correctness smokes with the same pinned hashed
ELF. The canonical pass cycles were 395266, 392194, and 386050; kernel cycles
were 13670, 12682, and 11538, respectively. All four cores reported completion,
all five FASED models accepted their complete explicit profiles with hardware
defaults disabled, and every run produced five valid terminal statistics
files.

These values prove target/profile realization and the correctness path only.
The workload is intentionally tiny, and host Verilator wall time is not XB10
performance. Exact source identities, build/output hashes, per-core UART
evidence, and CSV hashes are recorded in
`exact-goldengate-verilator-provenance.md`, `metasim-flow-audit.md`, and
`host-only-validation.sha256`.

The host-only XB10 deployment schema, exact hashed-ELF LoadMem path, fail-closed
single-slot templates, and nine-case campaign contract are recorded in
`xb10-runtime-deployment.md`. Run `validate_xb10_runtime_configs.py` before
using any filled copy; template mode intentionally reports missing artifacts,
manager-visible profiles, and coordinated slot selection as blockers.

## Shared archive caveat

The shared XB10 archives report FireSim base commit
`37f18a6329e26775a85ffec4e59b5ceb6cdeafbe-dirty`. The dirty changes are not
captured, so these archives can be used only for coordinated smoke tests and
closest-available reproduction, not as the final controlled pair.
