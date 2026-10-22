# HBM2-2000 command replay

`hbm2-2000-refsb-interleaved-one-port.csv` comes from one FASED bridge.
`ramulator-2000-refsb-one-port.log` is its valid independent Ramulator replay:
36,915 commands and zero timing/state violations.
`hbm2-2000-refsb-sequential-one-port.csv` is a second valid replay of the
sequential-address control: 36,819 commands and zero violations.

The `*-four-port.csv` and `ramulator-2000-refsb-four-port.log` files are a
**rejected experiment**, not evidence of DRAM violations. Four independent
FASED bridges print untagged command lines to the same console. The old
parser silently merged them into one channel, producing nonsensical
same-cycle duplicate commands and apparent failures. The parser now rejects
such multi-bridge untagged logs before creating a trace. The four-port
throughput runs remain valid; their model counters and target responses were
checked separately.
