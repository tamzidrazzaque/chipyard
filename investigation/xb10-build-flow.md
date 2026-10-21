# Corigine XB10 controlled-pair build audit

Audit date: 2026-10-21 PDT

Status: the build recipes parse and the Vivado 2025.1 device/IP catalog is
usable. No Vivado build was launched and no FPGA was opened, programmed, or
otherwise touched. FireSim commit
`590ebc4e7e1061a7b96bb333b7c692701a791bac` also makes the manager key path,
remote Vivado activation, archive contracts, and selected-card safety checks
explicit. The manager must not be launched until localhost SSH authentication
is separately resolved.

## Controlled pair

The recipes are in `xb10-build-recipes.yaml`. Both use:

- `PLATFORM=corigine_xb10`
- `TARGET_PROJECT=firesim`
- `DESIGN=FireSim`
- `TARGET_CONFIG=FireSimE4M3MxGemminiTwoClusterHBMRadianceConfig`
- 20 MHz FPGA host clock
- `TIMING` implementation strategy
- `CorigineXB10BitBuilder`

The only recipe-field difference is `PLATFORM_CONFIG`:

- HBM: `HBM2FRFCFS16GBDualPC_BaseCorigineXB10Config`
- timed DDR control: `FRFCFS8GBQuadRank_BaseCorigineXB10Config`

Use `xb10-build-hbm.yaml` and `xb10-build-ddr.yaml` sequentially. FireSim's
`ExternallyProvisioned` build farm assigns one distinct host to each requested
build and rejects a duplicate host address. Therefore, putting both recipes in
one build selector cannot use a single `localhost` safely.

`xb10-empty-hwdb.yaml` exists only because `BuildConfigFile` always parses an
HWDB, even for `buildbitstream`.

## Validated without building

The following checks passed:

- Both build selectors parse through FireSim's real `BuildConfigFile` and
  resolve to `CorigineXB10BitBuilder`, board `xb10`, localhost, and
  `/scratch/trazzaque/firesim-buildfarm`.
- A YAML dictionary comparison asserts that the two recipes differ only in
  `PLATFORM_CONFIG`.
- `/ecad/tools/xilinx/2025.1/Vivado/settings64.sh` activates Vivado 2025.1,
  software build 6140274, including from a clean shell with only
  `/usr/bin:/bin` initially on PATH.
- An in-memory Vivado 2025.1 project finds part
  `xcvu19p-fsvb3824-2-e` and the required catalog entries: XDMA 4.2, DDR4
  2.2, clock wizard 6.0, AXI data-width converter 2.1, and processor-system
  reset 5.0.
- `platforms/corigine_xb10/build-bitstream.sh` passes `bash -n`.
- Thirteen focused deploy tests pass. They cover the historical manager-key
  default, environment override, shell quoting, optional settings activation,
  missing settings, wrong Vivado version, and the complete XB10 shell argument
  path using a fake executable. No real Vivado process is started by the tests.
- At audit time the host had about 478 GiB available memory and 1.3 TiB free
  under `/scratch`; the port requests eight Vivado jobs.

Repeat the configuration parse and controlled-difference assertion in the
locked Chipyard environment with:

```bash
source /scratch/trazzaque/tools/miniforge/etc/profile.d/conda.sh
conda activate /scratch/trazzaque/chipyard/.conda-env
/scratch/trazzaque/chipyard/investigation/validate_xb10_build_configs.py
```

## Blocking preconditions

### Localhost SSH

The manager does not special-case localhost: Fabric and rsync still connect to
`localhost` over SSH. Current state:

- sshd listens on TCP/22;
- `~/firesim.pem` is absent;
- the forwarded `SSH_AUTH_SOCK` path is stale and `ssh-add` cannot connect;
- localhost rejects public-key authentication;
- `authorized_keys` contains one ED25519 key with fingerprint
  `SHA256:1LDyigplKx2TQsrW5a7Ejbrs/THBFf+lS06ZF1rcqik`;
- the localhost ED25519 key saved in `known_hosts` has fingerprint
  `SHA256:nNLhzcrbYXMbmF1kKJ+sGHOlmgTvqLthDq1y7YhL7Kw`, while the currently
  served key has fingerprint
  `SHA256:rJ93HTc63Z5iFkiFaPhLbKMSsJ6wWD3HKF6rrCYnO0w`.

Do not blindly remove or replace the saved host key. Verify the live host key,
then either restore the private key matching the existing authorized key or,
with explicit approval, install a new loopback-restricted build key. Keep the
private key under `/scratch/trazzaque` with mode 0600. FireSim now accepts its
path through `FIRESIM_SSH_KEY`; when the variable is unset or empty, the
historical `~/firesim.pem` default remains unchanged.

FireSim currently sets `env.disable_known_hosts = True`, and its rsync calls use
`StrictHostKeyChecking=no`. That bypass is not evidence that the changed host
key is benign; it only explains why manager behavior can differ from a manual
SSH check.

### Vivado activation inside the SSH build shell (resolved in source)

The Corigine bit-builder now accepts an optional `vivado_settings` argument,
shell-quotes it, and passes it to `build-bitstream.sh`. The controlled recipes
set it to `/ecad/tools/xilinx/2025.1/Vivado/settings64.sh`. The remote build
shell verifies the settings file is readable, sources it, and fails before
project creation unless `vivado -version` reports exactly 2025.1. An omitted
setting still supports an already-configured PATH, with the same exact-version
guard.

## Exact build commands after preconditions pass

Run HBM and DDR sequentially, never concurrently:

```bash
source /scratch/trazzaque/tools/miniforge/etc/profile.d/conda.sh
conda activate /scratch/trazzaque/chipyard/.conda-env
source /scratch/trazzaque/chipyard/env.sh
source /ecad/tools/xilinx/2025.1/Vivado/settings64.sh
cd /scratch/trazzaque/chipyard/sims/firesim
source sourceme-manager.sh --skip-ssh-setup
export FIRESIM_SSH_KEY=/scratch/trazzaque/.firesim-auth/id_ed25519

firesim buildbitstream \
  -b /scratch/trazzaque/chipyard/investigation/xb10-build-hbm.yaml \
  -r /scratch/trazzaque/chipyard/investigation/xb10-build-recipes.yaml \
  -a /scratch/trazzaque/chipyard/investigation/xb10-empty-hwdb.yaml

firesim buildbitstream \
  -b /scratch/trazzaque/chipyard/investigation/xb10-build-ddr.yaml \
  -r /scratch/trazzaque/chipyard/investigation/xb10-build-recipes.yaml \
  -a /scratch/trazzaque/chipyard/investigation/xb10-empty-hwdb.yaml
```

Before each command, record the top-level and submodule commits, dirty diffs,
recipe hashes, Vivado version, and the absence of another Vivado build using the
shared host. `buildbitstream` generates files only; it does not authorize
programming an FPGA.

## Port-flow hazards to retain in the run log

1. `cl_dir_setup` removes the exact per-quintuplet directory below
   `/scratch/trazzaque/firesim-buildfarm/platforms/corigine_xb10`. Keep that
   directory dedicated to this flow.
2. If the first implementation misses setup or hold timing, the port sources
   `scripts/implementation_idr_ml/${vivado_version}.tcl`. Only 2021.1 and
   2022.2 scripts exist; there is no 2025.1 fallback. At 20 MHz the first pass
   should be favorable, but a miss must stop for a real 2025.1 fix rather than
   reusing an old-version script.
3. The board documentation identifies a 2 Gb configuration flash, while
   `post_impl.tcl` calls `write_cfgmem -size 1024`. Resolve that mismatch before
   any flash-programming experiment. The generated `.bit` and `.mcs` are not
   interchangeable deployment evidence.
4. The 20 MHz setting is the physical FPGA host clock. It does not change the
   target's modeled 1 GHz memory-bus clock.
5. Preserve timing and utilization reports for each build. A generated
   bitstream is not a successful build unless WNS and WHS are nonnegative and
   the report identifies the intended part, frequency, and source quintuplet.
