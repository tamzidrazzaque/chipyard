# HBM2 versus DDR3 fixed-work diagnostic (host Verilator, 2026-10-21)

This is a memory-model diagnostic, **not an FPGA or native STREAM result**.
The checked-in two-SM target has five 64-bit AXI4 FASED bridges: one host
region and four independently hashed GPU regions. Its DDR platform config
instantiates a separate DDR3 FR-FCFS model on every bridge, just as the HBM
config instantiates a separate HBM2 model on every bridge. Thus a same-target
HBM/DDR run compares equal counts of independent 8-byte/tick model ingress
ports; it does not compare a 4-channel HBM stack against a 1-channel DDR
device. The exact target widths are in `fixtures/exact-target-architecture.json`.
The controlled pair holds the Radiance four-by-64 KiB GPU split-L2 topology
constant. Nicolas's historical shared-512 KiB DDR target is a different
cache design, so its reported slowdown cannot be attributed to DRAM timing
alone without reproducing that target.

## Controlled fixed-work result

`FixedReadProbe1M` and `FixedReadProbe4` issue the same 32,768 sequential
32-byte reads (1,048,576 bytes). The former drives one 64-bit AXI port; the
latter distributes 8,192 reads to each of four independent ports. Addresses
and request count do not change with response scheduling. Each bridge's
statistics independently confirms the expected reads and four 8-byte beats
per read, zero writes, and zero AXI response errors. The probe checks the
four-beat RLAST sequence per ID; it does **not** check returned data values.
The HBM and DDR variants have identical target FIR hashes within each port
count. Three independent runs per condition returned identical target cycles.

| Model / port count | Target cycles | Effective GB/s at 1 GHz | Versus matching-port DDR |
|---|---:|---:|---:|
| DDR3-2133 / 1 | 142,897 | 7.338 | baseline |
| HBM2-2000 / 1 | 145,354 | 7.214 | 1.719% more cycles |
| HBM2-2400 converted to 1 GHz / 1 | 145,528 | 7.205 | 1.841% more cycles |
| DDR3-2133 / 4 | 35,696 | 29.375 | baseline |
| HBM2-2000 / 4 | 36,331 | 28.862 | 1.779% more cycles |
| HBM2-2400 converted to 1 GHz / 4 | 36,369 | 28.832 | 1.885% more cycles |

A refresh-only isolation run reused the same 1 MiB read workload and binaries
but set `tREFI=30,000` for **both** models. That setting violates their normal
refresh requirements and is a causal diagnostic, not a candidate deployment
profile. Three repeats each gave DDR 141,358 cycles (1.077% below its valid
baseline) and HBM2-2000 132,727 cycles (8.687% below its valid baseline).
Under this nonphysical suppression HBM was 6.106% faster than DDR at one port.
Thus the valid-profile equal-port deficit is driven substantially by refresh,
not by an inability of the HBM backend to fill the port.

On the sequential request order, the valid HBM2-2000 REFSB variant performs
**worse**: 246,343 one-port cycles and 58,951 four-port cycles, repeated
exactly three times.
The one-port slowdown is 69.478% versus HBM REFab. The trace contains 2,018
REFSB commands versus 74 REFab commands in the respective runs. Source audit
found a specific scheduler mistake: `pcWantsRef` currently blocks all CAS and
ACT on a pseudo-channel while *one bank* awaits REFSB; the intended REFSB
semantics are bank-local. A bank-local gate edit preserves exact REFab timing
and reduces REFSB by only 15 cycles (0.0061%) at one port and 13 cycles
(0.0221%) at four ports, each in three repeated runs. It fixes the semantic
overblocking but **does not explain the 69% REFSB slowdown**. A likely
remaining cause is head-of-line blocking: sequential addresses spend 32
requests on one bank while the FASED scheduler window holds only eight, so
it cannot look ahead to a different bank during that bank's tRFCSB window.
To test that hypothesis, `FixedReadProbeInterleaved1M` permutes only the
request order, preserving exactly the same 32,768 addresses and 1 MiB of
reads. Each group of 16 requests visits all 16 HBM banks. The address-set
permutation has a separate exhaustive unit test. Three host-Verilator repeats
per condition gave:

| One-port, bank-interleaved order | Target cycles | GB/s at 1 GHz | Versus DDR |
|---|---:|---:|---:|
| DDR3-2133 | 142,897 | 7.338 | baseline |
| HBM2-2000 REFab | 145,465 | 7.209 | 1.797% more cycles |
| HBM2-2000 REFSB | 131,299 | 7.986 | **8.116% fewer cycles** |

DDR's cycle count is *identical* to its sequential-address run. On the same
interleaved HBM requests, REFSB takes 9.738% fewer cycles than REFab. The
valid REFSB model is therefore faster for a bank-parallel stream, while the
sequential stream is pathologically slow under the same policy. This strongly
supports the bank head-of-line explanation, though a direct scheduler-stall
counter would be needed to quantify its contribution precisely. The
interleaved HBM REFSB trace contains 36,915 commands, including 32,768 reads
and 1,074 REFpb commands; independent pinned Ramulator replay using its
HBM2-2000/HBM2-8Gb model reports **zero timing/state violations**. Trace and
check output are in `investigation/hbm-interleaved-legality-20261021`.
The HBM REFSB run delivers 99.827% of the one-port 8-byte/tick bridge
ceiling, so this target interface leaves very little room for a faster memory
device to improve equal-port throughput further.
The absolute transfer floor is 131,072 cycles on one port (1 MiB / 8 bytes
per tick); interleaved HBM is only 227 cycles above it, while interleaved
DDR is 11,825 cycles above it. On four ports the floor is 32,768 cycles,
and HBM REFSB is only 195 cycles above it.
The sequential one-port REFSB trace also passes independent HBM2-2000
Ramulator replay: 36,819 commands and zero violations. Its 2,018 REFpb
commands versus 1,074 in the faster interleaved run reflect the extra elapsed
time's refresh demand. It has 993 intervals longer than four cycles between
successive reads (maximum gap 120 cycles), versus 84 such intervals for the
interleaved run (maximum 94). Interleaving is faster **despite** more ACTs
(1,547 versus 1,024), which further points to refresh blocking, not simply
better row locality.

The matching four-port interleaved run also repeated exactly three times:
DDR3-2133 took 35,697 cycles, HBM2-2000 REFab 36,351 cycles, and HBM2-2000
REFSB 32,963 cycles. Thus HBM REFSB used **7.659% fewer cycles than DDR**
at equal port count and 9.320% fewer cycles than HBM REFab. The four-port DDR
control moved by only one cycle versus its sequential-address run. All four
bridge statistics in every repeat show 8,192 reads, 32,768 beats, and zero
AXI response errors. These four FASED bridges print commands without unique
channel labels, so their merged console log **cannot** be replayed as one
Ramulator device; such an attempt creates spurious apparent violations. The
trace parser now rejects this ambiguous case. The independently checked
one-port trace is the direct command-legality evidence for this runtime
profile, while the four-port result is a throughput/correctness control.
Effective aggregate throughput is 31.811 GB/s for four-port HBM REFSB versus
29.374 GB/s for four-port DDR at the modeled 1 GHz target clock.

Four-port HBM2-2000 is **3.933x faster / 74.575% fewer target cycles** than
one-port DDR3. Four-port HBM2-2400 at the target clock is **3.929x faster /
74.549% fewer cycles** than one-port DDR3. This is the channel-count
advantage, not proof that an individual HBM channel is faster. Four-port DDR
scales 4.003x and four-port HBM2-2000 scales 4.001x. In the sequential
REFab pair, each port achieves about 7.2–7.3 bytes per target tick against
an 8-byte/tick AXI ceiling; bank-interleaved REFSB reaches 7.986 bytes/tick.
Simply speeding up memory
timings cannot produce a large equal-port throughput win on this stream. A
true 1.2 GHz HBM2 controller would need a multirate/fractional-clock timing
model, while an HBM4-style channel-count advantage needs enough target ports
or port width to deliver it; replacing the HBM2 timing constants alone does
not solve either limitation.

Reproduction: `run_fixed_read_aggregate.sh` and
`validate_fixed_read_aggregate.py` (also passes with `python3 -O`); exact
logs and bridge statistics are in
`/scratch/trazzaque/firesim-host-builds/fixed-read-probe/aggregate-*`.

## Backend-capacity correction

The original HBM backend admitted four simultaneous read completions. With
the raw HBM2-2400 tCAS=17 plus two backend cycles, four 32-byte requests per
19 ticks cap the backend at 6.74 bytes/tick, below the 8-byte AXI ingress.
The new eight-entry default removes that artificial cap. In a fixed 8,192-read
probe using the clock-aligned HBM2-2000 profile, legacy four-entry backend
took 38,488 cycles; the default and explicit eight-entry variants both took
36,331 cycles (**5.605% fewer cycles** than legacy). They have identical
target FIRs, all 8,192 reads and 32,768 beats complete, and no AXI errors.
The default-eight and explicit-eight generated Verilog hashes also match.
`run_fixed_read_postfix.sh` reproduces this A/B. This change has not yet been
measured in a two-SM FPGA bitstream or a native STREAM run.
The corrected FireSim source is local commit `d86ece4a7`.

After the default changed, the full directed HBM2 suite passed six host
Verilator workloads (REFab, REFSB, closed-page, row-hit, row-conflict, and
pointer chase). Their 13,297 extracted commands replayed against pinned
Ramulator HBM2-2400/HBM2-8Gb with zero timing violations in all six traces.
The suite's raw logs and CSVs are under
`investigation/hbm-validation-post-backend8-20261021`. This checks command
legality for the original raw-2400 timing profile, not the approximate
1 GHz converted profile.
After the separate bank-local REFSB gate edit, the entire six-workload suite
was rerun from rebuilt Verilator binaries. All six workloads passed; 13,285
commands replayed against pinned Ramulator HBM2-2400/HBM2-8Gb with **zero
violations**, including 3,648 REFpb commands in the directed REFSB case.
Those logs and traces are in
`investigation/hbm-validation-post-bankgate-20261021`.
`HBMModelSpec` also passed all five Scala tests after this edit. The bank-local
gate, interleaved probes, and fail-closed trace parser are pinned in local
FireSim commit `b450657c0` (following backend-capacity commit `d86ece4a7`).

## Timing timebase

The raw HBM2-2400 table is expressed in 1.2 GHz CK counts, but this target's
FASED model advances at 1 GHz. The diagnostic
`runtime-configs/hbm2-FRFCFS-2400-1GHz-OP-REFab.source.conf` conservatively
converts minimum timings with `ceil(raw_count * 5 / 6)`, and caps the maximum
tREFI at 3900 target ticks. A generated five-bridge expansion accompanies it.
This is an integer-tick approximation, **not** an HBM4 profile or an exact
multirate HBM2 controller. Unit tests verify every converted setting and the
five-bridge expansion. Every converted minimum timing is equal to or greater
than the HBM2-2000 value at this coarse 1 GHz tick; this approximation cannot
represent the 2400 grade's fractional-cycle performance advantage. In the
8,192-read probe, raw-2400 took 36,181 cycles
but the corrected profile took 36,367. The latter issues 18 refresh commands
versus 14 under the artificially stretched raw tREFI, explaining why shorter
minimum delays alone do not guarantee a lower total.

The attached HBM4 specification describes up to 32 channels per stack and
two pseudo-channels per channel, with a different BL8/256-bit prefetch
organization. Those facts motivate future channel/topology design; its
timings were not imported into this HBM2 comparison. The meeting transcript's
expectation that HBM should win is a hypothesis, not a measured guarantee.

## Limits and next gate

These data are host-Verilator target cycles from an isolated read-only model
probe. The DDR comparator is a DDR3-2133 FASED configuration, not verified as
Nicolas's original DRAM model. Both model variants use identical generated
target FIR per port count, but these probes do not exercise the Radiance GPU
cache hierarchy, writes, native STREAM sizes, or physical FPGA clocks.
The four-port DDR diagnostic is useful for isolating channel count, but it
also demonstrates why instantiating one DDR model per GPU-region port is an
unrealistic *single-channel DDR* baseline. No FPGA has been used for these
results. Promote to FPGA only after source/provenance and end-to-end
correctness checks, matching HBM/DDR builds, and an explicitly available
shared card are established.
