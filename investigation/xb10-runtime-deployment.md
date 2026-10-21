# Corigine XB10 host-only runtime deployment audit

Audit date: 2026-10-21 PDT

Status: the manager schemas, exact workload resolution, address-hash loading
path, single-slot topology, campaign rules, and canonical FASED profiles parse
and validate. The files are deliberately fail-closed templates. No SSH
connection, FPGA device, Vivado process, driver, or programming action was
opened by this audit.

## Files

- `xb10-runtime-hwdb.template.yaml`: one physical HBM entry, one physical DDR
  entry, and an HBM2-2000 runtime alias. YAML anchors and validation force the
  alias to reuse the exact HBM bitstream and driver artifacts.
- `xb10-runtime-hbm.template.yaml`, `xb10-runtime-hbm2000.template.yaml`, and
  `xb10-runtime-ddr.template.yaml`: one-node/one-logical-slot runtime files for
  HBM2-2400, HBM2-2000 sensitivity, and DDR3-2133. All require the same
  coordinated one-entry FPGA database.
- `xb10-runtime-campaign.yaml`: the exact nine cases, ELF hashes, five-index
  FASED profiles, and repetition/retention policy.
- `workloads/xb10-two-sm-hashed-timed-*.json`: nine uniform-mode, one-job
  workload files. Each resolves directly to its audited ELF; no binary is
  copied or transformed by these definitions.
- `validate_xb10_runtime_configs.py`: template-mode and deployment-ready
  validation. It does not contact a run host.

## Exact manager loading path

The FireSim CLI uses `-c` for the runtime YAML, `-a` for the HWDB, and `-r` for
the build-recipe database. Relative paths inside the run-farm recipe are
interpreted from `sims/firesim/deploy` because the `firesim` entry point changes
to that directory before parsing.

For this flow:

1. `InnerRuntimeConfiguration` reads the runtime YAML and deep-merges its
   overrides into `run-farm-recipes/externally_provisioned.yaml`.
2. `RuntimeHWDB` reads `bitstream_tar`, optional `driver_tar`, metadata
   overrides, and the required `custom_runtime_config` key. Exactly one of
   `agfi` and `bitstream_tar` may be present; XB10 uses `bitstream_tar`.
3. The bitstream tar metadata supplies the exact deploy quintuplet. The
   template deliberately leaves both deploy overrides `null`, so a mismatched
   bitstream cannot be disguised with YAML.
4. A bare `custom_runtime_config` filename resolves under
   `sims/firesim/sim/custom-runtime-configs`. The manager copies that file into
   the driver bundle and expands its lines into simulator plusargs. It does not
   add FASED model indices. The HBM and DDR deployment copies must therefore be
   byte-identical to the canonical five-index files under
   `investigation/runtime-configs`. These are HBM2-2400, HBM2-2000, and
   DDR3-2133; every file carries explicit suffixes `_0` through `_4`.
5. `WorkloadConfig` reads the selected JSON below `deploy/workloads`. The
   checked-in relative reference reaches `investigation/workloads`, and each
   JSON's `common_bootbinary` resolves to one exact hashed/timed
   `kernel.soc.elf` under `radiance-kernels`.
6. The manager copies that ELF into `sim_slot_0` and passes its remote name as
   `+prog0=...` after `+permissive-off`.

### Why the hashed ELFs are correct

Although `+prog0` is owned by the TSI bridge, the current FireSim bridge is not
performing a serialized target-fabric program load. The target has ExtMem and a
FASED bridge, so `firesim_tsi_t` sets `has_loadmem = can_have_loadmem`. FESVR
parses the ELF into address/data writes; `tsibridge_t` intercepts those writes
and calls `loadmem_widget.write_mem_chunk(address + host_offset, ...)`. That is
a direct FPGA-DRAM write and does not cross Radiance's front-bus address hash.

Consequently, both controlled bitstreams must receive the already scrambled
`MU_ADDR_HASH=1` fused SoC ELFs. They have hash size `0x80000000`, 32-byte
units, four slices, GPU base `0x100000000`, and a
`.radiance_addr_hash` section. Supplying an unhashed ELF through this LoadMem
path would place GPU segments incorrectly. Conversely, forcing the hashed ELF
through pure serial TSI would apply the target hash a second time. Do not add
`+loadmem=kernel.soc.elf`: that simulator option consumes a raw memory image,
not this ELF-aware FESVR path.

The HBM and DDR builds share the identical hashed Radiance target and differ
only in the FASED platform model, so they use the same nine ELFs.

## One logical slot is not a physical-slot selector

The runtime templates replace the base run-farm host-spec list with one custom
spec whose `num_fpgas` is exactly 1. This creates only logical `sim_slot_0`.
The XB10 deploy manager then indexes database entry 0 for both:

- `uid`, when constructing the JTAG programming map; and
- `bdf`, when starting the PCIe driver.

There is no runtime-YAML field that maps logical slot 0 to an arbitrary entry
of the shared eight-card `/opt/firesim-db.json`. Pointing a one-slot topology at
that database would silently select its first card. All three templates therefore
retain `__REPLACE_WITH_COORDINATED_ONE_ENTRY_FPGA_DB_JSON__`, and the validator
forbids `/opt/firesim-db.json`.

After an owner and physical card are explicitly coordinated, create a separate
database containing exactly that existing card's `uid`, `device`, and `bdf`.
Use the same one-entry file for all three conditions. Do not invent any values,
and do not run `enumeratefpgas`: on XB10 that task unloads/reloads XDMA and
interacts with the device.

## Driver-bundle constraint

An external `driver_tar` causes the manager to skip local driver construction
and tarball creation. In that mode the custom runtime config is not copied as a
separate loose file; it must already be inside `driver-bundle.tar.gz` alongside
the nonempty `FireSim-corigine_xb10` executable and its libraries. The two
physical builds therefore have distinct driver-tar placeholders. The HBM2400
and HBM2000 HWDB entries share the exact HBM placeholder, so that one bundle
must contain both audited HBM profiles. Deployment-ready validation checks
both canonical hashes, the driver register names, and five FASED constructor
IDs.

Once both bitstream tars exist, a matching bundle can be produced host-only by
using a temporary HWDB with `driver_tar: null` and invoking `firesim
builddriver` separately for each physical build. That operation fetches the
bitstream metadata, builds the exact deploy-quintuplet driver, and writes
`sim/output/corigine_xb10/<deploy-quintuplet>/driver-bundle.tar.gz`. It is not
needed until the bitstreams and manager-visible profiles exist, and was not run
in this audit. Before declaring the HBM bundle final, package both HBM profile
files beside its one HBM driver; do not build a second physical HBM image.

## Campaign contract

FireSim assigns one explicit workload-list element per simulation node. With
one node, a JSON containing nine `workloads` entries would assign only element
0; the other eight would not become sequential jobs. The campaign therefore
uses nine separate uniform-mode JSON files and selects exactly one per manager
invocation.

For every one of the nine cases and all three runtime conditions (DDR3-2133,
HBM2-2400 current-code baseline, and HBM2-2000 1 ns-aligned sensitivity):

- label and exclude the first run;
- capture at least five complete independent runs;
- alternate runtime-condition order across run blocks when practical;
- retain every correctness result, including failures; and
- never silently retry or discard a failed run.

This is at least 162 total invocations: 27 labelled excluded first runs plus
135 captured results. Changing a workload path does not authorize a run; every
invocation still requires the shared-FPGA safety gate.

## Validation

Template validation currently passes with expected blockers:

```bash
source /scratch/trazzaque/tools/miniforge/etc/profile.d/conda.sh
conda activate /scratch/trazzaque/chipyard/.conda-env
cd /scratch/trazzaque/chipyard
python3 investigation/validate_xb10_runtime_configs.py
```

On the audited VM this exited 0 and reported passes for the exact 20 MHz
TIMING build pair, nine ELF hashes/manifests/address-hash sections, the source
`+prog0`/LoadMem path, the manager parsers, FASED IDs 0 through 4, the
single-slot topology, two-physical-build/three-runtime-condition reuse, and the
162-invocation/135-capture campaign arithmetic.
It reported only the expected template blockers listed below.

The exact command above was repeated from `/scratch/trazzaque/chipyard` after
an explicit activation and exited 0. `/usr/bin/python3
investigation/validate_xb10_runtime_configs.py` exited 1 with a direct
diagnostic naming the missing `fabric` dependency and the two activation
commands; the validator does not silently skip FireSim's real parsers outside
the pinned environment.

Two focused fail-closed checks also passed: calling
`validate_one_entry_fpga_db(Path('/opt/firesim-db.json'))` rejected its eight
entries, and calling `validate_fased_profile` on the checked-in unsuffixed
`hbm2-FRFCFS-2400-OP-REFab.conf` rejected the missing `_0` through `_4`
indices. Running the checked-in templates with `--ready` exited 1 at the first
missing manager-visible five-index profile, as intended; it did not continue
to any host or device operation.

After filling copies of the four templates, run the stronger local audit:

```bash
source /scratch/trazzaque/tools/miniforge/etc/profile.d/conda.sh
conda activate /scratch/trazzaque/chipyard/.conda-env
cd /scratch/trazzaque/chipyard
python3 investigation/validate_xb10_runtime_configs.py \
  --ready \
  --hwdb /scratch/trazzaque/xb10-runtime/config_hwdb.yaml \
  --hbm-runtime /scratch/trazzaque/xb10-runtime/config_runtime_hbm.yaml \
  --hbm2000-runtime /scratch/trazzaque/xb10-runtime/config_runtime_hbm2000.yaml \
  --ddr-runtime /scratch/trazzaque/xb10-runtime/config_runtime_ddr.yaml
```

Ready mode requires local paths or `file://` URIs so it can inspect, without
extracting, both bitstream tars and both driver tars. It checks the exact
quintuplet metadata, `corigine_xb10/firesim.bit`, driver executable, bundled
profile hashes, one-entry FPGA DB schema, manager parsing, all nine ELF hashes,
the controlled physical HBM/DDR difference, and exact HBM artifact reuse by
the HBM2-2000 runtime alias.

## Remaining blockers and destructive boundary

- Neither 20 MHz TIMING bitstream tar exists yet.
- Matching driver bundles cannot be finalized until those bitstream metadata
  and the manager-visible five-index profiles exist.
- The canonical five-index profile audit/copy is owned by the runtime-config
  audit and is still a prerequisite.
- A physical card/owner has not been coordinated, so no one-entry FPGA DB may
  be created yet.
- Localhost SSH authentication is unresolved. No SSH or authorization state was
  changed here.

`firesim infrasetup` is the programming boundary on this port: it copies and
extracts artifacts, disconnects PCIe, constructs a JTAG fleet map, programs all
assigned logical slots, reconnects PCIe, and reloads/chmods XDMA as needed.
`firesim boot` and `firesim runworkload` open the selected device. Do not run
any of those tasks until the artifacts pass `--ready`, localhost SSH is fixed
with explicit approval, and the single physical card is coordinated.
