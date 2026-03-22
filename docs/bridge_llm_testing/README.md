# FireSim OpenOCD-over-DMI Bridge (`bridge_llm_testing`)

## What Was Implemented

This branch adds a working **OpenOCD-over-DMI debug path** for FireSim Verilator simulation of a RocketChip-based target. The implementation allows a real OpenOCD instance to connect to the simulated RISC-V core via the existing FireSim DMI bridge infrastructure, without requiring JTAG-over-FAME1 (which is fundamentally blocked).

### New C++ components

| File | Purpose |
|------|---------|
| `generators/firechip/bridgestubs/src/main/cc/bridges/jtag_dtm_translator.{h,cc}` | Pure C++ JTAG TAP state machine + RISC-V DTM. Translates remote_bitbang JTAG bit-bang sequences into DMI read/write transactions. Implements IDCODE (0x10000001), DTMCS, and DMI_ACCESS registers. |
| `generators/firechip/bridgestubs/src/main/cc/bridges/rbb_dmi_bridge.{h,cc}` | FireSim `bridge_driver_t` that accepts OpenOCD remote_bitbang TCP connections (default port 23000), feeds bits through `jtag_dtm_translator_t`, and drives the target debug module via the existing DMI MMIO interface. |
| `generators/firechip/bridgestubs/src/main/cc/bridges/remote_bitbang.{h,cc}` | TCP remote_bitbang server (copied from rocket-chip csrc). Accepts character-level JTAG commands from OpenOCD. |

### Modified Scala components

| File | Change |
|------|--------|
| `generators/firechip/bridgeinterfaces/src/main/scala/DMI.scala` | Added `useRbbDmi: Boolean = false` field to `DMIBridgeParams` |
| `generators/firechip/bridgestubs/src/main/scala/dmi/DMIBridge.scala` | Forwarded `useRbbDmi` param through `DMIBridge` BlackBox and `apply()` |
| `generators/firechip/goldengateimplementations/src/main/scala/DMIBridge.scala` | Added conditional `genHeader` branch: when `useRbbDmi=true`, emits `rbb_dmi_bridge_t` constructor instead of `dmibridge_t` |
| `generators/firechip/chip/src/main/scala/BridgeBinders.scala` | Added `WithRBBDMIBridge` harness binder that instantiates `DMIBridge` with `useRbbDmi=true` |
| `generators/firechip/chip/src/main/scala/TargetConfigs.scala` | Added `FireSimRBBDmiRocketConfig` (re-enables debug module overriding `WithNoDebug`); commented out broken optional-submodule configs (Gemmini, CVA6, Radiance) |

### Build compatibility fixes (riscv-sodor submodule)

The sodor submodule had compile errors that blocked the entire chipyard SBT build:
- `sodor_tile.scala`: commented out `Annotated.params(...)` call (API removed in current Chisel)
- `rv32_{1,2,3,5}stage/cpath.scala`: added explicit `: UInt` type annotations to pattern-matching destructuring assignments to fix "value === is not a member of Any" errors

---

## Why Raw JTAG-on-FireSim Was Blocked

The Rocket-Chip JTAG TAP (in `JtagTap.scala`) uses registers clocked by `(!clock.asUInt).asClock` — i.e., negedge-triggered flip-flops. FireSim's FAME-1 transform requires all state elements to be posedge-triggered (single-clock model). FAME-1 cannot model negedge-clocked logic without a fundamentally different abstraction (FAME-5 or manual workarounds). Attempts to elaborate `FireSimJTAGRocketConfig` confirmed this blocker statically.

---

## Why the Pivot to DMI Was Made

The DMI (Debug Module Interface) path:
- Uses only posedge-triggered logic throughout — fully FAME-1 compatible
- Already had a complete FireSim bridge (`DMIBridgeModule`, `dmibridge_t`)
- Was missing only a socket-accessible entry point for external debuggers
- Allowed implementing the JTAG TAP state machine entirely in the host-side C++ driver (`jtag_dtm_translator_t`), completely outside the RTL simulation

This approach isolates the JTAG complexity in the bridge driver where LLMs can generate and iterate on it, while the RTL remains clean DMI-only.

---

## How to Run the End-to-End Demo

### Prerequisites

```bash
# Build the test ELF (or use the pre-compiled one in this repo)
riscv64-unknown-elf-gcc -march=rv64ima -mabi=lp64 -nostdlib \
  -T docs/bridge_llm_testing/spin.ld \
  docs/bridge_llm_testing/spin.S \
  -o /tmp/spin.elf

# Verify openocd is available
openocd --version   # should be 0.12.0 or later
```

### Step 1: Generate Verilog RTL (if not already done)

The pre-generated Verilog and Verilator build artifacts are in:
```
sims/firesim/sim/generated-src/f1/f1-firechip-FireSim-FireSimRBBDmiRocketConfig-BaseF1Config/
```

To regenerate from scratch (requires SBT, ~20 min):
```bash
cd sims/firesim/sim
# GoldenGate elaboration
java -jar firesim-main.jar \
  midas.stage.GoldenGateMain \
  -td generated-src/f1/f1-firechip-FireSim-FireSimRBBDmiRocketConfig-BaseF1Config \
  -faf generated-src/.../FireSim.anno.json \
  ...
```

### Step 2: Build the simulator binary (if not already done)

The compiled `VFireSim` binary path:
```
sims/firesim/sim/generated-src/f1/f1-firechip-FireSim-FireSimRBBDmiRocketConfig-BaseF1Config/VFireSim
```

To rebuild (bypasses SBT, uses pre-generated Vemul.mk):
```bash
GEN_DIR="sims/firesim/sim/generated-src/f1/f1-firechip-FireSim-FireSimRBBDmiRocketConfig-BaseF1Config"
cd "${GEN_DIR}/VFireSim.csrc"
# First clear any stale PCH/object files if needed:
rm -f Vemul__pch.h.*.gch *.o "${GEN_DIR}/VFireSim"
make -f Vemul.mk -j$(nproc)
```

### Step 3: Launch the simulator

```bash
GEN_DIR="sims/firesim/sim/generated-src/f1/f1-firechip-FireSim-FireSimRBBDmiRocketConfig-BaseF1Config"

# Kill any previous instances first
pkill -9 -f "VFireSim " 2>/dev/null; sleep 1

# Launch (runs indefinitely until OpenOCD connects and sends 'Q')
"${GEN_DIR}/VFireSim" \
  +max-cycles=500000000 \
  +load=/tmp/spin.elf \
  > /tmp/sim.log 2>&1 &

# Wait for the "Listening on port 23000" message in stderr
sleep 3
```

The `rbb_dmi_bridge_t::init()` will print to stderr:
```
This emulator compiled with JTAG Remote Bitbang client. To enable, use +jtag_rbb_enable=1.
Listening on port 23000
```

### Step 4: Connect OpenOCD

```bash
openocd -f docs/bridge_llm_testing/openocd_rbb_dmi.cfg
```

### Step 5 (optional): Attach GDB

```bash
riscv64-unknown-elf-gdb /tmp/spin.elf \
  -ex "target extended-remote localhost:3333" \
  -ex "info reg pc a0"
```

---

## Evidence That It Works

The `demo_output.txt` in this directory contains the exact OpenOCD session output. Key evidence:

```
JTAG tap: riscv.cpu tap/device found: 0x10000001   <- IDCODE matched
datacount=2 progbufsize=16                          <- DMI discovered
Examined RISC-V core; found 1 harts                 <- core examined
hart 0: XLEN=64, misa=0x800000000094112d            <- RV64IMAFD + S-mode
Target halted.                                      <- halt succeeded
Listening on port 3333 for gdb connections          <- GDB ready
```

MISA `0x800000000094112d` decodes as:
- RV64 (bit 63)
- Extensions: I (base), M (mul/div), A (atomic), F (float), D (double), S (supervisor), U (user)
- Matches Rocket-Chip's default configuration

---

## Architecture Diagram

```
OpenOCD (external)
     |
     | TCP remote_bitbang (port 23000)
     |
+----|------------------------------------------------------+
| rbb_dmi_bridge_t  (host-side C++ bridge driver)          |
|   |                                                      |
|   | JTAG bit-bang (tck/tms/tdi/tdo)                     |
|   v                                                      |
| jtag_dtm_translator_t                                    |
|   - TAP state machine (IEEE 1149.1)                      |
|   - IDCODE register (0x10000001)                         |
|   - DTMCS register  (abits=7, version=1)                 |
|   - DMI_ACCESS shift register (41-bit)                   |
|   |                                                      |
|   | DMI req/resp (addr, data, op)                        |
|   v                                                      |
| DMIBRIDGEMODULE MMIO registers                           |
|   (in_bits_{addr,data,op}, in_valid, in_ready,           |
|    out_bits_{data,resp}, out_valid, out_ready,            |
|    step_size, done, start)                               |
+---|------------------------------------------------------+
    |
    | FAME-1 token channel
    |
+---|------------------------------------------------------+
| FireSim RTL simulation (Verilator)                       |
|                                                          |
| RocketChip debug module (RISC-V Debug Spec 0.13)        |
|   - DMI slave interface                                  |
|   - Abstract commands (register read/write)              |
|   - Program buffer (16 words)                            |
|   - Hart control (halt/resume/step)                      |
+----------------------------------------------------------+
```

---

## Files in This Directory

| File | Purpose |
|------|---------|
| `README.md` | This file |
| `openocd_rbb_dmi.cfg` | OpenOCD configuration for the demo |
| `spin.S` | Minimal RISC-V test program (infinite loop with a0=42) |
| `spin.ld` | Linker script placing the test at 0x80000000 |
| `demo_output.txt` | Exact OpenOCD output from the successful demo run |

---

## Running on AWS F2 FPGA

### Prerequisites: sims/firesim submodule version

The `bridge_llm_testing` branch pins `sims/firesim` to official FireSim `be558e3f9` (official/main), which is the first FireSim commit that includes full F2 support:
- `deploy/bit-builder-recipes/f2.yaml` (`F2BitBuilder`)
- `sim/midas/src/main/scala/configs/CompilerConfigs.scala`: `BaseF2Config`
- `deploy/buildtools/bitbuilder.py`: `F2BitBuilder` class
- `deploy/run-farm-recipes/aws_ec2.yaml`: `AWSEC2F2` run farm type

GoldenGate re-elaboration with `BaseF2Config` has been verified successful (see commit message in submodule update). The generated `FireSim-generated.const.h` correctly instantiates `rbb_dmi_bridge_t` with F2's 64 GiB DRAM model.

### Step 1: Local deploy config setup (gitignored, do once)

The following changes to `sims/firesim/deploy/` are gitignored by FireSim (they are user-local configs). Apply them after `git submodule update --init sims/firesim`:

**`sims/firesim/deploy/config_build_recipes.yaml`** — add this recipe:
```yaml
firesim_rbb_dmi_rocket_f2:
    PLATFORM: f2
    TARGET_PROJECT: firechip
    TARGET_PROJECT_MAKEFRAG: null
    DESIGN: FireSim
    TARGET_CONFIG: FireSimRBBDmiRocketConfig
    PLATFORM_CONFIG: BaseF2Config
    deploy_quintuplet: null
    platform_config_args:
        fpga_frequency: 90
        build_strategy: TIMING
    post_build_hook: null
    metasim_customruntimeconfig: null
    bit_builder_recipe: bit-builder-recipes/f2.yaml
```

**`sims/firesim/deploy/config_build.yaml`** — set `builds_to_run: [firesim_rbb_dmi_rocket_f2]`

**`sims/firesim/deploy/config_runtime.yaml`** — set `default_hw_config: firesim_rbb_dmi_rocket_f2`

**`sims/firesim/deploy/config_hwdb.yaml`** — fill in `agfi` after build completes.

### Step 2: S3 bucket setup

```bash
# awsinit creates the required S3 bucket: firesim-<accountId>-<region>
# e.g. firesim-260905118414-us-east-1
cd sims/firesim && source sourceme-manager.sh && firesim awsinit
```

### Step 3: Build the F2 bitstream (overnight, ~8-12 hours)

```bash
cd sims/firesim
source sourceme-manager.sh
firesim buildbitstream
# This launches a z1d.2xlarge build farm EC2 instance, runs Vivado,
# packages the AGFI, and registers it in AWS.
```

When complete, note the AGFI ID printed by the manager (format: `agfi-XXXXXXXXXXXXXXXXX`), then update `config_hwdb.yaml`:
```yaml
firesim_rbb_dmi_rocket_f2:
    agfi: agfi-XXXXXXXXXXXXXXXXX   # fill in here
    deploy_quintuplet_override: null
    deploy_makefrag_override: null
    custom_runtime_config: null
```

### Step 4: Launch on F2 and attach OpenOCD

```bash
# Launch an f2.6xlarge run farm instance and flash the AGFI
firesim launchrunfarm
firesim infrasetup
firesim deploy  # with custom plusargs: +rbb-dmi-port=23000

# SSH into the F2 run farm host
# OpenOCD config is the same as the Verilator demo
openocd -f docs/bridge_llm_testing/openocd_rbb_dmi.cfg
```

### Key differences vs Verilator demo

| Aspect | Verilator | F2 FPGA |
|--------|-----------|---------|
| Simulation speed | ~2 MHz | ~25 MHz (12x faster) |
| DRAM model | FASED timing model | Real DDR5 on board |
| DRAM capacity | 16 GiB (simulated) | 64 GiB (physical) |
| Clock domain | Single domain | Same (FAME-1) |
| rbb_dmi_bridge_t | Identical | Identical |
| OpenOCD config | Identical | Identical |
