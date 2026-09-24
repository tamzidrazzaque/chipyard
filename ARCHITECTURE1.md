# Architecture 1: Radiance + multi-channel HBM

This is the **canonical** Chipyard branch for the current Radiance ↔ FASED HBM
integration (**Architecture 1**). Start here; the Radiance, FireSim, and
Rocket Chip commits are pinned as submodules.

| Component | Fork / branch | Pinned SHA |
|---|---|---|
| This repo | `tamzidrazzaque/chipyard` `hbm-arch1-512b` | (this commit) |
| Radiance | `tamzidrazzaque/radiance` `split-l2-512b` | `1356a02` |
| FireSim | `tamzidrazzaque/firesim` `hbm-arch1-512b` | `1b49ab0e7` |
| Rocket Chip | `tamzidrazzaque/rocket-chip` `hbm-512b-stripe` | `e2cbfb4` |

```bash
git clone --recursive -b hbm-arch1-512b \
  https://github.com/tamzidrazzaque/chipyard.git
```

## What this branch is

```
single Radiance cluster (MemPerf / SM path)
  -> coalescer / L0d / L1
  -> 4 L2 slices
  -> 512 B 4-way path select  (addr[10:9], BankBinder + AXI mask 0x600)
  -> 4 AXI memory ports
  -> 4 FASED bridges
  -> 4 independently timed 1-channel HBM models
     (one logical HBM; shared functional DRAM via MainMemory_0)
```

- **PARE is not integrated.** The HBM model still does transaction and command
  scheduling. A future MC would sit between L2/AXI and the HBM device model.
- Do **not** pair this target with `WithHBMQuadChannel`. Each AXI port already
  gets its own 1-channel `HBMModel`; the aggregate multi-channel frontend would
  re-serialize the four paths.
- Experimental branches (`hbm-arch1-experiments`, `hbm-arch1-compact-test`,
  32 B stripe configs) are **not** this packaging. Use them only for banking /
  locality experiments.

## Validated end-to-end config

**Target:** `FireSimRadianceMemPerf4PathConfig`  
**Platform:** `WithHBMRequestTrace_HBM2FRFCFS16GBDualPC_BaseF2Config`  
**Runtime registers:** `sims/firesim/sim/custom-runtime-configs/hbm2-FRFCFS-2400-OP-REFab.conf`  
(replicated onto FASED widgets `_0` … `_3`)

Longer MemPerf run (8M driver cycles): 262,184 requests, 0 routing mismatches,
0 Ramulator violations. See `HBM_RADIANCE_INTEGRATION_REPORT.md` for earlier
single-channel history; Architecture 1 numbers live with the working trees /
`hbm-arch1-out/presentation/` artifacts on the development machine.

## Build / run (FireSim Verilator metasim)

After `source env.sh` (or your site's Chipyard/FireSim env) and the usual
tooling (`RISCV`, firtool, Verilator):

```bash
cd sims/firesim/sim

make TARGET_PROJECT_MAKEFRAG=../../../generators/firechip/chip/src/main/makefrag/firesim \
  TARGET_CONFIG=FireSimRadianceMemPerf4PathConfig \
  PLATFORM_CONFIG_PACKAGE=firesim.configs \
  PLATFORM_CONFIG=WithHBMRequestTrace_HBM2FRFCFS16GBDualPC_BaseF2Config \
  verilator

GEN=generated-src/f2/f2-midasexamples-FireSim-FireSimRadianceMemPerf4PathConfig-WithHBMRequestTrace_HBM2FRFCFS16GBDualPC_BaseF2Config
CONF=custom-runtime-configs/hbm2-FRFCFS-2400-OP-REFab.conf

# Expand the single-channel conf onto four FASED instances:
ARGS=$(python3 - <<'PY'
from pathlib import Path
lines = [l.strip() for l in Path("custom-runtime-configs/hbm2-FRFCFS-2400-OP-REFab.conf").read_text().splitlines()
         if l.strip() and not l.startswith("#")]
print(" ".join(f"{k}_{i}={v}" for i in range(4) for k,v in (l.split("=",1) for l in lines)))
PY
)

cd "$GEN"
./VFireSim +permissive $ARGS +fesvr-step-size=128 +max-cycles=4000000 +permissive-off none
```

Parse / check traces from `sims/firesim/sim`:

```bash
scripts/hbm-validation/parse_hbm_req_trace.py <run.log> -o reqs.csv
scripts/hbm-validation/check_channel_routing.py reqs.csv --offset 9 --mask 3
scripts/hbm-validation/parse_fased_trace.py <run.log> -o cmds.csv
scripts/hbm-validation/check_trace_ramulator.py cmds.csv --ramulator $RAMULATOR2_DIR
```

Path id is `addr[10:9]` (`--offset 9 --mask 3`).

## Editing one component

Checkout the submodule branch above, commit there, then bump the pin in this
Chipyard repo (`git add generators/radiance` / `sims/firesim` /
`generators/rocket-chip` and commit). Keep `.gitmodules` URLs pointing at the
`tamzidrazzaque/*` forks that hold these branches.
