# Exact five-bridge runtime profiles

These files configure the five independent FASED memory-model bridges in
`FireSimE4M3MxGemminiTwoClusterHBMRadianceConfig`: bridge 0 is the host memory
region and bridges 1 through 4 are the four GPU regions.

Files ending in `.source.conf` are reviewable, unsuffixed inputs. **Never pass
them to a FireSim driver.** Per-model parsing only recognizes
`+mm_<register>_<bridge-id>=<value>`. An unsuffixed key is skipped, after which
the hardened driver rejects the empty or incomplete model configuration unless
the explicit hardware-default opt-in is present. This controlled flow forbids
that opt-in.
Files ending in `-5bridge.conf` are the deployable expansions for exact IDs
0 through 4.

## Profiles

- `hbm2-FRFCFS-2400-OP-REFab`: the model's stock HBM2-2400 count table. Those
  counts describe an approximately 0.833 ns HBM CK, but this target advances
  the model at 1 ns. It is retained as the current-code baseline and must not
  be described as time-correct HBM2-2400.
- `hbm2-FRFCFS-2000-OP-REFab`: the checked-in HBM2-2000 table. Its 1 ns CK
  aligns with the generated 1 GHz model tick and it uses the same bitstream;
  it is the clock-aligned HBM sensitivity point.
- `ddr3-FRFCFS-8G-4R-2133-OP`: the controlled DDR model for
  `FRFCFS8GBQuadRank`, derived from the checked-in Micron 2048 Mb, x8, sg093
  table at 1 GHz with four ranks and the baseline open-page mapping.

All three profiles use a compile-time/effective scheduler window and
transaction queue depth of eight. A focused RTL experiment proved that the
window's narrow field maps both programmed 0 and 8 to the full eight-entry
capacity. `transactionQueueDepth` is an exposed but disconnected no-op
register; keep it at 8 for provenance and never interpret a runtime queue-depth
sweep as changing the model.

## Generation and tests

The generated files were produced from the exact target annotation JSON:

```sh
python3 -B investigation/expand_fased_runtime_config.py \
  investigation/runtime-configs/<profile>.source.conf \
  --annotations sims/firesim-staging/generated-src/\
firechip.chip.FireSim.FireSimE4M3MxGemminiTwoClusterHBMRadianceConfig/\
firechip.chip.FireSim.FireSimE4M3MxGemminiTwoClusterHBMRadianceConfig.anno.json \
  > investigation/runtime-configs/<profile>-5bridge.conf
```

Run the source-table, annotation, and expansion checks from the Chipyard root:

```sh
python3 -B -m unittest -v \
  investigation/test_expand_fased_runtime_config.py \
  investigation/test_hbm_runtime_profiles.py \
  investigation/test_ddr_runtime_profile.py \
  investigation/test_expanded_runtime_profiles.py \
  investigation/test_exact_target_architecture.py
```

The tests derive HBM timings from `HBMModel.scala`, DDR timings from the pinned
Micron JSON, require the exact five bridge IDs/address regions, confirm the
1 GHz clock summary, and reproduce each deployable file byte for byte.

## SHA-256

```text
592294830e684f51487d3ab12a4d0ede8a3ee60bb3403c46652b151687427f2f  ddr3-FRFCFS-8G-4R-2133-OP.source.conf
af92398e9db6acf877fc5373db406e78bc2c8841a33911480e8a40945a0c3ed3  hbm2-FRFCFS-2000-OP-REFab.source.conf
9212d7c7d7417ec591a608136289eb0ef7c27311273a0a029d883db7518e11f9  hbm2-FRFCFS-2400-OP-REFab.source.conf
dc133659c8f8e4a8cfd14e6779a373bbcb005cc7143507320d1edf5e1014fc6a  ddr3-FRFCFS-8G-4R-2133-OP-5bridge.conf
2d45764907b723a66dc30a4547f9ed10d122a9da8132e5380febac76f80fd5ab  hbm2-FRFCFS-2000-OP-REFab-5bridge.conf
372af4e4a05a168bcdcc37dd853f6dbf3849b6c3585fc595b31522290f852cf8  hbm2-FRFCFS-2400-OP-REFab-5bridge.conf
```

Deployment copies belong under FireSim's `sim/custom-runtime-configs`; use
bare filenames in manager YAML and verify their hashes against this canonical
directory. Do not use symlinks or path traversal.
